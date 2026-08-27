from __future__ import annotations

import re

# Four-colour deck convention: easy to scan while preserving conventional suit identity.
SUIT_SYMBOLS = {
    "h": "♥",
    "d": "♦",
    "c": "♣",
    "s": "♠",
}

SUIT_COLORS = {
    "h": "#ff667d",  # hearts — red/pink
    "d": "#55b7ff",  # diamonds — blue
    "c": "#45d483",  # clubs — green
    "s": "#e6edf7",  # spades — light neutral
}

RANK_VALUES = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "T": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}

_CARD_RE = re.compile(r"(?<![A-Za-z0-9])([2-9TJQKA])([cdhs])(?![A-Za-z0-9])", re.IGNORECASE)


def card_text_segments(text: str) -> list[tuple[str, str | None]]:
    """Convert CoinPoker card tokens to display segments.

    The returned strings preserve all spacing/separators while card tokens such
    as ``Ah`` become ``A♥`` with the matching suit colour.  A ``None`` colour
    means the caller should use its normal table foreground colour.
    """
    value = text or ""
    out: list[tuple[str, str | None]] = []
    cursor = 0
    for match in _CARD_RE.finditer(value):
        if match.start() > cursor:
            out.append((value[cursor:match.start()], None))
        rank = match.group(1).upper()
        suit = match.group(2).lower()
        out.append((rank + SUIT_SYMBOLS[suit], SUIT_COLORS[suit]))
        cursor = match.end()
    if cursor < len(value):
        out.append((value[cursor:], None))
    if not out and value:
        out.append((value, None))
    return out


def _hole_card_tokens(text: str) -> list[tuple[str, str]]:
    """Return up to two CoinPoker hole-card tokens as normalized rank/suit pairs."""
    cards: list[tuple[str, str]] = []
    for match in _CARD_RE.finditer(text or ""):
        cards.append((match.group(1).upper(), match.group(2).lower()))
        if len(cards) == 2:
            break
    return cards


def normalize_hole_cards(text: str) -> str:
    """Put the higher-ranked hole card first for display.

    CoinPoker can export hole cards in either deal order.  The Hands tab uses a
    canonical poker order instead: ``2c Ad`` becomes ``Ad 2c``.  Equal-rank
    pairs retain a deterministic suit order so the display does not jump around.
    Non-standard/missing values are returned unchanged.
    """
    cards = _hole_card_tokens(text)
    if len(cards) != 2:
        return text or ""

    # Rank is the meaningful ordering.  Suit only provides deterministic order
    # for pairs; it has no impact on the poker rank sort itself.
    suit_order = {"s": 4, "h": 3, "d": 2, "c": 1}
    cards.sort(key=lambda c: (RANK_VALUES[c[0]], suit_order[c[1]]), reverse=True)
    return " ".join(rank + suit for rank, suit in cards)


def hole_card_sort_key(text: str) -> tuple:
    """Typed sort key for the Hands-tab Cards column.

    Descending sort produces the requested canonical sequence by rank:
    ``AA, AK, AQ, AJ, ... KQ, KJ, ... 22``.  All physical suit combinations of
    the same two ranks stay together; suitedness/suits are only stable
    tie-breakers after the rank pair.
    """
    cards = _hole_card_tokens(text)
    if len(cards) != 2:
        return (-1, -1, -1, "")

    ranks = sorted((RANK_VALUES[cards[0][0]], RANK_VALUES[cards[1][0]]), reverse=True)
    suited = int(cards[0][1] == cards[1][1])
    canonical = normalize_hole_cards(text).casefold()
    return (ranks[0], ranks[1], suited, canonical)
