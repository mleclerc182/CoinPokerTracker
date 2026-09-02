from cointracker.handtable import SUIT_COLORS, card_text_segments


def test_card_text_segments_uses_four_colour_suit_symbols():
    segments = card_text_segments("Ah Ks 7d 2c")
    assert segments == [
        ("A♥", SUIT_COLORS["h"]),
        (" ", None),
        ("K♠", SUIT_COLORS["s"]),
        (" ", None),
        ("7♦", SUIT_COLORS["d"]),
        (" ", None),
        ("2♣", SUIT_COLORS["c"]),
    ]


def test_card_text_segments_preserves_runout_separators():
    segments = card_text_segments("Jd Th 2c | 9s 9h")
    rendered = "".join(text for text, _ in segments)
    assert rendered == "J♦ T♥ 2♣ | 9♠ 9♥"
    assert sum(1 for _, color in segments if color) == 5


def test_card_text_segments_leaves_non_card_text_alone():
    assert card_text_segments("No board") == [("No board", None)]


def test_normalize_hole_cards_puts_high_rank_first():
    from cointracker.handtable import normalize_hole_cards

    assert normalize_hole_cards("2c Ad") == "Ad 2c"
    assert normalize_hole_cards("Qh As") == "As Qh"
    assert normalize_hole_cards("Kh Qd") == "Kh Qd"


def test_hole_card_sort_key_descending_uses_poker_rank_order():
    from cointracker.handtable import hole_card_sort_key

    hands = ["2c 2d", "Qh Kc", "Js Ah", "Qd As", "Kd Ac", "Ah Ad", "Kh Ks"]
    ordered = sorted(hands, key=hole_card_sort_key, reverse=True)
    assert ordered == ["Ah Ad", "Kd Ac", "Qd As", "Js Ah", "Kh Ks", "Qh Kc", "2c 2d"]


def test_hole_card_sort_groups_same_rank_combo_before_suit_tiebreakers():
    from cointracker.handtable import hole_card_sort_key

    aq = ["Ac Qc", "Ah Qd", "Qs Ad"]
    keys = [hole_card_sort_key(hand)[:2] for hand in aq]
    assert keys == [(14, 12), (14, 12), (14, 12)]
