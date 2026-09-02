from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Iterator, Optional

from .equity import exact_equities, estimate_equities_with_unknown

MONEY_SCALE = Decimal("100")

def money_to_cents(value: str | Decimal | None) -> int:
    if value is None or value == "":
        return 0
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int((d * MONEY_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_money(cents: int) -> Decimal:
    return Decimal(cents) / MONEY_SCALE

HEADER_RE = re.compile(
    r"^CoinPoker Hand #(?P<id>\d+):\s+(?P<game>[^\s]+)\s+"
    r"\(₮(?P<sb>[\d.]+)/₮(?P<bb>[\d.]+)(?:/₮(?P<ante>[\d.]+))?\)\s+"
    r"(?P<date>\d{4}/\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<tz>\S+)\s*$"
)
TABLE_RE = re.compile(r"^Table '([^']+)'\s+(\d+)-max Seat #(\d+) is the button$")
SEAT_RE = re.compile(r"^Seat (\d+):\s+(.+?)\s+\(₮([\d.]+) in chips\)$")
DEALT_RE = re.compile(r"^Dealt to (.+?)(?: \[([^\]]+)\])?$")
SPLASH_RE = re.compile(r"^(MEGA SPLASH|SPLASH) dropped ₮([\d.]+)$")
POST_RE = re.compile(r"^(.+?): posts (ante|small blind|big blind|auto big blind) ₮([\d.]+)$")
STRADDLE_RE = re.compile(r"^(.+?): STRADDLE ₮([\d.]+)$")
RAISE_RE = re.compile(r"^(.+?): raises ₮([\d.]+) to ₮([\d.]+)$")
CALL_RE = re.compile(r"^(.+?): calls ₮([\d.]+)$")
BET_RE = re.compile(r"^(.+?): bets ₮([\d.]+)$")
ALLIN_RE = re.compile(r"^(.+?): ALLIN ₮([\d.]+)$")
RETURN_RE = re.compile(r"^(.+?): RETURN ₮([\d.]+)$")
FOLD_RE = re.compile(r"^(.+?): folds$")
CHECK_RE = re.compile(r"^(.+?): checks$")
SHOW_RE = re.compile(r"^(.+?): shows \[([^\]]+)\](?: \(([^)]+)\))?$")
MUCK_RE = re.compile(r"^(.+?): mucks hand$")
COLLECT_RE = re.compile(r"^(.+?) collected ₮([\d.]+) from pot$")
TOTAL_RE = re.compile(r"^Total pot ₮([\d.]+) \| Rake ₮([\d.]+)(?: \| Splash Fee ₮([\d.]+))?$")
RUN_RE = re.compile(r"^Hand was run (once|two times|three times)$")
BOARD_RE = re.compile(r"^(?:(FIRST|SECOND|THIRD) )?Board \[\s*([^\]]*?)\s*\]$")
END_RE = re.compile(r"^Game ended: (\d{4}/\d{2}/\d{2}) (\d{2}:\d{2}:\d{2}) (\S+)$")
STREET_RE = re.compile(r"^\*\*\* (?:(FIRST|SECOND|THIRD) )?(FLOP|TURN|RIVER) \*\*\*")
SHOWDOWN_MARKER_RE = re.compile(r"^\*\*\* (?:(FIRST|SECOND|THIRD) )?SHOWDOWN \*\*\*$")
RUN_MAP = {"once": 1, "two times": 2, "three times": 3}
RUN_WORD = {None: 1, "FIRST": 1, "SECOND": 2, "THIRD": 3}


@dataclass(slots=True)
class Seat:
    seat_no: int
    player: str
    stack_cents: int
    position: str = ""


@dataclass(slots=True)
class Action:
    seq: int
    street: str
    run_index: int
    player: str
    action: str
    amount_cents: int = 0
    to_cents: int = 0
    raw: str = ""
    aggressive: bool = False
    raise_number: int = 0

@dataclass(slots=True)
class PlayerResult:
    player: str
    seat_no: int = 0
    stack_cents: int = 0
    position: str = ""
    contributed_cents: int = 0
    returned_cents: int = 0
    collected_cents: int = 0
    splash_won_cents: int = 0
    net_cents: int = 0
    allin_adj_cents: float = 0.0
    allin_equity: float | None = None
    allin_adjusted: bool = False
    allin_estimated: bool = False
    vpip: bool = False
    pfr: bool = False
    three_bet: bool = False
    three_bet_opp: bool = False
    saw_flop: bool = False
    went_to_showdown: bool = False
    won_showdown: bool = False
    folded_preflop: bool = False

@dataclass(slots=True)
class Hand:
    hand_id: str
    game: str
    sb_cents: int
    bb_cents: int
    started_at: datetime
    timezone: str
    table_name: str = ""
    max_seats: int = 0
    button_seat: int = 0
    ended_at: Optional[datetime] = None
    seats: list[Seat] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    hero_name: str = "Hero"
    hero_seat: int = 0
    hero_position: str = ""
    hero_cards: str = ""
    boards: list[str] = field(default_factory=list)
    run_count: int = 1
    splash_type: str = ""
    splash_cents: int = 0
    total_pot_cents: int = 0
    rake_cents: int = 0
    splash_fee_cents: int = 0
    player_results: dict[str, PlayerResult] = field(default_factory=dict)
    raw_text: str = ""
    first_allin_street: str = ""
    first_allin_board: str = ""
    @property
    def hero_result(self) -> PlayerResult:
        return self.player_results.get(self.hero_name, PlayerResult(self.hero_name))

    @property
    def is_splash(self) -> bool:
        return self.splash_cents > 0

    @property
    def is_multi_run(self) -> bool:
        return self.run_count > 1


CARD_RANK = {r: i for i, r in enumerate("23456789TJQKA", start=2)}
def _rank_five(cards: tuple[str, ...]) -> tuple[int, ...]:
    """Return a comparable Hold'em five-card rank; larger tuples are better."""
    values = sorted((CARD_RANK[c[0]] for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    counts = Counter(values)
    unique = sorted(set(values), reverse=True)
    if 14 in unique:
        unique.append(1)  # wheel support
    straight_high = 0
    for i in range(len(unique) - 4):
        seq = unique[i:i + 5]
        if seq[0] - seq[4] == 4:
            straight_high = seq[0]
            break
    flush = len(set(suits)) == 1

    if straight_high and flush:
        return (8, straight_high)
    quads = sorted((v for v, n in counts.items() if n == 4), reverse=True)
    if quads:
        q = quads[0]
        kicker = max(v for v in values if v != q)
        return (7, q, kicker)
    trips = sorted((v for v, n in counts.items() if n == 3), reverse=True)
    pairs_or_better = sorted((v for v, n in counts.items() if n >= 2), reverse=True)
    if trips:
        t = trips[0]
        pair_choices = [v for v in pairs_or_better if v != t]
        if pair_choices:
            return (6, t, pair_choices[0])
    if flush:
        return (5, *values)
    if straight_high:
        return (4, straight_high)
    if trips:
        t = trips[0]
        kickers = sorted((v for v in values if v != t), reverse=True)[:2]
        return (3, t, *kickers)
    pairs = sorted((v for v, n in counts.items() if n == 2), reverse=True)
    if len(pairs) >= 2:
        hi, lo = pairs[:2]
        kicker = max(v for v in values if v not in (hi, lo))
        return (2, hi, lo, kicker)
    if len(pairs) == 1:
        pair = pairs[0]
        kickers = sorted((v for v in values if v != pair), reverse=True)[:3]
        return (1, pair, *kickers)
    return (0, *values)

def _holdem_rank(hole_cards: str, board: str) -> tuple[int, ...] | None:
    cards = hole_cards.split() + board.split()
    if len(cards) != 7 or any(len(c) != 2 or c[0] not in CARD_RANK for c in cards):
        return None
    return max(_rank_five(combo) for combo in combinations(cards, 5))

def _odd_chip_order(hand: Hand, players: list[str]) -> list[str]:
    """Poker odd-chip order: first occupied seat clockwise after the button."""
    by_player = {s.player: s.seat_no for s in hand.seats}
    occupied = sorted(s.seat_no for s in hand.seats)
    if not occupied or hand.button_seat not in occupied:
        return sorted(players)
    bi = occupied.index(hand.button_seat)
    clockwise = occupied[bi + 1:] + occupied[:bi + 1]
    order_index = {seat: i for i, seat in enumerate(clockwise)}
    return sorted(players, key=lambda p: (order_index.get(by_player.get(p, -1), 999), p))

def _split_cents(amount: int, winners: list[str], hand: Hand) -> dict[str, int]:
    if amount <= 0 or not winners:
        return {}
    ordered = _odd_chip_order(hand, winners)
    base, rem = divmod(amount, len(ordered))
    return {p: base + (1 if i < rem else 0) for i, p in enumerate(ordered)}

def _splash_awards(
    hand: Hand,
    results: dict[str, PlayerResult],
    shown_cards: dict[str, str],
    folded_players: set[str],
    mucked_players: set[str],
) -> dict[str, int]:
    """Allocate CoinPoker Splash/Mega Splash money to main-pot winner(s).
    CoinPoker includes the promotional drop in ``Total pot`` but does not include
    that award in the normal ``collected`` lines. The drop belongs to the main pot,
    so side-pot-only winners receive none. For RIT/RIT3 the drop is divided across
    runouts, then ties on a runout split that runout's share.
    """
    if hand.splash_cents <= 0:
        return {}
    active = [
        p for p, r in results.items()
        if p not in folded_players
        and (r.contributed_cents - r.returned_cents > 0 or r.collected_cents > 0)
    ]
    if not active:
        return {}
    if len(active) == 1:
        return {active[0]: hand.splash_cents}
    # Split the promotional pot between runouts first. Earlier runouts receive an
    # odd cent if the splash amount is not evenly divisible.
    run_count = max(1, hand.run_count)
    run_base, run_rem = divmod(hand.splash_cents, run_count)
    awards: dict[str, int] = {}

    for run_idx in range(1, run_count + 1):
        run_amount = run_base + (1 if run_idx <= run_rem else 0)
        board = hand.boards[run_idx - 1] if run_idx - 1 < len(hand.boards) else ""
        ranks: dict[str, tuple[int, ...]] = {}
        unresolved: list[str] = []
        for player in active:
            if player in mucked_players:
                continue
            cards = shown_cards.get(player, "")
            rank = _holdem_rank(cards, board) if hand.game == "NLH" else None
            if rank is not None:
                ranks[player] = rank
            else:
                unresolved.append(player)
        winners: list[str] = []
        if ranks and not unresolved:
            best = max(ranks.values())
            winners = [p for p, rank in ranks.items() if rank == best]
        else:
            # Fallback for an unusual/incomplete HH: CoinPoker emits main-pot
            # collections before side-pot collections within each showdown.
            collectors = [
                a.player for a in hand.actions
                if a.action == "COLLECT" and a.run_index == run_idx
            ]
            if collectors:
                winners = [collectors[0]]
        for player, cents in _split_cents(run_amount, winners, hand).items():
            awards[player] = awards.get(player, 0) + cents

    return awards


_STREET_ORDER = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}
_DECISION_ACTIONS = {"CHECK", "FOLD", "CALL", "BET", "RAISE", "ALLIN"}
_VOLUNTARY_MONEY_ACTIONS = {"CALL", "BET", "RAISE", "ALLIN"}


def _rit_dead_sets(hand: Hand, base_board: str) -> list[tuple[str, ...]]:
    """Dead-card sets for sequential CoinPoker RIT/RIT+1 runouts.
    CoinPoker deals multiple runouts from one physical remaining deck.  The first
    run uses the deck as it stood at the all-in; cards consumed by that completed
    run are unavailable to the second, and so on.  Shared cards already present
    at the all-in are board cards, not dead cards.
    """
    if hand.run_count <= 1:
        return [()]
    if len(hand.boards) < hand.run_count or any(not b for b in hand.boards[:hand.run_count]):
        return [()]
    base = set(base_board.split())
    prior: list[str] = []
    out: list[tuple[str, ...]] = []
    for board_text in hand.boards[:hand.run_count]:
        out.append(tuple(prior))
        for card in board_text.split():
            if card not in base and card not in prior:
                prior.append(card)
    return out

def _collection_segments(hand: Hand, targets: list[float]) -> list[tuple[float, set[str]]] | None:
    """Consume CoinPoker collection lines in main-pot/side-pot order.
    CoinPoker emits main-pot collections before subsequent side-pot collections.
    This lets us preserve the *actual* result of later side-pot play while replacing
    only an earlier locked pot with its all-in equity.  A collection line may span
    a rounding boundary; in that case its cents are split across adjacent targets.
    """
    cols = [(a.player, float(a.amount_cents)) for a in hand.actions if a.action == "COLLECT"]
    if not targets:
        return []
    if not cols:
        return None
    ci = 0
    left = cols[0][1]
    out: list[tuple[float, set[str]]] = []
    for target in targets:
        need = float(round(target))
        hero_amt = 0.0
        winners: set[str] = set()
        guard = 0
        while need > 0.5 and ci < len(cols):
            player, _ = cols[ci]
            take = min(left, need)
            if take > 0:
                winners.add(player)
                if player == hand.hero_name:
                    hero_amt += take
                left -= take
                need -= take
            if left <= 0.5:
                ci += 1
                if ci < len(cols):
                    left = cols[ci][1]
            guard += 1
            if guard > len(cols) + 5:
                break
        if need > 1.5:
            return None
        out.append((hero_amt, winners))
    return out

def _allin_adjustment(
    hand: Hand,
    results: dict[str, PlayerResult],
    shown_cards: dict[str, str],
    folded_players: set[str],
) -> tuple[float, float | None, bool, bool]:
    """Return (adjusted net cents, weighted equity, adjusted?, estimated?).
    v0.11 calculates EV at the *pot-layer* level.  If a short stack is all-in and
    deeper players continue on later streets, only the already-locked main pot is
    equity-adjusted; the later side-pot result stays actual.  This matches the
    behavior exposed by the larger CoinPoker sample and avoids the old all-or-none
    hand-level exclusion.
    """
    hero = results.get(hand.hero_name)
    if hero is None:
        return 0.0, None, False, False
    actual = float(hero.net_cents)
    if hand.game != "NLH":
        return actual, None, False, False
    pre_river_allins = [
        a for a in hand.actions
        if a.action == "ALLIN" and a.street != "RIVER"
    ]
    if not pre_river_allins:
        return actual, None, False, False
    if any(a.player == hand.hero_name and a.action == "FOLD" for a in hand.actions):
        return actual, None, False, False
    first = min(pre_river_allins, key=lambda a: a.seq)
    first_order = _STREET_ORDER.get(first.street, -1)
    later_street_action = any(
        a.seq > first.seq
        and a.action in _DECISION_ACTIONS
        and _STREET_ORDER.get(a.street, -1) > first_order
        for a in hand.actions
    )
    # If a player voluntarily enters the all-in pot after the first shove and then
    # folds on the same street without revealing, the live range is unknowable from
    # the export and is highly selected.  Keep the actual result for that hand.
    post_first = [a for a in hand.actions if a.seq > first.seq]
    for fold in (a for a in post_first if a.action == "FOLD"):
        prior_after_allin = any(
            b.player == fold.player and b.seq < fold.seq and b.action in _VOLUNTARY_MONEY_ACTIONS
            for b in post_first
        )
        if prior_after_allin and fold.player not in shown_cards:
            return actual, None, False, False
    effective = {
        player: max(0, pr.contributed_cents - pr.returned_cents)
        for player, pr in results.items()
    }
    hero_eff = effective.get(hand.hero_name, 0)
    if hero_eff <= 0:
        return actual, None, False, False
    levels = sorted({c for c in effective.values() if c > 0})
    layers: list[tuple[int, int, list[str]]] = []  # (top level, gross cents, contributors)
    prev = 0
    for level in levels:
        contributors = [p for p, c in effective.items() if c >= level]
        amount = (level - prev) * len(contributors)
        if amount > 0:
            layers.append((level, amount, contributors))
        prev = level
    if not layers:
        return actual, None, False, False
    gross_from_layers = sum(amount for _, amount, _ in layers)
    player_total_pot = max(0, hand.total_pot_cents - hand.splash_cents)
    net_pot = max(0, player_total_pot - hand.rake_cents - hand.splash_fee_cents)
    if gross_from_layers <= 0 or net_pot <= 0:
        return actual, None, False, False
    if abs(gross_from_layers - player_total_pot) > 1:
        return actual, None, False, False
    # When action continues later, the first all-in player's effective contribution
    # is the cap of the pot that was already locked.  Higher layers remain actual.
    if later_street_action:
        lock_cap = effective.get(first.player, 0)
        if lock_cap <= 0 or hero_eff < min(lock_cap, hero_eff):
            return actual, None, False, False
        work_layers = [x for x in layers if x[0] <= lock_cap]
    else:
        work_layers = layers
    if not work_layers:
        return actual, None, False, False
    net_layers = [amount * (net_pot / gross_from_layers) for _, amount, _ in work_layers]
    actual_segments = _collection_segments(hand, net_layers) if later_street_action else None
    if later_street_action and actual_segments is None:
        return actual, None, False, False
    locked_observed_names: set[str] = set()
    if actual_segments is not None:
        for _, names in actual_segments:
            locked_observed_names.update(names)
    dead_sets = _rit_dead_sets(hand, hand.first_allin_board)
    expected_return = 0.0
    actual_locked_return = 0.0
    weighted_equity_num = 0.0
    weighted_equity_den = 0.0
    adjusted_any = False
    estimated_any = False
    for li, ((_, gross_amount, contributors), net_layer) in enumerate(zip(work_layers, net_layers)):
        if hand.hero_name not in contributors:
            continue
        eligible = [p for p in contributors if p not in folded_players]
        if hand.hero_name not in eligible:
            continue

        if later_street_action:
            assert actual_segments is not None
            hero_actual_layer, observed_winners = actual_segments[li]
            actual_locked_return += hero_actual_layer
        # A sole eligible player owns this layer deterministically.
        if len(eligible) == 1:
            expected_return += net_layer
            continue

        hero_idx = eligible.index(hand.hero_name)
        known_flags = [len(shown_cards.get(p, "").split()) == 2 for p in eligible]
        equities_by_run: list[float] = []
        if all(known_flags):
            for dead in dead_sets:
                if dead:
                    eqs = exact_equities(
                        [shown_cards[p] for p in eligible],
                        hand.first_allin_board,
                        dead_cards=dead,
                    )
                else:
                    eqs = exact_equities(
                        [shown_cards[p] for p in eligible],
                        hand.first_allin_board,
                    )
                if eqs is None:
                    return actual, None, False, False
                equities_by_run.append(eqs[hero_idx])
        elif later_street_action and known_flags.count(False) == 1 and hand.run_count == 1:
            # Coin knows the mucked live hand; an exported HH does not.  Infer a
            # posterior range from the actual completed board/main-pot winner and
            # mark the result as estimated in the UI.
            final_board = hand.boards[0] if hand.boards else ""
            if not final_board or actual_segments is None:
                return actual, None, False, False
            observed_idx = {i for i, p in enumerate(eligible) if p in locked_observed_names}
            if not observed_idx:
                return actual, None, False, False
            hand_inputs: list[str | None] = [
                shown_cards[p] if known_flags[i] else None
                for i, p in enumerate(eligible)
            ]
            eqs = estimate_equities_with_unknown(
                hand_inputs,
                hand.first_allin_board,
                final_board,
                observed_idx,
            )
            if eqs is None:
                return actual, None, False, False
            equities_by_run.append(eqs[hero_idx])
            estimated_any = True
        else:
            return actual, None, False, False
        hero_eq = sum(equities_by_run) / len(equities_by_run)
        expected_return += net_layer * hero_eq
        weighted_equity_num += net_layer * hero_eq
        weighted_equity_den += net_layer
        adjusted_any = True

    if not adjusted_any:
        return actual, None, False, False
    weighted_equity = (weighted_equity_num / weighted_equity_den) if weighted_equity_den else None
    if later_street_action:
        # Replace only the locked pot's real return with its equity share.  Hero's
        # later side-pot actions, returns, Splash award, etc. remain actual.
        adjusted_net = actual + (expected_return - actual_locked_return)
    else:
        # Entire player-funded pot was locked before the runout.  Splash/Mega Splash
        # promotional chips are not part of PokerIntel's equity pot.
        adjusted_net = expected_return - hero_eff
    return adjusted_net, weighted_equity, True, estimated_any

class ParseError(ValueError):
    pass

def _position_map(seats: list[Seat], button_seat: int) -> dict[int, str]:
    occupied = sorted(s.seat_no for s in seats)
    n = len(occupied)
    if not occupied or button_seat not in occupied:
        return {}
    bi = occupied.index(button_seat)
    order = occupied[bi:] + occupied[:bi]
    if n == 2:
        labels = ["BTN/SB", "BB"]
    elif n == 3:
        labels = ["BTN", "SB", "BB"]
    elif n == 4:
        labels = ["BTN", "SB", "BB", "CO"]
    elif n == 5:
        labels = ["BTN", "SB", "BB", "UTG", "CO"]
    elif n >= 6:
        pre = ["BTN", "SB", "BB"]
        middle_count = n - 3
        if middle_count == 3:
            mid = ["UTG", "HJ", "CO"]
        elif middle_count == 4:
            mid = ["UTG", "MP", "HJ", "CO"]
        else:
            mid = [f"EP{i+1}" for i in range(max(0, middle_count - 2))] + (["HJ", "CO"] if middle_count >= 2 else ["CO"])
        labels = pre + mid
    else:
        labels = ["BTN"]
    return {seat: labels[i] if i < len(labels) else f"P{i+1}" for i, seat in enumerate(order)}

def parse_hand(text: str, hero_name: str = "Hero") -> Hand:
    lines = [ln.rstrip("\r") for ln in text.strip().splitlines()]
    if not lines:
        raise ParseError("Empty hand")

    m = HEADER_RE.match(lines[0].strip())
    if not m:
        raise ParseError(f"Unrecognized CoinPoker header: {lines[0]!r}")
    started = datetime.strptime(f"{m.group('date')} {m.group('time')}", "%Y/%m/%d %H:%M:%S")
    hand = Hand(
        hand_id=m.group("id"),
        game=m.group("game"),
        sb_cents=money_to_cents(m.group("sb")),
        bb_cents=money_to_cents(m.group("bb")),
        started_at=started,
        timezone=m.group("tz"),
        hero_name=hero_name,
        raw_text=text.strip() + "\n",
    )
    # First pass for table/seats so positions are known before stats are finalized.
    for line in lines[1:]:
        s = line.strip()
        if mt := TABLE_RE.match(s):
            hand.table_name, max_seats, button = mt.groups()
            hand.max_seats = int(max_seats)
            hand.button_seat = int(button)
        elif ms := SEAT_RE.match(s):
            seat_no, player, stack = ms.groups()
            hand.seats.append(Seat(int(seat_no), player, money_to_cents(stack)))
    posmap = _position_map(hand.seats, hand.button_seat)
    seat_by_player: dict[str, Seat] = {}
    for seat in hand.seats:
        seat.position = posmap.get(seat.seat_no, "")
        seat_by_player[seat.player] = seat
        if seat.player == hero_name:
            hand.hero_seat = seat.seat_no
            hand.hero_position = seat.position
    results: dict[str, PlayerResult] = {
        seat.player: PlayerResult(
            player=seat.player,
            seat_no=seat.seat_no,
            stack_cents=seat.stack_cents,
            position=seat.position,
        )
        for seat in hand.seats
    }
    street = "PREFLOP"
    run_index = 1
    street_contrib: dict[str, int] = {p: 0 for p in results}
    preflop_raise_count = 0
    seq = 0
    in_showdown = False
    any_board = False
    shown_cards: dict[str, str] = {}
    folded_players: set[str] = set()
    mucked_players: set[str] = set()
    current_board = ""
    def ensure_player(name: str) -> PlayerResult:
        if name not in results:
            results[name] = PlayerResult(player=name)
            street_contrib[name] = 0
        return results[name]

    def add_action(player: str, action: str, amount: int = 0, to_amt: int = 0, *, aggressive: bool = False, raise_no: int = 0, raw: str = ""):
        nonlocal seq
        seq += 1
        hand.actions.append(Action(seq, street, run_index, player, action, amount, to_amt, raw, aggressive, raise_no))
    for line in lines[1:]:
        s = line.strip()
        if not s:
            continue

        if ms := SPLASH_RE.match(s):
            hand.splash_type = ms.group(1)
            hand.splash_cents = money_to_cents(ms.group(2))
            continue

        if md := DEALT_RE.match(s):
            player, cards = md.groups()
            if player == hero_name and cards:
                hand.hero_cards = cards
                shown_cards[player] = cards
            continue
        if sm := STREET_RE.match(s):
            run_word, new_street = sm.groups()
            new_run = RUN_WORD[run_word]
            if new_run == 1:
                board_cards = re.findall(r"[2-9TJQKA][cdhs]", s)
                if board_cards:
                    current_board = " ".join(board_cards)
            # Reset betting contribution only when entering a new actual betting street
            # for the first runout. SECOND/THIRD markers are board-only after all-in.
            if new_run == 1 and new_street != street:
                street_contrib = {p: 0 for p in street_contrib}
            street = new_street
            run_index = new_run
            any_board = True
            in_showdown = False
            continue
        if sd := SHOWDOWN_MARKER_RE.match(s):
            run_index = RUN_WORD[sd.group(1)]
            in_showdown = True
            continue
        if mp := POST_RE.match(s):
            player, kind, amount_s = mp.groups()
            amount = money_to_cents(amount_s)
            pr = ensure_player(player)
            pr.contributed_cents += amount
            # Antes are forced dead money. CoinPoker's "raises ... to ..." amount
            # is the betting-street total and does not include the ante.
            if kind != "ante":
                street_contrib[player] = street_contrib.get(player, 0) + amount
            add_action(player, kind.upper().replace(" ", "_"), amount, raw=s)
            continue
        if mst := STRADDLE_RE.match(s):
            player, amount_s = mst.groups()
            amount = money_to_cents(amount_s)
            pr = ensure_player(player)
            pr.contributed_cents += amount
            street_contrib[player] = street_contrib.get(player, 0) + amount
            add_action(player, "STRADDLE", amount, raw=s)
            continue
        if mr := RAISE_RE.match(s):
            player, by_s, to_s = mr.groups()
            to_amt = money_to_cents(to_s)
            already = street_contrib.get(player, 0)
            increment = max(0, to_amt - already)
            pr = ensure_player(player)
            pr.contributed_cents += increment
            street_contrib[player] = to_amt
            raise_no = 0
            if street == "PREFLOP":
                if preflop_raise_count == 1:
                    pr.three_bet_opp = True
                preflop_raise_count += 1
                raise_no = preflop_raise_count
                pr.vpip = True
                pr.pfr = True
                if preflop_raise_count >= 2:
                    pr.three_bet = True
            add_action(player, "RAISE", increment, to_amt, aggressive=True, raise_no=raise_no, raw=s)
            continue
        if mc := CALL_RE.match(s):
            player, amount_s = mc.groups()
            amount = money_to_cents(amount_s)
            pr = ensure_player(player)
            pr.contributed_cents += amount
            street_contrib[player] = street_contrib.get(player, 0) + amount
            if street == "PREFLOP":
                pr.vpip = True
                if preflop_raise_count == 1:
                    pr.three_bet_opp = True
            add_action(player, "CALL", amount, raw=s)
            continue
        if mb := BET_RE.match(s):
            player, amount_s = mb.groups()
            amount = money_to_cents(amount_s)
            pr = ensure_player(player)
            pr.contributed_cents += amount
            street_contrib[player] = street_contrib.get(player, 0) + amount
            add_action(player, "BET", amount, aggressive=True, raw=s)
            continue
        if ma := ALLIN_RE.match(s):
            player, amount_s = ma.groups()
            amount = money_to_cents(amount_s)
            pr = ensure_player(player)
            # CoinPoker's ALLIN amount is the amount pushed on this action, not "to" amount.
            previous_max = max(street_contrib.values(), default=0)
            before = street_contrib.get(player, 0)
            after = before + amount
            pr.contributed_cents += amount
            street_contrib[player] = after
            aggressive = after > previous_max
            raise_no = 0
            if street == "PREFLOP":
                pr.vpip = True
                if preflop_raise_count == 1:
                    pr.three_bet_opp = True
                if aggressive:
                    preflop_raise_count += 1
                    raise_no = preflop_raise_count
                    pr.pfr = True
                    if preflop_raise_count >= 2:
                        pr.three_bet = True
            add_action(player, "ALLIN", amount, after, aggressive=aggressive, raise_no=raise_no, raw=s)
            if not hand.first_allin_street:
                hand.first_allin_street = street
                hand.first_allin_board = current_board
            continue
        if mret := RETURN_RE.match(s):
            player, amount_s = mret.groups()
            amount = money_to_cents(amount_s)
            pr = ensure_player(player)
            pr.returned_cents += amount
            add_action(player, "RETURN", amount, raw=s)
            continue
        if mf := FOLD_RE.match(s):
            player = mf.group(1)
            folded_players.add(player)
            pr = ensure_player(player)
            if street == "PREFLOP":
                pr.folded_preflop = True
                if preflop_raise_count == 1:
                    pr.three_bet_opp = True
            add_action(player, "FOLD", raw=s)
            continue

        if mch := CHECK_RE.match(s):
            add_action(mch.group(1), "CHECK", raw=s)
            continue
        if msh := SHOW_RE.match(s):
            player = msh.group(1)
            shown_cards[player] = msh.group(2)
            pr = ensure_player(player)
            pr.went_to_showdown = True
            add_action(player, "SHOW", raw=s)
            continue
        if mm := MUCK_RE.match(s):
            player = mm.group(1)
            mucked_players.add(player)
            pr = ensure_player(player)
            pr.went_to_showdown = True
            add_action(player, "MUCK", raw=s)
            continue
        if mcol := COLLECT_RE.match(s):
            player, amount_s = mcol.groups()
            amount = money_to_cents(amount_s)
            pr = ensure_player(player)
            pr.collected_cents += amount
            if in_showdown and pr.went_to_showdown:
                pr.won_showdown = True
            add_action(player, "COLLECT", amount, raw=s)
            continue
        if mt := TOTAL_RE.match(s):
            hand.total_pot_cents = money_to_cents(mt.group(1))
            hand.rake_cents = money_to_cents(mt.group(2))
            hand.splash_fee_cents = money_to_cents(mt.group(3))
            continue

        if mrn := RUN_RE.match(s):
            hand.run_count = RUN_MAP[mrn.group(1)]
            continue
        if mbd := BOARD_RE.match(s):
            which, cards = mbd.groups()
            idx = RUN_WORD[which]
            while len(hand.boards) < idx:
                hand.boards.append("")
            hand.boards[idx - 1] = cards.strip()
            if cards.strip():
                any_board = True
            continue

        if mend := END_RE.match(s):
            hand.ended_at = datetime.strptime(f"{mend.group(1)} {mend.group(2)}", "%Y/%m/%d %H:%M:%S")
            continue
    splash_awards = _splash_awards(hand, results, shown_cards, folded_players, mucked_players)
    for pr in results.values():
        pr.splash_won_cents = splash_awards.get(pr.player, 0)
        pr.net_cents = (
            pr.collected_cents + pr.returned_cents + pr.splash_won_cents
            - pr.contributed_cents
        )
        pr.saw_flop = any_board and not pr.folded_preflop
        # A player can muck at showdown, or show on any runout. Winners that never show
        # (everyone else folded) are deliberately not counted as W$SD.
    adj, equity, adjusted, estimated = _allin_adjustment(hand, results, shown_cards, folded_players)
    hero_pr = results.get(hand.hero_name)
    if hero_pr is not None:
        hero_pr.allin_adj_cents = adj
        hero_pr.allin_equity = equity
        hero_pr.allin_adjusted = adjusted
        hero_pr.allin_estimated = estimated
    for pr in results.values():
        if pr.player != hand.hero_name:
            pr.allin_adj_cents = float(pr.net_cents)
    hand.player_results = results
    # Summary says run count; guarantee a useful board slot for run-once hands.
    if not hand.boards:
        hand.boards = [""]
    return hand


def iter_hand_texts(text: str, require_complete: bool = True) -> Iterator[str]:
    """Yield CoinPoker hand blocks from arbitrary text.
    require_complete=True skips a trailing hand that has not reached SUMMARY/Game ended yet,
    which makes this safe for files CoinPoker is actively appending to.
    """
    starts = [m.start() for m in re.finditer(r"(?m)^CoinPoker Hand #", text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[start:end].strip()
        if not block:
            continue
        if require_complete and ("*** SUMMARY ***" not in block or "Game ended:" not in block):
            continue
        yield block + "\n"

def parse_file(path: str, hero_name: str = "Hero") -> Iterator[Hand]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    for block in iter_hand_texts(text, require_complete=True):
        yield parse_hand(block, hero_name=hero_name)
