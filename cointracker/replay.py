from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import Action, Hand


_STREET_RE = re.compile(
    r"^\*\*\* (?:(FIRST|SECOND|THIRD) )?(FLOP|TURN|RIVER) \*\*\*"
)
_SHOWDOWN_RE = re.compile(
    r"^\*\*\* (?:(FIRST|SECOND|THIRD) )?SHOWDOWN \*\*\*$"
)
_DEALT_RE = re.compile(r"^Dealt to (.+?)(?: \[([^\]]+)\])?$")
_SHOW_RE = re.compile(r"^(.+?): shows \[([^\]]+)\]")
_CARD_RE = re.compile(r"[2-9TJQKA][cdhs]", re.IGNORECASE)

_RUN_INDEX = {None: 1, "FIRST": 1, "SECOND": 2, "THIRD": 3}
_MONEY_IN_ACTIONS = {
    "ANTE",
    "SMALL_BLIND",
    "BIG_BLIND",
    "AUTO_BIG_BLIND",
    "STRADDLE",
    "CALL",
    "BET",
    "RAISE",
    "ALLIN",
}


@dataclass(frozen=True, slots=True)
class ReplaySeat:
    seat_no: int
    player: str
    position: str
    starting_stack_cents: int
    is_button: bool = False


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    street: str
    run_index: int
    boards: tuple[str, ...]
    pot_cents: int
    stacks: dict[str, int]
    street_bets: dict[str, int]
    cards: dict[str, str]
    folded: frozenset[str]
    active_player: str
    action_text: str
    complete: bool = False


@dataclass(frozen=True, slots=True)
class ReplayHand:
    hand_id: str
    game: str
    sb_cents: int
    bb_cents: int
    splash_type: str
    splash_cents: int
    hero_name: str
    seats: tuple[ReplaySeat, ...]
    frames: tuple[ReplayFrame, ...]


def format_chips(cents: int) -> str:
    """Format integer CoinPoker cents without floating-point rounding."""
    sign = "-" if cents < 0 else ""
    value = abs(int(cents))
    return f"{sign}₮{value // 100}.{value % 100:02d}"


def _fallback_action_text(action: Action) -> str:
    label = action.action.replace("_", " ").title()
    if action.action == "RAISE" and action.to_cents:
        return f"{action.player}: raises to {format_chips(action.to_cents)}"
    if action.amount_cents:
        return f"{action.player}: {label.lower()} {format_chips(action.amount_cents)}"
    return f"{action.player}: {label.lower()}"


def _board_from_marker(hand: Hand, line: str, run_index: int, street: str) -> str:
    cards = _CARD_RE.findall(line)
    if cards:
        return " ".join(card[0].upper() + card[1].lower() for card in cards)

    board = hand.boards[run_index - 1] if run_index <= len(hand.boards) else ""
    count = {"FLOP": 3, "TURN": 4, "RIVER": 5}.get(street, 0)
    return " ".join(board.split()[:count])


def build_replay(hand: Hand) -> ReplayHand:
    """Create immutable visual-replay frames from a parsed CoinPoker hand.

    The parser's normalized actions drive chip movement, while raw hand-history
    street markers preserve the exact order in which multi-run boards appeared.
    """
    ordered_seats = sorted(hand.seats, key=lambda item: item.seat_no)
    hero_index = next(
        (
            index
            for index, seat in enumerate(ordered_seats)
            if seat.player == hand.hero_name
        ),
        0,
    )
    ordered_seats = ordered_seats[hero_index:] + ordered_seats[:hero_index]
    seats = tuple(
        ReplaySeat(
            seat_no=seat.seat_no,
            player=seat.player,
            position=seat.position,
            starting_stack_cents=seat.stack_cents,
            is_button=seat.seat_no == hand.button_seat,
        )
        for seat in ordered_seats
    )
    players = [seat.player for seat in seats]
    stacks = {seat.player: seat.starting_stack_cents for seat in seats}
    street_bets = {player: 0 for player in players}
    cards: dict[str, str] = {}
    folded: set[str] = set()
    board_count = max(1, hand.run_count, len(hand.boards))
    boards = ["" for _ in range(board_count)]
    frames: list[ReplayFrame] = []

    street = "PREFLOP"
    run_index = 1
    pot_cents = int(hand.splash_cents or 0)

    def snapshot(
        text: str,
        *,
        active_player: str = "",
        is_complete: bool = False,
    ) -> None:
        frames.append(
            ReplayFrame(
                street=street,
                run_index=run_index,
                boards=tuple(boards),
                pot_cents=max(0, int(pot_cents)),
                stacks=dict(stacks),
                street_bets=dict(street_bets),
                cards=dict(cards),
                folded=frozenset(folded),
                active_player=active_player,
                action_text=text,
                complete=is_complete,
            )
        )

    opening = "Ready to replay"
    if hand.splash_cents:
        splash = hand.splash_type or "Splash"
        opening = f"{splash.title()} adds {format_chips(hand.splash_cents)}"
    snapshot(opening)

    actions = sorted(hand.actions, key=lambda item: item.seq)
    action_index = 0

    def apply_action(action: Action) -> None:
        nonlocal pot_cents, street, run_index
        if action.street:
            street = action.street
        run_index = max(1, int(action.run_index or 1))
        player = action.player

        if player and player not in stacks:
            stacks[player] = 0
            street_bets[player] = 0

        if action.action in _MONEY_IN_ACTIONS:
            amount = max(0, int(action.amount_cents or 0))
            stacks[player] = stacks.get(player, 0) - amount
            street_bets[player] = street_bets.get(player, 0) + amount
            pot_cents += amount
        elif action.action == "RETURN":
            amount = max(0, int(action.amount_cents or 0))
            stacks[player] = stacks.get(player, 0) + amount
            street_bets[player] = max(0, street_bets.get(player, 0) - amount)
            pot_cents = max(0, pot_cents - amount)
        elif action.action == "COLLECT":
            amount = max(0, int(action.amount_cents or 0))
            stacks[player] = stacks.get(player, 0) + amount
            pot_cents = max(0, pot_cents - amount)

        if action.action == "FOLD":
            folded.add(player)
        elif action.action == "SHOW":
            shown = _SHOW_RE.match(action.raw or "")
            if shown:
                cards[player] = shown.group(2)

        snapshot(
            action.raw or _fallback_action_text(action),
            active_player=player,
        )

    for raw_line in hand.raw_text.splitlines()[1:]:
        line = raw_line.strip()
        if not line:
            continue

        dealt = _DEALT_RE.match(line)
        if dealt and dealt.group(2):
            dealt_player = dealt.group(1)
            cards[dealt_player] = dealt.group(2)
            snapshot(
                f"{dealt_player} is dealt [{dealt.group(2)}]",
                active_player=dealt_player,
            )
            continue

        street_match = _STREET_RE.match(line)
        if street_match:
            run_word, street = street_match.groups()
            run_index = _RUN_INDEX[run_word]
            if run_index == 1:
                street_bets = {player: 0 for player in street_bets}
            while len(boards) < run_index:
                boards.append("")
            boards[run_index - 1] = _board_from_marker(
                hand,
                line,
                run_index,
                street,
            )
            run_label = f"Run {run_index} " if hand.run_count > 1 else ""
            snapshot(f"{run_label}{street.title()} dealt")
            continue

        showdown_match = _SHOWDOWN_RE.match(line)
        if showdown_match:
            run_index = _RUN_INDEX[showdown_match.group(1)]
            label = f"Run {run_index} showdown" if hand.run_count > 1 else "Showdown"
            snapshot(label)
            continue

        if (
            action_index < len(actions)
            and line == (actions[action_index].raw or "").strip()
        ):
            apply_action(actions[action_index])
            action_index += 1

    # Defensive fallback for a future parser action whose source line is not
    # represented in the raw-history scan above.
    while action_index < len(actions):
        apply_action(actions[action_index])
        action_index += 1

    for seat in seats:
        result = hand.player_results.get(seat.player)
        if result is not None:
            stacks[seat.player] = seat.starting_stack_cents + int(result.net_cents)
    street_bets = {player: 0 for player in street_bets}
    pot_cents = 0
    hero_net = int(hand.hero_result.net_cents)
    if hero_net > 0:
        summary = f"Hand complete · {hand.hero_name} won {format_chips(hero_net)}"
    elif hero_net < 0:
        summary = f"Hand complete · {hand.hero_name} lost {format_chips(-hero_net)}"
    else:
        summary = f"Hand complete · {hand.hero_name} broke even"
    snapshot(summary, is_complete=True)

    return ReplayHand(
        hand_id=hand.hand_id,
        game=hand.game,
        sb_cents=hand.sb_cents,
        bb_cents=hand.bb_cents,
        splash_type=hand.splash_type,
        splash_cents=hand.splash_cents,
        hero_name=hand.hero_name,
        seats=seats,
        frames=tuple(frames),
    )
