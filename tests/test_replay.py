from cointracker.database import TrackerDB
from cointracker.parser import parse_hand
from cointracker.replay import build_replay, format_chips


FOLD_HAND_TEXT = """CoinPoker Hand #123456789: NLH (₮0.01/₮0.02) 2026/08/27 07:00:00 EDT
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
"""


def test_replay_tracks_deal_actions_chips_and_final_result():
    hand = parse_hand(FOLD_HAND_TEXT)

    replay = build_replay(hand)

    assert replay.frames[0].action_text == "Ready to replay"
    assert "Hero" not in replay.frames[0].cards

    dealt = next(frame for frame in replay.frames if "is dealt" in frame.action_text)
    assert dealt.cards["Hero"] == "As Kd"

    raised = next(frame for frame in replay.frames if ": raises " in frame.action_text)
    assert raised.pot_cents == 8
    assert raised.stacks["Hero"] == 194
    assert raised.street_bets["Hero"] == 6

    folded = next(frame for frame in replay.frames if frame.action_text == "Villain: folds")
    assert "Villain" in folded.folded

    final = replay.frames[-1]
    assert final.complete
    assert final.pot_cents == 0
    assert final.stacks == {"Hero": 202, "Villain": 198}
    assert final.action_text == "Hand complete · Hero won ₮0.02"
    assert format_chips(-5) == "-₮0.05"


def test_database_replay_uses_the_stored_hero_name(tmp_path):
    source = parse_hand(
        FOLD_HAND_TEXT.replace("Hero", "Alice"),
        hero_name="Alice",
    )
    db = TrackerDB(tmp_path / "tracker.sqlite3")
    try:
        assert db.import_hands([source]) == (1, 0)
        loaded = db.replay_hand(source.hand_id)
        assert loaded is not None
        assert loaded.hero_name == "Alice"
        assert loaded.hero_cards == "As Kd"
    finally:
        db.close()


def test_replay_rotates_hero_to_the_first_visual_seat_and_exposes_splash():
    hand = parse_hand(
        FOLD_HAND_TEXT
        .replace("Seat 1: Hero", "Seat 1: Villain")
        .replace("Seat 2: Villain", "Seat 2: Hero")
        .replace(
            "Hero: posts small blind",
            "SPLASH dropped ₮0.50\nHero: posts small blind",
        )
    )

    replay = build_replay(hand)

    assert replay.seats[0].player == "Hero"
    assert replay.seats[1].player == "Villain"
    assert replay.splash_type == "SPLASH"
    assert replay.splash_cents == 50


def test_replay_preserves_each_multi_run_board_street(monkeypatch):
    monkeypatch.setattr(
        "cointracker.parser.exact_equities",
        lambda *args, **kwargs: [0.5, 0.5],
    )
    hand = parse_hand(
        """CoinPoker Hand #999: NLH (₮0.01/₮0.02) 2026/08/27 07:00:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Ad]
Hero: ALLIN ₮1.99
Villain: ALLIN ₮1.98
*** FIRST FLOP *** [Ac 7d 2h]
*** FIRST TURN *** [Ac 7d 2h] [3s]
*** FIRST RIVER *** [Ac 7d 2h 3s] [4c]
*** SECOND FLOP *** [Kc 7h 2d]
*** SECOND TURN *** [Kc 7h 2d] [3c]
*** SECOND RIVER *** [Kc 7h 2d 3c] [4d]
*** FIRST SHOWDOWN ***
Hero: shows [As Ad] (Three Of A Kind)
Hero collected ₮1.90 from pot
Villain: shows [Ks Kd] (One Pair)
*** SECOND SHOWDOWN ***
Villain: shows [Ks Kd] (Three Of A Kind)
Villain collected ₮1.90 from pot
Hero: shows [As Ad] (One Pair)
*** SUMMARY ***
Total pot ₮4 | Rake ₮0.20
Hand was run two times
FIRST Board [ Ac 7d 2h 3s 4c ]
SECOND Board [ Kc 7h 2d 3c 4d ]
Game ended: 2026/08/27 07:00:30 EDT
"""
    )

    replay = build_replay(hand)
    board_frames = [
        frame
        for frame in replay.frames
        if frame.action_text.endswith("dealt")
    ]

    assert [frame.action_text for frame in board_frames] == [
        "Run 1 Flop dealt",
        "Run 1 Turn dealt",
        "Run 1 River dealt",
        "Run 2 Flop dealt",
        "Run 2 Turn dealt",
        "Run 2 River dealt",
    ]
    assert board_frames[2].boards[0] == "Ac 7d 2h 3s 4c"
    assert board_frames[-1].boards == (
        "Ac 7d 2h 3s 4c",
        "Kc 7h 2d 3c 4d",
    )
    assert any(frame.action_text == "Run 2 showdown" for frame in replay.frames)
