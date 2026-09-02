from __future__ import annotations

from fractions import Fraction
from itertools import combinations
import hashlib
import random
from typing import Sequence

try:
    import eval7  # type: ignore
    try:
        # eval7's Monte Carlo engine uses this Cython-backed RNG internally.
        # Seeding it makes the native fast path reproducible for a given matchup.
        from eval7 import xorshift_rand as _eval7_rng  # type: ignore
    except Exception:  # pragma: no cover
        _eval7_rng = None
except Exception:  # pragma: no cover - optional speed-up
    eval7 = None
    _eval7_rng = None

RANKS = "23456789TJQKA"
SUITS = "cdhs"
FULL_DECK = tuple(r + s for r in RANKS for s in SUITS)

# Fallback used when the native eval7 fast path cannot be used (multiway,
# dead-card/RIT cases, or eval7 unavailable).
PREFLOP_MC_ITERATIONS = 250_000

# Heads-up known-card preflop spots can be pushed entirely into eval7's Cython
# Monte Carlo engine.  This uses more samples than the old Python loop while
# normally being much faster because board dealing + hand evaluation stay in
# compiled code instead of crossing Python 250,000 times.
#
# IMPORTANT: eval7 0.1.11 does NOT expose an exhaustive preflop-equity API.
# Its py_hand_vs_range_exact() function is exact only when the board supplied
# to it is already complete.  Therefore this fast path is still Monte Carlo,
# just native + deterministic.  It is intentionally isolated here so it can be
# replaced later by a true native exhaustive backend without touching parser.py.
PREFLOP_NATIVE_ITERATIONS = 1_000_000

UNKNOWN_HOLE_MC_ITERATIONS = 150_000


def evaluator_available() -> bool:
    """Whether the optional accelerated 7-card evaluator is available."""
    return eval7 is not None


def _normalize(cards: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(cards, str):
        return tuple(c for c in cards.split() if c)
    return tuple(cards)


def _river_rank(cards: tuple[str, ...]) -> tuple[int, ...]:
    """Small dependency-free seven-card evaluator. Larger tuples are better."""
    from collections import Counter

    vals = sorted((RANKS.index(c[0]) + 2 for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    counts = Counter(vals)
    unique = sorted(counts, reverse=True)
    if 14 in unique:
        unique.append(1)

    straight_high = 0
    for i in range(len(unique) - 4):
        seq = unique[i:i + 5]
        if seq[0] - seq[4] == 4:
            straight_high = seq[0]
            break

    flush_suit = None
    for suit in SUITS:
        if suits.count(suit) >= 5:
            flush_suit = suit
            break

    if flush_suit:
        fvals = sorted(
            (RANKS.index(c[0]) + 2 for c in cards if c[1] == flush_suit),
            reverse=True,
        )
        fu = sorted(set(fvals), reverse=True)
        if 14 in fu:
            fu.append(1)
        for i in range(len(fu) - 4):
            seq = fu[i:i + 5]
            if seq[0] - seq[4] == 4:
                return (8, seq[0])

    quads = sorted((v for v, n in counts.items() if n == 4), reverse=True)
    if quads:
        q = quads[0]
        return (7, q, max(v for v in vals if v != q))

    trips = sorted((v for v, n in counts.items() if n >= 3), reverse=True)
    pairs = sorted((v for v, n in counts.items() if n >= 2), reverse=True)

    if trips:
        t = trips[0]
        pair_choices = [v for v in pairs if v != t]
        if pair_choices:
            return (6, t, pair_choices[0])

    if flush_suit:
        fvals = sorted(
            (RANKS.index(c[0]) + 2 for c in cards if c[1] == flush_suit),
            reverse=True,
        )
        return (5, *fvals[:5])

    if straight_high:
        return (4, straight_high)

    if trips:
        t = trips[0]
        kickers = [v for v in vals if v != t][:2]
        return (3, t, *kickers)

    exact_pairs = sorted((v for v, n in counts.items() if n == 2), reverse=True)
    if len(exact_pairs) >= 2:
        hi, lo = exact_pairs[:2]
        return (2, hi, lo, max(v for v in vals if v not in (hi, lo)))

    if exact_pairs:
        p = exact_pairs[0]
        return (1, p, *[v for v in vals if v != p][:3])

    return (0, *vals[:5])


def _native_heads_up_preflop(
    hands: Sequence[tuple[str, ...]],
    dead_cards: tuple[str, ...],
    iterations: int = PREFLOP_NATIVE_ITERATIONS,
) -> list[float] | None:
    """Fast reproducible heads-up preflop equity using eval7's native MC engine.

    eval7's public exact function does not enumerate missing community cards, so
    it cannot provide exact preflop equity.  Its Cython Monte Carlo routine does,
    however, keep the expensive deal/evaluate loop in native code.

    We only use this fast path when:
      * exactly two concrete hands are known;
      * there are no RIT dead cards;
      * eval7 is installed.

    Multiway and dead-card cases fall back to the tracker's original deterministic
    Python sampler, preserving support for all existing hand-history shapes.
    """
    if eval7 is None or len(hands) != 2 or dead_cards:
        return None

    try:
        hero_cards = tuple(eval7.Card(c) for c in hands[0])
        # HandRange accepts an exact concrete combo such as "AsAd".
        villain_range = eval7.HandRange("".join(hands[1]))

        # eval7's xorshift RNG is seedable.  Use a stable matchup-derived seed so
        # repeated imports of the same hand produce the same result.
        seed_text = (
            "|".join(" ".join(h) for h in hands)
            + f"|n={iterations}|native-eval7-v1"
        )
        seed = int.from_bytes(
            hashlib.sha256(seed_text.encode("ascii")).digest()[:8],
            "big",
        )
        if _eval7_rng is not None:
            _eval7_rng.seed(seed)

        hero_equity = float(
            eval7.py_hand_vs_range_monte_carlo(
                hero_cards,
                villain_range,
                (),
                iterations,
            )
        )

        if not (0.0 <= hero_equity <= 1.0):
            return None

        # Heads-up equity shares (including split-pot shares) sum to 1.
        return [hero_equity, 1.0 - hero_equity]
    except Exception:
        # Do not make an import fail because the optional native path is missing
        # or behaves differently on a particular packaged build.
        return None


def _deterministic_board_monte_carlo(
    hands: Sequence[tuple[str, ...]],
    board: tuple[str, ...],
    dead_cards: tuple[str, ...],
    iterations: int = PREFLOP_MC_ITERATIONS,
) -> list[float] | None:
    """Reproducible concrete-hand equity for an incomplete board.

    This is the original CoinPokerTracker fallback path.  The board samples are
    generated by Python's Mersenne Twister from a SHA-256 seed derived from the
    exact hole cards, current board and dead cards.
    """
    if len(hands) < 2:
        return None

    known = {c for h in hands for c in h} | set(board) | set(dead_cards)
    remaining = [c for c in FULL_DECK if c not in known]
    needed = 5 - len(board)
    if needed <= 0 or len(remaining) < needed:
        return None

    seed_text = (
        "|".join(" ".join(h) for h in hands)
        + "|" + " ".join(board)
        + "|" + " ".join(dead_cards)
        + f"|n={iterations}|v=7"
    )
    seed = int.from_bytes(
        hashlib.sha256(seed_text.encode("ascii")).digest()[:8],
        "big",
    )
    rng = random.Random(seed)
    wins = [0.0 for _ in hands]

    if eval7 is not None:
        ehands = [[eval7.Card(c) for c in h] for h in hands]
        eboard = [eval7.Card(c) for c in board]
        eremaining = [eval7.Card(c) for c in remaining]

        for _ in range(iterations):
            extra = rng.sample(eremaining, needed)
            full_board = eboard + extra
            ranks = [eval7.evaluate(ehand + full_board) for ehand in ehands]
            best = max(ranks)
            winners = [i for i, rank in enumerate(ranks) if rank == best]
            share = 1.0 / len(winners)
            for i in winners:
                wins[i] += share
    else:
        for _ in range(iterations):
            extra = tuple(rng.sample(remaining, needed))
            full_board = board + extra
            ranks = [_river_rank(h + full_board) for h in hands]
            best = max(ranks)
            winners = [i for i, rank in enumerate(ranks) if rank == best]
            share = 1.0 / len(winners)
            for i in winners:
                wins[i] += share

    return [w / iterations for w in wins]


def exact_equities(
    hands: Sequence[str | Sequence[str]],
    board: str | Sequence[str],
    dead_cards: str | Sequence[str] = (),
) -> list[float] | None:
    """Equity shares for concrete known Hold'em hands.

    Flop/turn/river spots remain exhaustively enumerated exactly, matching the
    current tracker.

    Heads-up preflop spots with no RIT dead cards use eval7's compiled Monte Carlo
    engine for speed.  The native path uses 1,000,000 samples and a stable seed.

    Multiway preflop and dead-card/RIT preflop spots use the existing deterministic
    250,000-board Python sampler.
    """
    hole = [_normalize(h) for h in hands]
    community = _normalize(board)
    dead = _normalize(dead_cards)

    if len(hole) < 2 or any(len(h) != 2 for h in hole):
        return None
    if len(community) not in (0, 3, 4, 5):
        return None

    known = [c for h in hole for c in h] + list(community) + list(dead)
    if len(set(known)) != len(known):
        return None

    # Postflop exact enumeration is small: 990 turn/river combinations from a
    # flop, ~44 rivers from a turn, or one completed board.
    if len(community) >= 3:
        remaining = [c for c in FULL_DECK if c not in set(known)]
        needed = 5 - len(community)
        totals = [Fraction(0, 1) for _ in hole]
        n = 0

        for extra in combinations(remaining, needed):
            full_board = community + tuple(extra)

            if eval7 is not None:
                eboard = [eval7.Card(c) for c in full_board]
                ranks = [
                    eval7.evaluate([eval7.Card(c) for c in h] + eboard)
                    for h in hole
                ]
            else:
                ranks = [_river_rank(tuple(h) + full_board) for h in hole]

            best = max(ranks)
            winners = [i for i, r in enumerate(ranks) if r == best]
            share = Fraction(1, len(winners))
            for i in winners:
                totals[i] += share
            n += 1

        if not n:
            return None
        return [float(x / n) for x in totals]

    if len(community) == 0 and len(hole) >= 2:
        native = _native_heads_up_preflop(hole, dead)
        if native is not None:
            return native
        return _deterministic_board_monte_carlo(hole, community, dead)

    return None


def _rank_completed_hands(
    hands: Sequence[tuple[str, ...]],
    full_board: tuple[str, ...],
) -> list[object]:
    """Comparable ranks for concrete hands on a completed Hold'em board."""
    if eval7 is not None:
        eboard = [eval7.Card(c) for c in full_board]
        return [
            eval7.evaluate([eval7.Card(c) for c in h] + eboard)
            for h in hands
        ]
    return [_river_rank(tuple(h) + full_board) for h in hands]


def estimate_equities_with_unknown(
    hands: Sequence[str | Sequence[str] | None],
    board: str | Sequence[str],
    final_board: str | Sequence[str],
    observed_winners: set[int],
    dead_cards: str | Sequence[str] = (),
    iterations: int = UNKNOWN_HOLE_MC_ITERATIONS,
) -> list[float] | None:
    """Estimate equity when exactly one live player's hole cards are omitted.

    CoinPoker occasionally lets a live showdown player muck, so the exported HH
    lacks cards the server used for PokerIntel.  We infer a *range* for that one
    hidden hand from the completed board and the observed main-pot winner(s), then
    average Hero's all-in equity over compatible hidden hands.

    This function is deliberately left behaviorally the same as the existing
    tracker.  It is exposed as an estimate, not an exact replacement for
    CoinPoker's server-side hidden-card equity.
    """
    community = _normalize(board)
    completed = _normalize(final_board)
    dead = _normalize(dead_cards)

    if len(completed) != 5 or len(community) not in (0, 3, 4):
        return None

    normalized: list[tuple[str, ...] | None] = []
    unknown_idx: list[int] = []

    for i, h in enumerate(hands):
        if h is None:
            normalized.append(None)
            unknown_idx.append(i)
            continue

        nh = _normalize(h)
        if len(nh) != 2:
            normalized.append(None)
            unknown_idx.append(i)
        else:
            normalized.append(nh)

    if len(unknown_idx) != 1:
        return None

    ui = unknown_idx[0]
    known_hole = [c for h in normalized if h is not None for c in h]
    all_known = known_hole + list(completed) + list(dead)
    if len(set(all_known)) != len(all_known):
        return None

    # A hidden hole card cannot be one of the cards that was actually dealt to the
    # board. Conditioning on the observed winner further narrows the plausible
    # hidden range without pretending that we know the exact mucked hand.
    candidate_deck = [c for c in FULL_DECK if c not in set(all_known)]
    candidates: list[tuple[str, str]] = []

    for combo in combinations(candidate_deck, 2):
        concrete = list(normalized)
        concrete[ui] = tuple(combo)
        ranks = _rank_completed_hands(
            [h for h in concrete if h is not None],
            completed,
        )
        best = max(ranks)
        winners = {i for i, rank in enumerate(ranks) if rank == best}
        if winners == observed_winners:
            candidates.append(tuple(combo))

    if not candidates:
        return None

    needed = 5 - len(community)
    totals = [0.0 for _ in normalized]

    # With a flop or turn the complete posterior range is small enough to enumerate
    # every hidden-hand / remaining-board combination exactly.
    if len(community) >= 3:
        n = 0
        for cand in candidates:
            concrete = [
                cand if i == ui else h
                for i, h in enumerate(normalized)
            ]
            assert all(h is not None for h in concrete)

            used = (
                {c for h in concrete for c in h}
                | set(community)
                | set(dead)
            )
            remaining = [c for c in FULL_DECK if c not in used]

            for extra in combinations(remaining, needed):
                full_board = community + tuple(extra)
                ranks = _rank_completed_hands(
                    concrete,  # type: ignore[arg-type]
                    full_board,
                )
                best = max(ranks)
                winners = [
                    i for i, rank in enumerate(ranks)
                    if rank == best
                ]
                share = 1.0 / len(winners)
                for i in winners:
                    totals[i] += share
                n += 1

        return [x / n for x in totals] if n else None

    # Preflop unknown/mucked-card case: preserve the existing estimator exactly.
    seed_text = (
        "|".join(
            "??" if h is None else " ".join(h)
            for h in normalized
        )
        + "|board=" + " ".join(community)
        + "|final=" + " ".join(completed)
        + "|w=" + ",".join(map(str, sorted(observed_winners)))
        + f"|n={iterations}|unknown-v1"
    )
    seed = int.from_bytes(
        hashlib.sha256(seed_text.encode("ascii")).digest()[:8],
        "big",
    )
    rng = random.Random(seed)

    for _ in range(iterations):
        cand = candidates[rng.randrange(len(candidates))]
        concrete = [
            cand if i == ui else h
            for i, h in enumerate(normalized)
        ]
        assert all(h is not None for h in concrete)

        used = (
            {c for h in concrete for c in h}
            | set(community)
            | set(dead)
        )
        remaining = [c for c in FULL_DECK if c not in used]
        extra = tuple(rng.sample(remaining, needed))

        ranks = _rank_completed_hands(
            concrete,  # type: ignore[arg-type]
            community + extra,
        )
        best = max(ranks)
        winners = [
            i for i, rank in enumerate(ranks)
            if rank == best
        ]
        share = 1.0 / len(winners)
        for i in winners:
            totals[i] += share

    return [x / iterations for x in totals]
