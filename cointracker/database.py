from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from heapq import nlargest
from pathlib import Path
from typing import Callable, Iterable, Optional

from .parser import Hand, parse_hand
from .equity import evaluator_available
from .handtable import starting_hand_label, starting_hand_type

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS hands (
    hand_id TEXT PRIMARY KEY,
    game TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    timezone TEXT,
    table_name TEXT,
    max_seats INTEGER,
    button_seat INTEGER,
    sb_cents INTEGER NOT NULL,
    bb_cents INTEGER NOT NULL,
    hero_name TEXT NOT NULL,
    hero_seat INTEGER,
    hero_position TEXT,
    hero_cards TEXT,
    board1 TEXT,
    board2 TEXT,
    board3 TEXT,
    run_count INTEGER NOT NULL DEFAULT 1,
    splash_type TEXT,
    splash_cents INTEGER NOT NULL DEFAULT 0,
    total_pot_cents INTEGER NOT NULL DEFAULT 0,
    rake_cents INTEGER NOT NULL DEFAULT 0,
    hero_contributed_cents INTEGER NOT NULL DEFAULT 0,
    hero_returned_cents INTEGER NOT NULL DEFAULT 0,
    hero_collected_cents INTEGER NOT NULL DEFAULT 0,
    hero_splash_won_cents INTEGER NOT NULL DEFAULT 0,
    hero_net_cents INTEGER NOT NULL DEFAULT 0,
    hero_allin_adj_cents REAL NOT NULL DEFAULT 0,
    hero_allin_equity REAL,
    hero_allin_adjusted INTEGER NOT NULL DEFAULT 0,
    hero_allin_estimated INTEGER NOT NULL DEFAULT 0,
    hero_vpip INTEGER NOT NULL DEFAULT 0,
    hero_pfr INTEGER NOT NULL DEFAULT 0,
    hero_three_bet INTEGER NOT NULL DEFAULT 0,
    hero_three_bet_opp INTEGER NOT NULL DEFAULT 0,
    hero_saw_flop INTEGER NOT NULL DEFAULT 0,
    hero_wtsd INTEGER NOT NULL DEFAULT 0,
    hero_won_sd INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hands_started ON hands(started_at);
CREATE INDEX IF NOT EXISTS idx_hands_stakes ON hands(sb_cents, bb_cents);
CREATE INDEX IF NOT EXISTS idx_hands_splash ON hands(splash_cents);
CREATE INDEX IF NOT EXISTS idx_hands_runs ON hands(run_count);
CREATE TABLE IF NOT EXISTS seats (
    hand_id TEXT NOT NULL REFERENCES hands(hand_id) ON DELETE CASCADE,
    seat_no INTEGER NOT NULL,
    player TEXT NOT NULL,
    stack_cents INTEGER NOT NULL,
    position TEXT,
    PRIMARY KEY(hand_id, seat_no)
);
CREATE INDEX IF NOT EXISTS idx_seats_player ON seats(player);
CREATE TABLE IF NOT EXISTS actions (
    hand_id TEXT NOT NULL REFERENCES hands(hand_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    street TEXT NOT NULL,
    run_index INTEGER NOT NULL,
    player TEXT NOT NULL,
    action TEXT NOT NULL,
    amount_cents INTEGER NOT NULL DEFAULT 0,
    to_cents INTEGER NOT NULL DEFAULT 0,
    aggressive INTEGER NOT NULL DEFAULT 0,
    raise_number INTEGER NOT NULL DEFAULT 0,
    raw TEXT,
    PRIMARY KEY(hand_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_actions_player ON actions(player);
CREATE TABLE IF NOT EXISTS player_results (
    hand_id TEXT NOT NULL REFERENCES hands(hand_id) ON DELETE CASCADE,
    player TEXT NOT NULL,
    seat_no INTEGER,
    stack_cents INTEGER,
    position TEXT,
    contributed_cents INTEGER NOT NULL DEFAULT 0,
    returned_cents INTEGER NOT NULL DEFAULT 0,
    collected_cents INTEGER NOT NULL DEFAULT 0,
    splash_won_cents INTEGER NOT NULL DEFAULT 0,
    net_cents INTEGER NOT NULL DEFAULT 0,
    vpip INTEGER NOT NULL DEFAULT 0,
    pfr INTEGER NOT NULL DEFAULT 0,
    three_bet INTEGER NOT NULL DEFAULT 0,
    three_bet_opp INTEGER NOT NULL DEFAULT 0,
    saw_flop INTEGER NOT NULL DEFAULT 0,
    went_to_showdown INTEGER NOT NULL DEFAULT 0,
    won_showdown INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(hand_id, player)
);
CREATE INDEX IF NOT EXISTS idx_player_results_player ON player_results(player);
CREATE TABLE IF NOT EXISTS tracker_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rakeback_by_stake (
    bb_cents INTEGER PRIMARY KEY,
    sb_cents INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL DEFAULT 0 CHECK(amount_cents >= 0)
);
"""

# CoinPoker's standard published NLHE/PLO cash ladder. The UI also adds any
# other stakes already present in the user's hand-history database so VIP or
# uncommon games remain selectable.
COIN_CASH_STAKES = (
    (1, 2),
    (2, 5),
    (5, 10),
    (10, 25),
    (25, 50),
    (50, 100),
    (100, 200),
    (200, 500),
    (500, 1000),
    (1000, 2000),
    (2500, 5000),
    (5000, 10000),
)

CALCULATION_VERSION = "14-stable-rollback-v11-pot-layer-v1"
THREE_BET_CALCULATION_VERSION = "2-second-preflop-raise-verified"
POSITION_CALCULATION_VERSION = "2-five-handed-hj-verified"

class TrackerDB:
    def __init__(self, path: str | Path, migration_progress: Callable[..., None] | None = None):
        self.path = str(path)
        self.migration_progress = migration_progress
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.create_function(
            "starting_hand_label", 1, starting_hand_label, deterministic=True,
        )
        self.conn.executescript(SCHEMA)
        self._report_migration_progress(
            1, 5, "Database opened.\nChecking stored calculation fields…",
        )
        self.recalculated_count = 0
        self.recalculation_errors = 0
        self._ensure_columns()
        self._ensure_indexes()
        self._migrate_calculations_if_needed()
        self._report_migration_progress(
            2, 5, "Calculation fields checked.\nChecking 3-bet statistics…",
        )
        self._migrate_three_bet_flags_if_needed()
        self._report_migration_progress(
            3, 5, "3-bet statistics checked.\nChecking table positions…",
        )
        self._migrate_positions_if_needed()
        self._report_migration_progress(
            4, 5, "Database checks complete.\nLoading the tracker…",
        )
    def _ensure_columns(self):
        """Add columns needed by newer builds without replacing the user's DB."""
        hands_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(hands)")}
        results_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(player_results)")}
        with self.conn:
            if "hero_splash_won_cents" not in hands_cols:
                self.conn.execute(
                    "ALTER TABLE hands ADD COLUMN hero_splash_won_cents INTEGER NOT NULL DEFAULT 0"
                )
            if "splash_won_cents" not in results_cols:
                self.conn.execute(
                    "ALTER TABLE player_results ADD COLUMN splash_won_cents INTEGER NOT NULL DEFAULT 0"
                )
            if "hero_allin_adj_cents" not in hands_cols:
                self.conn.execute(
                    "ALTER TABLE hands ADD COLUMN hero_allin_adj_cents REAL NOT NULL DEFAULT 0"
                )
            if "hero_allin_equity" not in hands_cols:
                self.conn.execute(
                    "ALTER TABLE hands ADD COLUMN hero_allin_equity REAL"
                )
            if "hero_allin_adjusted" not in hands_cols:
                self.conn.execute(
                    "ALTER TABLE hands ADD COLUMN hero_allin_adjusted INTEGER NOT NULL DEFAULT 0"
                )
            if "hero_allin_estimated" not in hands_cols:
                self.conn.execute(
                    "ALTER TABLE hands ADD COLUMN hero_allin_estimated INTEGER NOT NULL DEFAULT 0"
                )

    def _ensure_indexes(self):
        """Add lookup indexes introduced after the original database schema."""
        indexes = {
            row[1]
            for row in self.conn.execute("PRAGMA index_list(actions)")
        }
        if "idx_actions_three_bet" in indexes:
            return
        with self._database_update_progress(
            0,
            1,
            "Optimizing the action history for regression checks…\n"
            "This is a one-time database update.",
        ), self.conn:
            self.conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_actions_three_bet
                   ON actions(
                       street, raise_number, aggressive, action, hand_id, player
                   )"""
            )
    def _meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM tracker_meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO tracker_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def _report_migration_progress(
        self,
        completed: int,
        total: int,
        message: str,
    ):
        if self.migration_progress:
            self.migration_progress(completed, total, message)

    def _migrate_calculations_if_needed(self):
        if self._meta("calculation_version") == CALCULATION_VERSION:
            return
        self.recalculated_count = self.recalculate_all_hands()
        # Never mark a migration complete if one or more stored hands failed to
        # reparse. Older builds silently did this, which could leave a mixture of
        # stale and new EV values in the same database.
        if self.recalculation_errors == 0:
            with self.conn:
                self._set_meta("calculation_version", CALCULATION_VERSION)
    def _migrate_three_bet_flags_if_needed(self):
        """Repair old 4-bet+ flags using the stored, correctly numbered actions.

        The old parser recorded every preflop raise after the opener as a
        3-bet. Its action raise numbers and opportunity flags were already
        correct, so this repair only needs to rebuild the 3-bet flags. A
        separate version avoids rerunning costly all-in equity calculations.
        """
        marker_is_current = (
            self._meta("three_bet_calculation_version")
            == THREE_BET_CALCULATION_VERSION
        )
        needs_repair = self._three_bet_flags_need_repair()
        if marker_is_current and not needs_repair:
            return
        if not needs_repair:
            with self.conn:
                self._set_meta(
                    "three_bet_calculation_version",
                    THREE_BET_CALCULATION_VERSION,
                )
            return
        three_bettors = """SELECT hand_id, player FROM actions
            WHERE street = 'PREFLOP' AND raise_number = 2
              AND aggressive = 1 AND action IN ('RAISE', 'ALLIN')"""
        with self._database_update_progress(
            0, 2, "Repairing 3-bet statistics…\nUpdating hand summaries (step 1 of 2).",
        ) as report_progress, self.conn:
            self.conn.execute(
                f"""UPDATE hands SET hero_three_bet =
                    (hand_id, hero_name) IN ({three_bettors})"""
            )
            report_progress(
                1,
                "Repairing 3-bet statistics…\nUpdating player results (step 2 of 2).",
            )
            self.conn.execute(
                f"""UPDATE player_results SET three_bet =
                    (hand_id, player) IN ({three_bettors})"""
            )
            self._set_meta("three_bet_calculation_version", THREE_BET_CALCULATION_VERSION)

    def _three_bet_flags_need_repair(self) -> bool:
        """Check stored flags even if an earlier build wrote a migration marker."""
        queries = (
            (
                "hand summaries already marked as 3-bets",
                """SELECT 1 FROM hands AS stored
                WHERE stored.hero_three_bet NOT IN (0, 1)
                   OR (
                    stored.hero_three_bet = 1 AND NOT EXISTS (
                    SELECT 1 FROM actions AS action INDEXED BY idx_actions_three_bet
                    WHERE action.hand_id = stored.hand_id
                      AND action.player = stored.hero_name
                      AND action.street = 'PREFLOP'
                      AND action.raise_number = 2
                      AND action.aggressive = 1
                      AND action.action IN ('RAISE', 'ALLIN')
                    )
                ) LIMIT 1""",
            ),
            (
                "3-bet actions missing from hand summaries",
                """SELECT 1 FROM actions AS action INDEXED BY idx_actions_three_bet
                JOIN hands AS stored
                  ON stored.hand_id = action.hand_id
                 AND stored.hero_name = action.player
                WHERE action.street = 'PREFLOP'
                  AND action.raise_number = 2
                  AND action.aggressive = 1
                  AND action.action IN ('RAISE', 'ALLIN')
                  AND stored.hero_three_bet != 1
                LIMIT 1""",
            ),
            (
                "player results already marked as 3-bets",
                """SELECT 1 FROM player_results AS stored
                WHERE stored.three_bet NOT IN (0, 1)
                   OR (
                    stored.three_bet = 1 AND NOT EXISTS (
                    SELECT 1 FROM actions AS action INDEXED BY idx_actions_three_bet
                    WHERE action.hand_id = stored.hand_id
                      AND action.player = stored.player
                      AND action.street = 'PREFLOP'
                      AND action.raise_number = 2
                      AND action.aggressive = 1
                      AND action.action IN ('RAISE', 'ALLIN')
                    )
                ) LIMIT 1""",
            ),
            (
                "3-bet actions missing from player results",
                """SELECT 1 FROM actions AS action INDEXED BY idx_actions_three_bet
                JOIN player_results AS stored
                  ON stored.hand_id = action.hand_id
                 AND stored.player = action.player
                WHERE action.street = 'PREFLOP'
                  AND action.raise_number = 2
                  AND action.aggressive = 1
                  AND action.action IN ('RAISE', 'ALLIN')
                  AND stored.three_bet != 1
                LIMIT 1""",
            ),
        )
        with self._database_update_progress(
            0,
            len(queries),
            "Checking 3-bet statistics…\nStarting regression check 1 of 4.",
            finish=False,
        ) as report_progress:
            for index, (description, query) in enumerate(queries, 1):
                report_progress(
                    index - 1,
                    "Checking 3-bet statistics…\n"
                    f"Checking {description} ({index} of {len(queries)}).",
                )
                if self.conn.execute(query).fetchone():
                    return True
                report_progress(
                    index,
                    "Checking 3-bet statistics…\n"
                    f"Completed regression check {index} of {len(queries)}.",
                )
        return False

    def _migrate_positions_if_needed(self):
        """Move the old five-handed UTG labels to HJ in every stored table.

        Count the seats recorded for each hand, not the table's maximum
        capacity. Six-handed UTG remains UTG, and no equity recalculation or
        hand-history re-import is required.
        """
        marker_is_current = (
            self._meta("position_calculation_version")
            == POSITION_CALCULATION_VERSION
        )
        needs_repair = self._positions_need_repair()
        if marker_is_current and not needs_repair:
            return
        if not needs_repair:
            with self.conn:
                self._set_meta(
                    "position_calculation_version",
                    POSITION_CALCULATION_VERSION,
                )
            return
        five_handed = """SELECT hand_id FROM seats
            GROUP BY hand_id HAVING COUNT(*) = 5"""
        with self._database_update_progress(
            0, 3, "Repairing five-handed positions…\nUpdating hands (step 1 of 3).",
        ) as report_progress, self.conn:
            tables = (
                ("hands", "hero_position"),
                ("seats", "position"),
                ("player_results", "position"),
            )
            for index, (table, column) in enumerate(tables, 1):
                self.conn.execute(
                    f"""UPDATE {table} SET {column} = 'HJ'
                        WHERE {column} = 'UTG' AND hand_id IN ({five_handed})"""
                )
                if index < len(tables):
                    next_table = "seats" if index == 1 else "player results"
                    report_progress(
                        index,
                        "Repairing five-handed positions…\n"
                        f"Updating {next_table} (step {index + 1} of 3).",
                    )
            self._set_meta("position_calculation_version", POSITION_CALCULATION_VERSION)

    def _positions_need_repair(self) -> bool:
        """Find legacy five-handed UTG labels regardless of migration metadata."""
        tables = (
            ("hands", "hero_position"),
            ("seats", "position"),
            ("player_results", "position"),
        )
        with self._database_update_progress(
            0,
            len(tables),
            "Checking five-handed positions…\nStarting regression check 1 of 3.",
            finish=False,
        ) as report_progress:
            for index, (table, column) in enumerate(tables, 1):
                report_progress(
                    index - 1,
                    "Checking five-handed positions…\n"
                    f"Checking {table} (step {index} of {len(tables)}).",
                )
                row = self.conn.execute(
                    f"""SELECT 1 FROM {table} AS stored
                        WHERE stored.{column} = 'UTG'
                          AND 5 = (
                              SELECT COUNT(*) FROM seats
                              WHERE seats.hand_id = stored.hand_id
                          )
                        LIMIT 1"""
                ).fetchone()
                if row:
                    return True
                report_progress(
                    index,
                    "Checking five-handed positions…\n"
                    f"Completed regression check {index} of {len(tables)}.",
                )
        return False

    @contextmanager
    def _database_update_progress(
        self,
        completed: int,
        total: int,
        message: str,
        finish: bool = True,
    ):
        """Pump startup progress during SQL repairs and clean up on failure."""
        notify = self.migration_progress
        if not self.conn.execute("SELECT 1 FROM hands LIMIT 1").fetchone():
            notify = None
        state = {
            "completed": completed,
            "message": message,
        }

        def pump_events():
            notify(state["completed"], total, state["message"])
            return 0  # Continue SQLite execution; this is not a cancel action.

        def report_progress(new_completed: int, new_message: str):
            state["completed"] = new_completed
            state["message"] = new_message
            if notify:
                notify(new_completed, total, new_message)

        if notify:
            pump_events()
            # SQLite calls this during long statements, allowing the startup
            # window to repaint while the updates and commit are in progress.
            self.conn.set_progress_handler(pump_events, 10_000)
        try:
            yield report_progress
        finally:
            if notify:
                self.conn.set_progress_handler(None, 0)
        if notify and finish:
            notify(total, total, state["message"])

    def recalculate_all_hands(self) -> int:
        """Reparse stored raw HH so formula fixes apply to already-imported hands."""
        rows = self.conn.execute(
            "SELECT hand_id, hero_name, raw_text FROM hands ORDER BY started_at, hand_id"
        ).fetchall()
        if not rows:
            return 0

        total_rows = len(rows)
        self._report_migration_progress(
            0,
            total_rows,
            f"Recalculating stored hands…\nProcessed 0 of {total_rows:,}.",
        )
        hand_updates = []
        result_updates = []
        self.recalculation_errors = 0
        for index, row in enumerate(rows, 1):
            try:
                hand = parse_hand(row["raw_text"], hero_name=row["hero_name"] or "Hero")
            except Exception:
                # Keep the database usable, but do not silently claim that the
                # calculation migration completed. The UI exposes the failure count.
                self.recalculation_errors += 1
                continue
            hr = hand.hero_result
            hand_updates.append((
                hr.contributed_cents, hr.returned_cents, hr.collected_cents,
                hr.splash_won_cents, hr.net_cents, hr.allin_adj_cents, hr.allin_equity,
                int(hr.allin_adjusted), int(hr.allin_estimated), int(hr.vpip), int(hr.pfr), int(hr.three_bet),
                int(hr.three_bet_opp), int(hr.saw_flop), int(hr.went_to_showdown),
                int(hr.won_showdown), hand.hand_id,
            ))
            result_updates.extend((
                p.contributed_cents, p.returned_cents, p.collected_cents,
                p.splash_won_cents, p.net_cents, int(p.vpip), int(p.pfr),
                int(p.three_bet), int(p.three_bet_opp), int(p.saw_flop),
                int(p.went_to_showdown), int(p.won_showdown), hand.hand_id, p.player,
            ) for p in hand.player_results.values())
            # The UI throttles repaints, so report each completed hand. This
            # keeps progress alive even when a batch of 100 expensive equity
            # calculations would otherwise make startup look frozen.
            if self.migration_progress:
                self._report_migration_progress(
                    index,
                    total_rows,
                    "Recalculating stored hands…\n"
                    f"Processed {index:,} of {total_rows:,}.",
                )
        with self.conn:
            self.conn.executemany(
                """UPDATE hands SET
                    hero_contributed_cents=?, hero_returned_cents=?, hero_collected_cents=?,
                    hero_splash_won_cents=?, hero_net_cents=?, hero_allin_adj_cents=?,
                    hero_allin_equity=?, hero_allin_adjusted=?, hero_allin_estimated=?, hero_vpip=?, hero_pfr=?,
                    hero_three_bet=?, hero_three_bet_opp=?, hero_saw_flop=?, hero_wtsd=?,
                    hero_won_sd=? WHERE hand_id=?""",
                hand_updates,
            )
            self.conn.executemany(
                """UPDATE player_results SET
                    contributed_cents=?, returned_cents=?, collected_cents=?, splash_won_cents=?,
                    net_cents=?, vpip=?, pfr=?, three_bet=?, three_bet_opp=?, saw_flop=?,
                    went_to_showdown=?, won_showdown=? WHERE hand_id=? AND player=?""",
                result_updates,
            )
        return len(hand_updates)
    def close(self):
        self.conn.close()

    def import_hands(self, hands: Iterable[Hand]) -> tuple[int, int]:
        batch = list(hands)
        if not batch:
            return 0, 0
        ids = [h.hand_id for h in batch]
        existing: set[str] = set()
        # Keep comfortably under SQLite's parameter limit.
        for i in range(0, len(ids), 800):
            chunk = ids[i:i + 800]
            marks = ",".join("?" for _ in chunk)
            existing.update(r[0] for r in self.conn.execute(
                f"SELECT hand_id FROM hands WHERE hand_id IN ({marks})", chunk
            ).fetchall())
        new_hands = [h for h in batch if h.hand_id not in existing]
        duplicates = len(batch) - len(new_hands)
        if not new_hands:
            return 0, duplicates
        hand_rows = []
        seat_rows = []
        action_rows = []
        result_rows = []
        for hand in new_hands:
            hr = hand.hero_result
            boards = (hand.boards + ["", "", ""])[:3]
            hand_rows.append((
                hand.hand_id, hand.game, hand.started_at.isoformat(sep=" "),
                hand.ended_at.isoformat(sep=" ") if hand.ended_at else None,
                hand.timezone, hand.table_name, hand.max_seats, hand.button_seat,
                hand.sb_cents, hand.bb_cents, hand.hero_name, hand.hero_seat,
                hand.hero_position, hand.hero_cards, boards[0], boards[1], boards[2],
                hand.run_count, hand.splash_type, hand.splash_cents,
                hand.total_pot_cents, hand.rake_cents,
                hr.contributed_cents, hr.returned_cents, hr.collected_cents,
                hr.splash_won_cents, hr.net_cents, hr.allin_adj_cents, hr.allin_equity,
                int(hr.allin_adjusted), int(hr.allin_estimated), int(hr.vpip), int(hr.pfr), int(hr.three_bet), int(hr.three_bet_opp),
                int(hr.saw_flop), int(hr.went_to_showdown), int(hr.won_showdown),
                hand.raw_text,
            ))
            seat_rows.extend((hand.hand_id, s.seat_no, s.player, s.stack_cents, s.position) for s in hand.seats)
            action_rows.extend((
                hand.hand_id, a.seq, a.street, a.run_index, a.player, a.action,
                a.amount_cents, a.to_cents, int(a.aggressive), a.raise_number, a.raw
            ) for a in hand.actions)
            result_rows.extend((
                hand.hand_id, p.player, p.seat_no, p.stack_cents, p.position,
                p.contributed_cents, p.returned_cents, p.collected_cents, p.splash_won_cents, p.net_cents,
                int(p.vpip), int(p.pfr), int(p.three_bet), int(p.three_bet_opp), int(p.saw_flop),
                int(p.went_to_showdown), int(p.won_showdown)
            ) for p in hand.player_results.values())
        with self.conn:
            self.conn.executemany(
                """INSERT INTO hands (
                    hand_id, game, started_at, ended_at, timezone, table_name,
                    max_seats, button_seat, sb_cents, bb_cents, hero_name,
                    hero_seat, hero_position, hero_cards, board1, board2, board3,
                    run_count, splash_type, splash_cents, total_pot_cents, rake_cents,
                    hero_contributed_cents, hero_returned_cents, hero_collected_cents,
                    hero_splash_won_cents, hero_net_cents, hero_allin_adj_cents, hero_allin_equity, hero_allin_adjusted, hero_allin_estimated,
                    hero_vpip, hero_pfr, hero_three_bet, hero_three_bet_opp, hero_saw_flop, hero_wtsd, hero_won_sd, raw_text
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                hand_rows,
            )
            self.conn.executemany(
                "INSERT INTO seats(hand_id, seat_no, player, stack_cents, position) VALUES (?,?,?,?,?)",
                seat_rows,
            )
            self.conn.executemany(
                """INSERT INTO actions(hand_id, seq, street, run_index, player, action,
                   amount_cents, to_cents, aggressive, raise_number, raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                action_rows,
            )
            self.conn.executemany(
                """INSERT INTO player_results(hand_id, player, seat_no, stack_cents, position,
                   contributed_cents, returned_cents, collected_cents, splash_won_cents, net_cents,
                   vpip, pfr, three_bet, three_bet_opp, saw_flop, went_to_showdown, won_showdown)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                result_rows,
            )
        return len(new_hands), duplicates
    @staticmethod
    def _where(filters: dict | None) -> tuple[str, list]:
        filters = filters or {}
        clauses: list[str] = []
        params: list = []
        if filters.get("date_from"):
            clauses.append("date(started_at) >= date(?)")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            clauses.append("date(started_at) <= date(?)")
            params.append(filters["date_to"])
        if filters.get("bb_cents") is not None:
            clauses.append("bb_cents = ?")
            params.append(filters["bb_cents"])
        if filters.get("sb_cents") is not None:
            clauses.append("sb_cents = ?")
            params.append(filters["sb_cents"])
        if filters.get("splash") == "only":
            clauses.append("splash_cents > 0")
        elif filters.get("splash") == "exclude":
            clauses.append("splash_cents = 0")
        if filters.get("runs") == "multi":
            clauses.append("run_count > 1")
        elif filters.get("runs") == "once":
            clauses.append("run_count = 1")
        if filters.get("position"):
            clauses.append("hero_position = ?")
            params.append(filters["position"])
        if filters.get("contributed_bb_min") is not None:
            clauses.append(
                "(bb_cents > 0 AND "
                "CAST(hero_contributed_cents - hero_returned_cents AS REAL) "
                "/ bb_cents >= ?)"
            )
            params.append(float(filters["contributed_bb_min"]))
        if filters.get("contributed_bb_max") is not None:
            clauses.append(
                "(bb_cents > 0 AND "
                "CAST(hero_contributed_cents - hero_returned_cents AS REAL) "
                "/ bb_cents <= ?)"
            )
            params.append(float(filters["contributed_bb_max"]))
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def rakeback_stakes(self) -> list[tuple[int, int]]:
        """Return CoinPoker's standard cash stakes plus any stakes seen in this DB."""
        by_bb = {bb: (sb, bb) for sb, bb in COIN_CASH_STAKES}
        for sb, bb in self.distinct_stakes():
            by_bb[bb] = (sb, bb)
        return sorted(by_bb.values(), key=lambda stake: (stake[1], stake[0]))

    def rakeback_cents(self, bb_cents: int) -> int:
        row = self.conn.execute(
            "SELECT amount_cents FROM rakeback_by_stake WHERE bb_cents=?",
            (int(bb_cents),),
        ).fetchone()
        return int(row[0]) if row else 0

    def set_rakeback_cents(self, sb_cents: int, bb_cents: int, amount_cents: int):
        amount_cents = max(0, int(amount_cents))
        with self.conn:
            self.conn.execute(
                """INSERT INTO rakeback_by_stake(bb_cents, sb_cents, amount_cents)
                   VALUES(?,?,?)
                   ON CONFLICT(bb_cents) DO UPDATE SET
                       sb_cents=excluded.sb_cents,
                       amount_cents=excluded.amount_cents""",
                (int(bb_cents), int(sb_cents), amount_cents),
            )

    def _rakeback_totals(self, filters: dict | None = None) -> tuple[int, float]:
        """Return cash rakeback and its BB equivalent for the selected stake(s)."""
        filters = filters or {}
        selected_bb = filters.get("bb_cents")
        if selected_bb is None:
            row = self.conn.execute(
                """SELECT
                       COALESCE(SUM(amount_cents), 0) amount_cents,
                       COALESCE(SUM(CASE WHEN bb_cents > 0
                           THEN CAST(amount_cents AS REAL) / bb_cents ELSE 0 END), 0) amount_bb
                   FROM rakeback_by_stake"""
            ).fetchone()
        else:
            row = self.conn.execute(
                """SELECT
                       COALESCE(SUM(amount_cents), 0) amount_cents,
                       COALESCE(SUM(CASE WHEN bb_cents > 0
                           THEN CAST(amount_cents AS REAL) / bb_cents ELSE 0 END), 0) amount_bb
                   FROM rakeback_by_stake WHERE bb_cents=?""",
                (int(selected_bb),),
            ).fetchone()
        return int(row["amount_cents"] or 0), float(row["amount_bb"] or 0)

    def overview(self, filters: dict | None = None) -> dict:
        where, params = self._where(filters)
        r = self.conn.execute(
            f"""SELECT COUNT(*) hands,
                COALESCE(SUM(hero_net_cents),0) net_cents,
                COALESCE(SUM(hero_allin_adj_cents),0) allin_adj_cents,
                COALESCE(SUM(hero_splash_won_cents),0) splash_won_cents,
                COALESCE(SUM(rake_cents),0) rake_cents,
                COALESCE(SUM(hero_vpip),0) vpip_n,
                COALESCE(SUM(hero_pfr),0) pfr_n,
                COALESCE(SUM(hero_three_bet),0) three_bet_n,
                COALESCE(SUM(hero_three_bet_opp),0) three_bet_opp_n,
                COALESCE(SUM(hero_saw_flop),0) saw_flop_n,
                COALESCE(SUM(CASE WHEN hero_saw_flop = 1 AND (hero_collected_cents > 0 OR hero_splash_won_cents > 0) THEN 1 ELSE 0 END),0) wwsf_wins,
                COALESCE(SUM(hero_wtsd),0) wtsd_n,
                COALESCE(SUM(hero_won_sd),0) won_sd_n,
                COALESCE(SUM(CASE WHEN splash_cents > 0 THEN 1 ELSE 0 END),0) splash_hands,
                COALESCE(SUM(CASE WHEN run_count > 1 THEN 1 ELSE 0 END),0) multi_run_hands,
                COALESCE(SUM(hero_allin_adjusted),0) allin_adjusted_hands,
                COALESCE(SUM(CASE WHEN bb_cents > 0 THEN CAST(hero_net_cents AS REAL)/bb_cents ELSE 0 END),0) net_bb,
                COALESCE(SUM(CASE WHEN bb_cents > 0 THEN hero_allin_adj_cents/bb_cents ELSE 0 END),0) allin_adj_bb
              FROM hands{where}""", params
        ).fetchone()
        hands = r["hands"] or 0
        wtsd = r["wtsd_n"] or 0
        saw_flop = r["saw_flop_n"] or 0
        three_bet_opp = r["three_bet_opp_n"] or 0
        net_cents = int(r["net_cents"] or 0)
        net_bb = float(r["net_bb"] or 0)
        rakeback_cents, rakeback_bb = self._rakeback_totals(filters)
        post_rb_net_cents = net_cents + rakeback_cents
        post_rb_net_bb = net_bb + rakeback_bb
        return {
            "hands": hands,
            "net_cents": net_cents,
            "rakeback_cents": rakeback_cents,
            "net_post_rb_cents": post_rb_net_cents,
            "net_bb_post_rb": post_rb_net_bb,
            "bb100_post_rb": (post_rb_net_bb * 100 / hands) if hands else 0.0,
            "allin_adj_cents": float(r["allin_adj_cents"] or 0),
            "splash_won_cents": r["splash_won_cents"] or 0,
            "rake_cents": r["rake_cents"] or 0,
            "net_bb": net_bb,
            "bb100": (net_bb * 100 / hands) if hands else 0.0,
            "allin_adj_bb": float(r["allin_adj_bb"] or 0),
            "allin_adj_bb100": (float(r["allin_adj_bb"] or 0) * 100 / hands) if hands else 0.0,
            "allin_adjusted_hands": r["allin_adjusted_hands"] or 0,
            "vpip": (r["vpip_n"] * 100 / hands) if hands else 0.0,
            "pfr": (r["pfr_n"] * 100 / hands) if hands else 0.0,
            "three_bet": (r["three_bet_n"] * 100 / three_bet_opp) if three_bet_opp else 0.0,
            "wwsf": (r["wwsf_wins"] * 100 / saw_flop) if saw_flop else 0.0,
            "wtsd": (r["wtsd_n"] * 100 / saw_flop) if saw_flop else 0.0,
            "wsd": (r["won_sd_n"] * 100 / wtsd) if wtsd else 0.0,
            "splash_hands": r["splash_hands"] or 0,
            "multi_run_hands": r["multi_run_hands"] or 0,
        }
    def profit_points(self, filters: dict | None = None) -> list[sqlite3.Row]:
        where, params = self._where(filters)
        return self.conn.execute(
            f"SELECT hand_id, started_at, hero_net_cents, hero_allin_adj_cents, hero_wtsd FROM hands{where} ORDER BY started_at, hand_id", params
        ).fetchall()
    def distinct_stakes(self) -> list[tuple[int, int]]:
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT DISTINCT sb_cents, bb_cents FROM hands ORDER BY bb_cents, sb_cents"
        ).fetchall()]
    def hand_count(self, filters: dict | None = None) -> int:
        """Count all matching hands independently of the display limit."""
        where, params = self._where(filters)
        return self.conn.execute(
            f"SELECT COUNT(*) FROM hands{where}", params,
        ).fetchone()[0]

    def hands(self, filters: dict | None = None, limit: int = 1000) -> list[sqlite3.Row]:
        """Return the latest matching hands; a negative limit returns all."""
        where, params = self._where(filters)
        return self._query_hands(where, params, limit)

    def _query_hands(self, where: str, params: Iterable, limit: int) -> list[sqlite3.Row]:
        """Fetch the shared hand-table columns after applying a SQL condition."""
        return self.conn.execute(
            f"""SELECT hand_id, started_at, sb_cents, bb_cents, hero_position, hero_cards,
                board1, board2, board3, run_count, splash_type, splash_cents,
                total_pot_cents, rake_cents, hero_contributed_cents,
                hero_returned_cents, hero_splash_won_cents, hero_net_cents,
                hero_allin_adj_cents, hero_allin_equity, hero_allin_adjusted, hero_allin_estimated
                FROM hands{where} ORDER BY started_at DESC, hand_id DESC LIMIT ?""",
            [*params, limit],
        ).fetchall()

    def hands_for_group(
        self,
        group_by: str,
        group_key: str | tuple[int, int] | None,
        filters: dict | None = None,
        limit: int = -1,
    ) -> list[sqlite3.Row]:
        """Return the latest filtered hands in a group; None selects the total.

        Use the same position normalization and starting-hand categories as
        grouped_results. Add the group condition to the active filters rather
        than replacing a potentially narrower existing filter. A negative
        limit returns all matching hands.
        """
        if group_by not in {"position", "stakes", "starting_hands"}:
            raise ValueError(f"Unsupported grouping: {group_by}")
        if group_key is None:
            return self.hands(filters, limit=limit)

        where, params = self._where(filters)
        if group_by == "stakes":
            if not isinstance(group_key, (tuple, list)) or len(group_key) != 2:
                raise ValueError("A stakes group requires its small and big blind")
            condition = "sb_cents = ? AND bb_cents = ?"
            params.extend(group_key)
        elif group_by == "starting_hands":
            condition = "starting_hand_label(hero_cards) = ?"
            params.append(group_key)
        else:
            condition = "COALESCE(NULLIF(TRIM(hero_position), ''), 'Unknown') = ?"
            params.append(group_key)
        where += (" AND " if where else " WHERE ") + condition
        return self._query_hands(where, params, limit)

    def hands_by_ids(
        self, hand_ids: Iterable[str], limit: int = -1,
    ) -> list[sqlite3.Row]:
        """Return the latest stored hands in an ID set; a negative limit returns all.

        Select by date across the entire set before loading full hand rows.
        This keeps a large session selection from loading every hand when the
        user only wants to display its most recent 1,000.
        """
        if limit == 0:
            return []
        ids = list(dict.fromkeys(str(hand_id) for hand_id in hand_ids if hand_id))
        if limit > 0 and len(ids) > limit:
            def candidates():
                for index in range(0, len(ids), 800):
                    chunk = ids[index:index + 800]
                    marks = ",".join("?" for _ in chunk)
                    yield from self.conn.execute(
                        f"""SELECT hand_id, started_at FROM hands
                            WHERE hand_id IN ({marks})
                            ORDER BY started_at DESC, hand_id DESC LIMIT ?""",
                        [*chunk, limit],
                    )

            ids = [
                row["hand_id"] for row in nlargest(
                    limit, candidates(),
                    key=lambda row: (row["started_at"], row["hand_id"]),
                )
            ]
        if not ids:
            return []

        rows: list[sqlite3.Row] = []
        for index in range(0, len(ids), 800):
            chunk = ids[index:index + 800]
            marks = ",".join("?" for _ in chunk)
            rows.extend(
                self._query_hands(f" WHERE hand_id IN ({marks})", chunk, -1)
            )
        return sorted(
            rows,
            key=lambda row: (row["started_at"], row["hand_id"]),
            reverse=True,
        )

    def raw_hand(self, hand_id: str) -> str:
        r = self.conn.execute("SELECT raw_text FROM hands WHERE hand_id=?", (hand_id,)).fetchone()
        return r[0] if r else ""

    def replay_hand(self, hand_id: str) -> Hand | None:
        """Reparse one stored hand with the hero name used at import time."""
        row = self.conn.execute(
            "SELECT hero_name, raw_text FROM hands WHERE hand_id=?",
            (hand_id,),
        ).fetchone()
        if row is None:
            return None
        return parse_hand(
            row["raw_text"],
            hero_name=row["hero_name"] or "Hero",
        )

    def delete_hands(self, hand_ids: Iterable[str]) -> int:
        """Delete hands and all dependent rows. Returns the number of hands removed."""
        ids = list(dict.fromkeys(str(hand_id) for hand_id in hand_ids if hand_id))
        if not ids:
            return 0
        deleted = 0
        with self.conn:
            # Keep comfortably under SQLite's parameter limit. Foreign keys on
            # seats/actions/player_results use ON DELETE CASCADE.
            for i in range(0, len(ids), 800):
                chunk = ids[i:i + 800]
                marks = ",".join("?" for _ in chunk)
                existing = self.conn.execute(
                    f"SELECT COUNT(*) FROM hands WHERE hand_id IN ({marks})", chunk
                ).fetchone()[0]
                self.conn.execute(f"DELETE FROM hands WHERE hand_id IN ({marks})", chunk)
                deleted += existing
        return deleted
    def sessions(self, gap_minutes: int = 30, filters: dict | None = None) -> list[dict]:
        where, params = self._where(filters)
        rows = self.conn.execute(
            f"SELECT hand_id, started_at, hero_net_cents, bb_cents FROM hands{where} ORDER BY started_at, hand_id", params
        ).fetchall()
        from datetime import datetime, timedelta
        out: list[dict] = []
        current = None
        gap = timedelta(minutes=gap_minutes)
        for r in rows:
            dt = datetime.fromisoformat(r["started_at"])
            if current is None or dt - current["end"] > gap:
                current = {
                    "start": dt, "end": dt, "hands": 0, "net_cents": 0,
                    "net_bb": 0.0, "hand_ids": [],
                }
                out.append(current)
            current["end"] = dt
            current["hands"] += 1
            current["hand_ids"].append(r["hand_id"])
            current["net_cents"] += r["hero_net_cents"]
            if r["bb_cents"]:
                current["net_bb"] += r["hero_net_cents"] / r["bb_cents"]
        return list(reversed(out))
    def positional(self, filters: dict | None = None) -> list[sqlite3.Row]:
        where, params = self._where(filters)
        return self.conn.execute(
            f"""SELECT hero_position position, COUNT(*) hands,
                SUM(hero_net_cents) net_cents,
                SUM(hero_vpip) vpip_n, SUM(hero_pfr) pfr_n,
                SUM(CASE WHEN bb_cents>0 THEN CAST(hero_net_cents AS REAL)/bb_cents ELSE 0 END) net_bb
              FROM hands{where}
              GROUP BY hero_position ORDER BY hands DESC""", params
        ).fetchall()

    def grouped_results(
        self, group_by: str = "position", filters: dict | None = None,
    ) -> tuple[list[dict], dict]:
        """Return grouped results and a total for exactly the filtered hands.

        Aggregate raw counts before calculating percentages. In particular,
        mixed-stakes BB results sum each hand's winnings divided by its own
        big blind; totals never average the displayed group percentages.
        """
        group_columns = {
            "position": "COALESCE(NULLIF(TRIM(hero_position), ''), 'Unknown')",
            "stakes": "sb_cents, bb_cents",
            "starting_hands": "hero_cards",
        }
        if group_by not in group_columns:
            raise ValueError(f"Unsupported grouping: {group_by}")
        aggregates = {
            "hands": "COUNT(*)",
            "net_cents": "SUM(hero_net_cents)",
            "allin_adj_cents": "SUM(hero_allin_adj_cents)",
            "splash_won_cents": "SUM(hero_splash_won_cents)",
            "net_bb": "SUM(CASE WHEN bb_cents > 0 THEN CAST(hero_net_cents AS REAL) / bb_cents ELSE 0 END)",
            "allin_adj_bb": "SUM(CASE WHEN bb_cents > 0 THEN CAST(hero_allin_adj_cents AS REAL) / bb_cents ELSE 0 END)",
            "vpip_n": "SUM(hero_vpip)",
            "pfr_n": "SUM(hero_pfr)",
            "three_bet_n": "SUM(hero_three_bet)",
            "three_bet_opp_n": "SUM(hero_three_bet_opp)",
            "saw_flop_n": "SUM(hero_saw_flop)",
            "wwsf_wins": "SUM(CASE WHEN hero_saw_flop = 1 AND (hero_collected_cents > 0 OR hero_splash_won_cents > 0) THEN 1 ELSE 0 END)",
            "wtsd_n": "SUM(hero_wtsd)",
            "won_sd_n": "SUM(hero_won_sd)",
        }
        group_sql = group_columns[group_by]
        selection = group_sql if group_by == "stakes" else f"{group_sql} AS group_value"
        metrics_sql = ", ".join(
            f"COALESCE({expression}, 0) AS {key}"
            for key, expression in aggregates.items()
        )
        where, params = self._where(filters)
        rows = self.conn.execute(
            f"SELECT {selection}, {metrics_sql} FROM hands{where} "
            f"GROUP BY {group_sql} ORDER BY {group_sql}", params,
        )
        groups = {}
        total = {key: 0 for key in aggregates}
        for row in rows:
            if group_by == "stakes":
                key = (row["sb_cents"], row["bb_cents"])
                identity = {"sb_cents": key[0], "bb_cents": key[1]}
            elif group_by == "starting_hands":
                key = starting_hand_label(row["group_value"])
                identity = {"group": key, "hand_type": starting_hand_type(key)}
            else:
                key = row["group_value"]
                identity = {"group": key}
            if key not in groups:
                groups[key] = {**identity, **{name: 0 for name in aggregates}}
            for name in aggregates:
                groups[key][name] += row[name]
                total[name] += row[name]

        def add_rates(result: dict):
            for name, numerator, denominator in (
                ("bb100", "net_bb", "hands"),
                ("allin_adj_bb100", "allin_adj_bb", "hands"),
                ("vpip", "vpip_n", "hands"),
                ("pfr", "pfr_n", "hands"),
                ("three_bet", "three_bet_n", "three_bet_opp_n"),
                ("wwsf", "wwsf_wins", "saw_flop_n"),
                ("wtsd", "wtsd_n", "saw_flop_n"),
                ("wsd", "won_sd_n", "wtsd_n"),
            ):
                result[name] = (
                    result[numerator] * 100 / result[denominator]
                    if result[denominator] else 0.0
                )
            result["share_pct"] = (
                result["hands"] * 100 / total["hands"] if total["hands"] else 0.0
            )

        for result in groups.values():
            add_rates(result)
        add_rates(total)
        return list(groups.values()), total
