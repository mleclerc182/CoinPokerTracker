from cointracker.database import TrackerDB
from cointracker.parser import parse_hand


def _hand():
    return parse_hand("""CoinPoker Hand #123456789: NLH (₮0.01/₮0.02) 2026/08/27 07:00:00 EDT
Table '200588' 6-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Kd]
Hero: raises ₮0.05 to ₮0.06
Villain: folds
Hero: RETURN ₮0.04
*** SHOWDOWN ***
Hero collected ₮0.04 from pot
*** SUMMARY ***
Total pot ₮0.04 | Rake ₮0
Hand was run once
Board [  ]
Game ended: 2026/08/27 07:00:10 EDT
""")


def test_delete_hand_cascades(tmp_path):
    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        added, duplicates = db.import_hands([_hand()])
        assert (added, duplicates) == (1, 0)
        hand_id = "123456789"
        assert db.raw_hand(hand_id)
        assert db.conn.execute("SELECT COUNT(*) FROM seats WHERE hand_id=?", (hand_id,)).fetchone()[0] > 0
        assert db.conn.execute("SELECT COUNT(*) FROM actions WHERE hand_id=?", (hand_id,)).fetchone()[0] > 0
        assert db.conn.execute("SELECT COUNT(*) FROM player_results WHERE hand_id=?", (hand_id,)).fetchone()[0] > 0

        assert db.delete_hands([hand_id]) == 1
        assert db.raw_hand(hand_id) == ""
        assert db.conn.execute("SELECT COUNT(*) FROM seats WHERE hand_id=?", (hand_id,)).fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM actions WHERE hand_id=?", (hand_id,)).fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM player_results WHERE hand_id=?", (hand_id,)).fetchone()[0] == 0
        assert db.delete_hands([hand_id, "does-not-exist"]) == 0
    finally:
        db.close()


def test_calculation_migration_reparses_existing_splash_hands(tmp_path):
    path = tmp_path / "tracker.sqlite3"
    splash = parse_hand("""CoinPoker Hand #987654321: NLH (₮0.01/₮0.02) 2026/08/26 08:22:18 EDT
Table '200588' 3-max Seat #1 is the button
Seat 1: A (₮2 in chips)
Seat 2: Hero (₮2 in chips)
Seat 3: B (₮2 in chips)
SPLASH dropped ₮0.40
Hero: posts small blind ₮0.01
B: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Kd]
A: folds
Hero: raises ₮0.05 to ₮0.06
B: folds
Hero: RETURN ₮0.04
*** SHOWDOWN ***
Hero collected ₮0.04 from pot
*** SUMMARY ***
Total pot ₮0.44 | Rake ₮0
Hand was run once
Board [  ]
Game ended: 2026/08/26 08:22:30 EDT
""")

    db = TrackerDB(path)
    db.import_hands([splash])
    assert db.overview()["net_cents"] == 42
    # Simulate a pre-fix stored calculation while retaining the raw HH.
    with db.conn:
        db.conn.execute(
            "UPDATE hands SET hero_splash_won_cents=0, hero_net_cents=2 WHERE hand_id=?",
            (splash.hand_id,),
        )
        db.conn.execute(
            "INSERT INTO tracker_meta(key,value) VALUES('calculation_version','2') "
            "ON CONFLICT(key) DO UPDATE SET value='2'"
        )
    db.close()

    upgraded = TrackerDB(path)
    try:
        assert upgraded.recalculated_count == 1
        row = upgraded.conn.execute(
            "SELECT hero_splash_won_cents, hero_net_cents FROM hands WHERE hand_id=?",
            (splash.hand_id,),
        ).fetchone()
        assert row["hero_splash_won_cents"] == 40
        assert row["hero_net_cents"] == 42
    finally:
        upgraded.close()


def test_overview_exposes_allin_adjusted_bb(monkeypatch, tmp_path):
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda hands, board: [0.75, 0.25])
    hand = parse_hand("""CoinPoker Hand #5550001: NLH (₮0.01/₮0.02) 2026/08/27 08:00:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Ad]
Hero: ALLIN ₮1.99
Villain: ALLIN ₮1.98
*** FLOP *** [2c 7d 9h]
*** TURN *** [2c 7d 9h] [Js]
*** RIVER *** [2c 7d 9h Js] [Kc]
*** SHOWDOWN ***
Villain: shows [Ks Kd] (Three Of A Kind)
Villain collected ₮4 from pot
Hero: shows [As Ad] (One Pair)
*** SUMMARY ***
Total pot ₮4 | Rake ₮0
Hand was run once
Board [ 2c 7d 9h Js Kc ]
Game ended: 2026/08/27 08:00:30 EDT
""")
    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        assert db.import_hands([hand]) == (1, 0)
        o = db.overview()
        # 4.00 * .75 - 2.00 = +1.00 adjusted = 50 BB at a .02 BB.
        assert o["allin_adj_cents"] == 100.0
        assert o["allin_adj_bb"] == 50.0
        assert o["allin_adj_bb100"] == 5000.0
        assert o["allin_adjusted_hands"] == 1
        row = db.hands()[0]
        assert row["hero_allin_adjusted"] == 1
        assert row["hero_allin_equity"] == 0.75
        assert row["hero_allin_adj_cents"] == 100.0
    finally:
        db.close()


def _hand_at(hand_id: str, started: str, ended: str):
    return parse_hand(f"""CoinPoker Hand #{hand_id}: NLH (₮0.01/₮0.02) {started} EDT
Table '200588' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Kd]
Hero: raises ₮0.05 to ₮0.06
Villain: folds
Hero: RETURN ₮0.04
*** SHOWDOWN ***
Hero collected ₮0.04 from pot
*** SUMMARY ***
Total pot ₮0.04 | Rake ₮0
Hand was run once
Board [  ]
Game ended: {ended} EDT
""")


def test_sessions_expose_all_hand_ids_for_session_delete(tmp_path):
    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        hands = [
            _hand_at("910001", "2026/08/27 07:00:00", "2026/08/27 07:00:10"),
            _hand_at("910002", "2026/08/27 07:10:00", "2026/08/27 07:10:10"),
            _hand_at("910003", "2026/08/27 08:00:01", "2026/08/27 08:00:11"),
        ]
        assert db.import_hands(hands) == (3, 0)

        sessions = db.sessions(30)
        assert len(sessions) == 2
        # Sessions are returned newest first.
        assert sessions[0]["hand_ids"] == ["910003"]
        assert sessions[1]["hand_ids"] == ["910001", "910002"]

        session_hands = db.hands_by_ids(sessions[1]["hand_ids"])
        assert [row["hand_id"] for row in session_hands] == [
            "910002",
            "910001",
        ]

        deleted = db.delete_hands(sessions[1]["hand_ids"])
        assert deleted == 2
        assert db.conn.execute("SELECT COUNT(*) FROM hands").fetchone()[0] == 1
        for table in ("seats", "actions", "player_results"):
            assert db.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE hand_id IN ('910001','910002')"
            ).fetchone()[0] == 0
    finally:
        db.close()


def test_contributed_bb_filter_uses_net_chips_put_in_the_pot(tmp_path):
    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        hands = [
            _hand_at(
                "920001",
                "2026/08/27 07:00:00",
                "2026/08/27 07:00:10",
            ),
            _hand_at(
                "920002",
                "2026/08/27 07:10:00",
                "2026/08/27 07:10:10",
            ),
        ]
        assert db.import_hands(hands) == (2, 0)

        # Both hands use a 2-cent BB. The first contributes 6 cents and
        # receives 4 cents back (1 BB net); the second contributes 20 and
        # receives 4 back (8 BB net).
        with db.conn:
            db.conn.execute(
                "UPDATE hands SET hero_contributed_cents=20, "
                "hero_returned_cents=4 WHERE hand_id='920002'"
            )

        rows = db.hands()
        assert rows[0]["hero_contributed_cents"] == 20
        assert rows[0]["hero_returned_cents"] == 4

        minimum = db.hands({"contributed_bb_min": 2})
        assert [row["hand_id"] for row in minimum] == ["920002"]

        maximum = db.hands({"contributed_bb_max": 1})
        assert [row["hand_id"] for row in maximum] == ["920001"]

        exact_range = db.hands(
            {
                "contributed_bb_min": 8,
                "contributed_bb_max": 8,
            }
        )
        assert [row["hand_id"] for row in exact_range] == ["920002"]
        assert db.overview({"contributed_bb_min": 2})["hands"] == 1
        assert db.sessions(30, {"contributed_bb_max": 1})[0][
            "hand_ids"
        ] == ["920001"]
    finally:
        db.close()


def test_profit_points_exposes_showdown_flag_for_graph(tmp_path):
    showdown = parse_hand("""CoinPoker Hand #940001: NLH (₮0.01/₮0.02) 2026/08/27 09:00:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Kd]
Hero: calls ₮0.01
Villain: checks
*** FLOP *** [Ac 7d 2h]
Hero: checks
Villain: checks
*** TURN *** [Ac 7d 2h] [3s]
Hero: checks
Villain: checks
*** RIVER *** [Ac 7d 2h 3s] [4c]
Hero: checks
Villain: checks
*** SHOWDOWN ***
Hero: shows [As Kd] (One Pair)
Hero collected ₮0.04 from pot
Villain: shows [Qs Jd] (High Card)
*** SUMMARY ***
Total pot ₮0.04 | Rake ₮0
Hand was run once
Board [ Ac 7d 2h 3s 4c ]
Game ended: 2026/08/27 09:00:30 EDT
""")
    nonshowdown = parse_hand("""CoinPoker Hand #940002: NLH (₮0.01/₮0.02) 2026/08/27 09:01:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [7c 2d]
Hero: folds
Villain: RETURN ₮0.01
*** SHOWDOWN ***
Villain collected ₮0.02 from pot
*** SUMMARY ***
Total pot ₮0.02 | Rake ₮0
Hand was run once
Board [  ]
Game ended: 2026/08/27 09:01:10 EDT
""")

    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        assert db.import_hands([showdown, nonshowdown]) == (2, 0)
        rows = db.profit_points()
        assert [r["hand_id"] for r in rows] == ["940001", "940002"]
        assert rows[0]["hero_wtsd"] == 1
        assert rows[1]["hero_wtsd"] == 0
    finally:
        db.close()


def test_overview_wwsf_counts_pot_wins_after_seeing_flop(tmp_path):
    won = parse_hand("""CoinPoker Hand #950001: NLH (₮0.01/₮0.02) 2026/08/27 10:00:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Kd]
Hero: calls ₮0.01
Villain: checks
*** FLOP *** [Ac 7d 2h]
Villain: checks
Hero: bets ₮0.02
Villain: folds
Hero: RETURN ₮0.02
*** SHOWDOWN ***
Hero collected ₮0.04 from pot
*** SUMMARY ***
Total pot ₮0.04 | Rake ₮0
Hand was run once
Board [ Ac 7d 2h ]
Game ended: 2026/08/27 10:00:20 EDT
""")
    lost = parse_hand("""CoinPoker Hand #950002: NLH (₮0.01/₮0.02) 2026/08/27 10:01:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [Qs Jd]
Hero: calls ₮0.01
Villain: checks
*** FLOP *** [Ac 7d 2h]
Villain: bets ₮0.02
Hero: folds
Villain: RETURN ₮0.02
*** SHOWDOWN ***
Villain collected ₮0.04 from pot
*** SUMMARY ***
Total pot ₮0.04 | Rake ₮0
Hand was run once
Board [ Ac 7d 2h ]
Game ended: 2026/08/27 10:01:20 EDT
""")
    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        assert db.import_hands([won, lost]) == (2, 0)
        o = db.overview()
        assert o["wtsd"] == 0.0
        assert o["wwsf"] == 50.0
    finally:
        db.close()
