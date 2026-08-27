from cointracker.parser import parse_hand


def test_normal_hand_net_and_return():
    hh = """CoinPoker Hand #86911400263: NLH (₮0.01/₮0.02) 2026/07/11 08:51:04 EDT
Table '200588' 6-max Seat #4 is the button
Seat 1: a8cef862 (₮2 in chips)
Seat 3: 251065f6 (₮0.80 in chips)
Seat 4: f29764f0 (₮3.63 in chips)
Seat 5: 77d460fc (₮1.71 in chips)
Seat 6: Hero (₮2 in chips)
77d460fc: posts small blind ₮0.01
Hero: posts big blind ₮0.02
251065f6: posts auto big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [4s Jc]
Hero: checks
*** FLOP *** [Kc Js 7s]
Hero: checks
251065f6: checks
*** TURN *** [Kc Js 7s] [Ks]
Hero: checks
251065f6: checks
*** RIVER *** [Kc Js 7s Ks] [Jh]
Hero: bets ₮0.04
251065f6: folds
Hero: RETURN ₮0.04
*** SHOWDOWN ***
Hero collected ₮0.05 from pot
*** SUMMARY ***
Total pot ₮0.05 | Rake ₮0
Hand was run once
Board [ Kc Js 7s Ks Jh ]
Game ended: 2026/07/11 08:51:49 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.contributed_cents == 6
    assert h.hero_result.returned_cents == 4
    assert h.hero_result.collected_cents == 5
    assert h.hero_result.net_cents == 3
    assert h.run_count == 1
    assert h.boards == ["Kc Js 7s Ks Jh"]


def test_splash_side_pot_win_does_not_get_splash_main_pot(monkeypatch):
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda *a, **k: [0.25, 0.25, 0.25, 0.25])
    hh = """CoinPoker Hand #89668000357: NLH (₮0.01/₮0.02) 2026/07/15 09:54:17 EDT
Table '200588' 6-max Seat #3 is the button
Seat 1: Hero (₮2.89 in chips)
Seat 3: 45507089 (₮2 in chips)
Seat 4: 4e29a28c (₮2.21 in chips)
Seat 5: ae546cac (₮0.65 in chips)
Seat 6: 1238d296 (₮1.05 in chips)
MEGA SPLASH dropped ₮2
4e29a28c: posts small blind ₮0.01
ae546cac: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [6c Kh]
1238d296: ALLIN ₮1.05
Hero: ALLIN ₮2.89
45507089: ALLIN ₮2
4e29a28c: ALLIN ₮2.20
ae546cac: folds
Hero: RETURN ₮0.68
*** FLOP *** [Td 5d Ts]
*** TURN *** [Td 5d Ts] [Ks]
*** RIVER *** [Td 5d Ts Ks] [Ad]
*** SHOWDOWN ***
1238d296: shows [Ah 9c] (Two Pair)
1238d296 collected ₮0.99 from pot
Hero: shows [6c Kh] (Two Pair)
Hero collected ₮1.38 from pot
4e29a28c: shows [Kd 9h] (Two Pair)
4e29a28c collected ₮1.39 from pot
Hero: shows [6c Kh] (Two Pair)
Hero collected ₮0.20 from pot
4e29a28c: shows [Kd 9h] (Two Pair)
4e29a28c collected ₮0.21 from pot
45507089: shows [Qs Qh] (Two Pair)
*** SUMMARY ***
Total pot ₮9.49 | Rake ₮0.20
Hand was run once
Board [ Td 5d Ts Ks Ad ]
Game ended: 2026/07/15 09:55:16 EDT
"""
    h = parse_hand(hh)
    assert h.splash_type == "MEGA SPLASH"
    assert h.splash_cents == 200
    assert h.hero_result.splash_won_cents == 0
    assert h.hero_result.net_cents == -63


def test_splash_outright_main_pot_winner_adds_promotional_drop():
    hh = """CoinPoker Hand #119863400045: NLH (₮0.01/₮0.02) 2026/08/26 08:22:18 EDT
Table '200588' 6-max Seat #5 is the button
Seat 2: A (₮2.26 in chips)
Seat 3: B (₮2.37 in chips)
Seat 4: C (₮2.10 in chips)
Seat 5: Hero (₮2.05 in chips)
Seat 6: D (₮1.67 in chips)
SPLASH dropped ₮0.04
D: posts small blind ₮0.01
A: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [4s Ks]
B: folds
C: folds
Hero: raises ₮0.03 to ₮0.05
D: folds
A: folds
Hero: RETURN ₮0.03
*** SHOWDOWN ***
Hero collected ₮0.05 from pot
*** SUMMARY ***
Total pot ₮0.09 | Rake ₮0
Hand was run once
Board [  ]
Game ended: 2026/08/26 08:22:44 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.collected_cents == 5
    assert h.hero_result.splash_won_cents == 4
    assert h.hero_result.net_cents == 7


def test_splash_chop_splits_promotional_drop(monkeypatch):
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda *a, **k: [0.5, 0.5])
    hh = """CoinPoker Hand #88306100222: NLH (₮0.01/₮0.02) 2026/07/13 10:45:59 EDT
Table '200588' 6-max Seat #1 is the button
Seat 1: A (₮2 in chips)
Seat 2: Hero (₮2.01 in chips)
Seat 3: B (₮3.63 in chips)
Seat 6: Villain (₮2 in chips)
MEGA SPLASH dropped ₮2
Hero: posts small blind ₮0.01
B: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [6d 5h]
Villain: ALLIN ₮2
A: folds
Hero: ALLIN ₮2
B: folds
Hero: RETURN ₮0.01
*** FLOP *** [Ks 8d Kh]
*** TURN *** [Ks 8d Kh] [Kc]
*** RIVER *** [Ks 8d Kh Kc] [8c]
*** SHOWDOWN ***
Hero: shows [6d 5h] (Full House)
Hero collected ₮1.92 from pot
Villain: shows [Qs Ts] (Full House)
Villain collected ₮1.92 from pot
*** SUMMARY ***
Total pot ₮6.04 | Rake ₮0.20
Hand was run once
Board [ Ks 8d Kh Kc 8c ]
Game ended: 2026/07/13 10:46:57 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.splash_won_cents == 100
    assert h.hero_result.net_cents == 92


def test_splash_run_twice_awards_only_won_runout_share(monkeypatch):
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda *a, **k: [0.5, 0.5])
    hh = """CoinPoker Hand #999: NLH (₮0.01/₮0.02) 2026/08/27 07:00:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
SPLASH dropped ₮0.50
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
Total pot ₮4.50 | Rake ₮0.20
Hand was run two times
FIRST Board [ Ac 7d 2h 3s 4c ]
SECOND Board [ Kc 7h 2d 3c 4d ]
Game ended: 2026/08/27 07:00:30 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.splash_won_cents == 25


def test_run_twice_shared_flop():
    hh = """CoinPoker Hand #91895200274: NLH (₮0.01/₮0.02) 2026/07/18 10:46:02 EDT
Table '200588' 6-max Seat #1 is the button
Seat 1: a (₮2.32 in chips)
Seat 2: b (₮4.56 in chips)
Seat 5: Hero (₮3.67 in chips)
b: posts small blind ₮0.01
Hero: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [Qc 7h]
Hero: folds
*** FIRST FLOP *** [Ts Jc 8s]
b: checks
a: bets ₮0.29
b: ALLIN ₮4.28
a: ALLIN ₮1.75
b: RETURN ₮2.24
*** FIRST TURN *** [Ts Jc 8s] [7s]
*** FIRST RIVER *** [Ts Jc 8s 7s] [Td]
*** SECOND TURN *** [Ts Jc 8s] [3h]
*** SECOND RIVER *** [Ts Jc 8s 3h] [6c]
*** FIRST SHOWDOWN ***
a: shows [Ad Th] (Three Of A Kind)
a collected ₮2.23 from pot
*** SECOND SHOWDOWN ***
b: shows [Qs Qd] (One Pair)
b collected ₮2.23 from pot
*** SUMMARY ***
Total pot ₮4.66 | Rake ₮0.20
Hand was run two times
FIRST Board [ Ts Jc 8s 7s Td ]
SECOND Board [ Ts Jc 8s 3h 6c ]
Game ended: 2026/07/18 10:46:54 EDT
"""
    h = parse_hand(hh)
    assert h.run_count == 2
    assert h.boards == ["Ts Jc 8s 7s Td", "Ts Jc 8s 3h 6c"]


def test_straddle_forced_not_vpip():
    hh = """CoinPoker Hand #1: NLH (₮0.01/₮0.02) 2026/07/11 08:51:04 EDT
Table 'T' 6-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: A (₮2 in chips)
Seat 3: B (₮2 in chips)
A: posts small blind ₮0.01
B: posts big blind ₮0.02
Hero: STRADDLE ₮0.04
*** HOLE CARDS ***
Dealt to Hero [As Ks]
A: folds
B: folds
Hero: RETURN ₮0.02
*** SHOWDOWN ***
Hero collected ₮0.04 from pot
*** SUMMARY ***
Total pot ₮0.04 | Rake ₮0
Hand was run once
Board [  ]
Game ended: 2026/07/11 08:51:10 EDT
"""
    h=parse_hand(hh)
    assert h.hero_result.contributed_cents == 4
    assert not h.hero_result.vpip


def test_allin_adj_preflop_replaces_actual_with_exact_equity(monkeypatch):
    # Hero loses the real runout, but had 80% equity when the money went in.
    # 4.00 post-rake pot * 80% - 2.00 invested = +1.20 adjusted.
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda hands, board: [0.80, 0.20])
    hh = """CoinPoker Hand #4001: NLH (₮0.01/₮0.02) 2026/08/27 07:00:00 EDT
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
Game ended: 2026/08/27 07:00:30 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.net_cents == -200
    assert h.hero_result.allin_adjusted
    assert h.hero_result.allin_equity == 0.80
    assert h.hero_result.allin_adj_cents == 120.0


def test_allin_adj_includes_dead_money_side_layer(monkeypatch):
    # F raises to 2.00 before short V jams 1.00. Hero jams 2.00, F folds.
    # Main pot = 3.00 at 50% equity; the 2.00 Hero-vs-folded-player side pot
    # is deterministic. EV return 1.50 + 2.00 - 2.00 investment = +1.50.
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda hands, board: [0.50, 0.50])
    hh = """CoinPoker Hand #4002: NLH (₮0.01/₮0.02) 2026/08/27 07:01:00 EDT
Table 'T' 3-max Seat #1 is the button
Seat 1: F (₮2 in chips)
Seat 2: Hero (₮2 in chips)
Seat 3: Villain (₮1 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Ad]
F: raises ₮2 to ₮2
Villain: ALLIN ₮0.98
Hero: ALLIN ₮1.99
F: folds
*** FLOP *** [2c 7d 9h]
*** TURN *** [2c 7d 9h] [Js]
*** RIVER *** [2c 7d 9h Js] [Kc]
*** SHOWDOWN ***
Villain: shows [Ks Kd] (Three Of A Kind)
Villain collected ₮3 from pot
Hero collected ₮2 from pot
Hero: shows [As Ad] (One Pair)
*** SUMMARY ***
Total pot ₮5 | Rake ₮0
Hand was run once
Board [ 2c 7d 9h Js Kc ]
Game ended: 2026/08/27 07:01:30 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.net_cents == 0
    assert h.hero_result.allin_adjusted
    assert h.hero_result.allin_equity == 0.50
    assert h.hero_result.allin_adj_cents == 150.0


def test_allin_adj_uses_post_rake_pot(monkeypatch):
    # 4.00 gross, 0.20 rake -> 3.80 net pot. At 40% equity Hero's expected
    # return is 1.52; minus 2.00 invested = -0.48 adjusted.
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda hands, board: [0.40, 0.60])
    hh = """CoinPoker Hand #4003: NLH (₮0.01/₮0.02) 2026/08/27 07:02:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [Ah Kh]
Hero: ALLIN ₮1.99
Villain: ALLIN ₮1.98
*** FLOP *** [2c 7d 9h]
*** TURN *** [2c 7d 9h] [Js]
*** RIVER *** [2c 7d 9h Js] [Qc]
*** SHOWDOWN ***
Villain: shows [Qh Qd] (Three Of A Kind)
Villain collected ₮3.80 from pot
Hero: shows [Ah Kh] (High Card)
*** SUMMARY ***
Total pot ₮4 | Rake ₮0.20
Hand was run once
Board [ 2c 7d 9h Js Qc ]
Game ended: 2026/08/27 07:02:30 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.allin_adjusted
    assert abs(h.hero_result.allin_adj_cents - (-48.0)) < 1e-9


def test_earlier_allin_with_later_street_action_adjusts_only_locked_pot(monkeypatch):
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda *a, **k: [0.50, 0.25, 0.25])
    hh = """CoinPoker Hand #4004: NLH (₮0.01/₮0.02) 2026/08/27 07:03:00 EDT
Table 'T' 3-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Deep (₮2 in chips)
Seat 3: Short (₮1 in chips)
Deep: posts small blind ₮0.01
Short: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Ad]
Short: ALLIN ₮0.98
Hero: calls ₮1
Deep: calls ₮0.99
*** FLOP *** [2c 7d 9h]
Deep: checks
Hero: checks
*** TURN *** [2c 7d 9h] [Js]
Deep: checks
Hero: checks
*** RIVER *** [2c 7d 9h Js] [Kc]
Deep: checks
Hero: checks
*** SHOWDOWN ***
Hero: shows [As Ad] (One Pair)
Hero collected ₮3 from pot
Deep: shows [Qh Qd] (One Pair)
Short: shows [Ks Kd] (Three Of A Kind)
*** SUMMARY ***
Total pot ₮3 | Rake ₮0
Hand was run once
Board [ 2c 7d 9h Js Kc ]
Game ended: 2026/08/27 07:03:30 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.allin_adjusted
    # Main pot is 3.00 and Hero actually receives all 3.00.  At 50% equity the
    # locked-pot expected return is 1.50, so adjusted net is +0.50 after Hero's
    # 1.00 contribution; later checks do not invalidate the locked main pot.
    assert abs(h.hero_result.allin_adj_cents - 50.0) < 1e-9


def test_postflop_equity_fallback_is_exact_without_eval7(monkeypatch):
    # Compare the dependency-free equity enumerator against the parser's separate
    # 5-card-combination hand ranker for a known flop spot.
    import itertools
    import cointracker.equity as eqmod
    from cointracker.parser import _holdem_rank

    monkeypatch.setattr(eqmod, "eval7", None)
    hands = ["Ac Jc", "Qh Td"]
    board = "Jd Th 2c"
    got = eqmod.exact_equities(hands, board)
    assert got is not None

    known = set(" ".join(hands).split() + board.split())
    deck = [c for c in eqmod.FULL_DECK if c not in known]
    wins = [0.0, 0.0]
    total = 0
    for extra in itertools.combinations(deck, 2):
        b = board + " " + " ".join(extra)
        ranks = [_holdem_rank(h, b) for h in hands]
        best = max(ranks)
        winners = [i for i, rank in enumerate(ranks) if rank == best]
        for i in winners:
            wins[i] += 1 / len(winners)
        total += 1
    expected = [w / total for w in wins]
    assert abs(got[0] - expected[0]) < 1e-12
    assert abs(got[1] - expected[1]) < 1e-12
    assert abs(sum(got) - 1.0) < 1e-12


def test_allin_adj_rit_uses_sequential_remaining_deck(monkeypatch):
    # CoinPoker deals RIT boards from one remaining physical deck, so cards from
    # run 1 are dead when the equity share for run 2 is evaluated.
    calls = []
    def fake_equity(hands, board, dead_cards=()):
        calls.append(tuple(dead_cards))
        return [0.60, 0.40] if not dead_cards else [0.50, 0.50]
    monkeypatch.setattr("cointracker.parser.exact_equities", fake_equity)
    hh = """CoinPoker Hand #4005: NLH (₮0.01/₮0.02) 2026/08/27 07:04:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
SPLASH dropped ₮0.50
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Ks]
Hero: ALLIN ₮1.99
Villain: ALLIN ₮1.98
*** FIRST FLOP *** [2c 7d 9h]
*** FIRST TURN *** [2c 7d 9h] [Js]
*** FIRST RIVER *** [2c 7d 9h Js] [Qc]
*** SECOND FLOP *** [Ah 7c 4d]
*** SECOND TURN *** [Ah 7c 4d] [5s]
*** SECOND RIVER *** [Ah 7c 4d 5s] [6c]
*** FIRST SHOWDOWN ***
Villain: shows [Qh Qd] (Three Of A Kind)
Villain collected ₮1.90 from pot
Hero: shows [As Ks] (High Card)
*** SECOND SHOWDOWN ***
Villain: shows [Qh Qd] (One Pair)
Villain collected ₮1.90 from pot
Hero: shows [As Ks] (One Pair)
*** SUMMARY ***
Total pot ₮4.50 | Rake ₮0.20
Hand was run two times
FIRST Board [ 2c 7d 9h Js Qc ]
SECOND Board [ Ah 7c 4d 5s 6c ]
Game ended: 2026/08/27 07:04:30 EDT
"""
    h = parse_hand(hh)
    assert h.run_count == 2
    assert h.hero_result.allin_adjusted
    # Splash is excluded from EV. Player-funded net pot is 3.80; the two halves
    # use 60% then 50% equity, for average 55%: 3.80*.55 - 2.00 = +0.09.
    assert abs(h.hero_result.allin_adj_cents - 9.0) < 1e-9
    assert abs(h.hero_result.allin_equity - 0.55) < 1e-12
    assert len(calls) == 2
    assert calls[0] == ()
    assert calls[1]


def test_incomplete_heads_up_board_never_calls_eval7_complete_board_exact(monkeypatch):
    """Regression: preflop equity must use our reproducible board sampler."""
    import cointracker.equity as eqmod

    class PoisonEval7:
        @staticmethod
        def py_hand_vs_range_exact(*args, **kwargs):
            raise AssertionError("complete-board exact API must not be used preflop")

        @staticmethod
        def py_hand_vs_range_monte_carlo(*args, **kwargs):
            raise AssertionError("eval7's private Monte Carlo must not be used")

    monkeypatch.setattr(eqmod, "eval7", PoisonEval7)
    called = {}

    def fake_sampler(hands, board, dead_cards, iterations=eqmod.PREFLOP_MC_ITERATIONS):
        called["hands"] = hands
        called["board"] = board
        called["dead"] = dead_cards
        return [0.709, 0.291]

    monkeypatch.setattr(eqmod, "_deterministic_board_monte_carlo", fake_sampler)
    got = eqmod.exact_equities(["Ah Kh", "Kc Tc"], "")
    assert got == [0.709, 0.291]
    assert called["hands"] == [("Ah", "Kh"), ("Kc", "Tc")]
    assert called["board"] == ()
    assert called["dead"] == ()


def test_preflop_sampler_is_deterministic_without_eval7(monkeypatch):
    import cointracker.equity as eqmod

    monkeypatch.setattr(eqmod, "eval7", None)
    hands = [("Ah", "Kh"), ("Kc", "Tc")]
    a = eqmod._deterministic_board_monte_carlo(hands, (), (), iterations=20_000)
    b = eqmod._deterministic_board_monte_carlo(hands, (), (), iterations=20_000)
    assert a == b
    assert a is not None
    # Exact exhaustive equity is ~70.894%; the deterministic sample should be
    # comfortably close while remaining fast enough for a unit test.
    assert abs(a[0] - 0.7089442062) < 0.015
    assert abs(sum(a) - 1.0) < 1e-12

def test_postflop_exact_result_is_independent_of_eval7_presence(monkeypatch):
    import cointracker.equity as eqmod

    class PoisonEval7:
        @staticmethod
        def py_hand_vs_range_exact(*args, **kwargs):
            raise AssertionError("postflop exact enumeration should be internal")

        @staticmethod
        def py_hand_vs_range_monte_carlo(*args, **kwargs):
            raise AssertionError("postflop equity should not be Monte Carlo")

    monkeypatch.setattr(eqmod, "eval7", PoisonEval7)
    got = eqmod.exact_equities(["Ac Jc", "Qh Td"], "Jd Th 2c")
    assert got is not None
    assert abs(got[0] - 0.7919191919191919) < 1e-12
    assert abs(sum(got) - 1.0) < 1e-12


def test_coinpoker_aug26_rit_regression(monkeypatch):
    """RIT must use the equity before either runout is dealt."""
    first_eq = 0.708944206169
    second_eq = 0.686760724622
    def fake_equity(hands, board, dead_cards=()):
        assert board == ""
        return [second_eq, 1.0-second_eq] if dead_cards else [first_eq, 1.0-first_eq]
    monkeypatch.setattr("cointracker.parser.exact_equities", fake_equity)
    hh = """CoinPoker Hand #120203700191: NLH (₮0.01/₮0.02) 2026/08/26 19:19:45 EDT
Table '200588' 6-max Seat #1 is the button
Seat 1: A (₮2 in chips)
Seat 3: B (₮3.74 in chips)
Seat 4: C (₮0.11 in chips)
Seat 5: Hero (₮2 in chips)
Seat 6: Villain (₮1.30 in chips)
B: posts small blind ₮0.01
C: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [Ah Kh]
Hero: raises ₮0.03 to ₮0.05
Villain: raises ₮0.03 to ₮0.08
A: folds
B: folds
C: folds
Hero: ALLIN ₮1.95
Villain: ALLIN ₮1.22
Hero: RETURN ₮0.70
*** FIRST FLOP *** [9d 9s 4d]
*** FIRST TURN *** [9d 9s 4d] [Qh]
*** FIRST RIVER *** [9d 9s 4d Qh] [5s]
*** SECOND FLOP *** [Jh 8c 9h]
*** SECOND TURN *** [Jh 8c 9h] [Jd]
*** SECOND RIVER *** [Jh 8c 9h Jd] [5d]
*** FIRST SHOWDOWN ***
Hero: shows [Ah Kh] (One Pair)
Hero collected ₮1.24 from pot
Villain: shows [Kc Tc] (One Pair)
*** SECOND SHOWDOWN ***
Hero: shows [Ah Kh] (One Pair)
Hero collected ₮1.26 from pot
Villain: shows [Kc Tc] (One Pair)
*** SUMMARY ***
Total pot ₮2.63 | Rake ₮0.13
Hand was run two times
FIRST Board [ 9d 9s 4d Qh 5s ]
SECOND Board [ Jh 8c 9h Jd 5d ]
Game ended: 2026/08/26 19:20:31 EDT
"""
    h = parse_hand(hh)
    expected = 250.0 * ((first_eq + second_eq) / 2.0) - 130.0
    assert h.hero_result.allin_adjusted
    assert abs(h.hero_result.allin_adj_cents - expected) < 1e-9
    assert abs(h.hero_result.allin_adj_cents - expected) < 1e-6


def test_coinpoker_ev_includes_covering_call_of_opponent_allin(monkeypatch):
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda *a, **k: [0.5, 0.5])
    hh = """CoinPoker Hand #5001: NLH (₮0.01/₮0.02) 2026/08/27 08:00:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮3 in chips)
Seat 2: Villain (₮1 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Ks]
Hero: raises ₮0.05 to ₮0.06
Villain: ALLIN ₮0.98
Hero: calls ₮0.94
*** FLOP *** [2c 3d 4h]
*** TURN *** [2c 3d 4h] [5s]
*** RIVER *** [2c 3d 4h 5s] [9c]
*** SHOWDOWN ***
Hero: shows [As Ks] (Straight)
Hero collected ₮1.90 from pot
Villain: shows [Qh Qd] (One Pair)
*** SUMMARY ***
Total pot ₮2.00 | Rake ₮0.10
Hand was run once
Board [ 2c 3d 4h 5s 9c ]
Game ended: 2026/08/27 08:00:20 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.allin_adjusted
    # Player-funded pot after rake is 1.90. At 50% equity Hero expects 0.95
    # after investing 1.00, so adjusted net is -0.05.
    assert abs(h.hero_result.allin_adj_cents - (-5.0)) < 1e-9


def test_coinpoker_ev_excludes_river_allins(monkeypatch):
    monkeypatch.setattr("cointracker.parser.exact_equities", lambda *a, **k: [0.5, 0.5])
    hh = """CoinPoker Hand #5002: NLH (₮0.01/₮0.02) 2026/08/27 08:01:00 EDT
Table 'T' 2-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Villain (₮2 in chips)
Hero: posts small blind ₮0.01
Villain: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [As Ks]
Hero: calls ₮0.01
Villain: checks
*** FLOP *** [2c 3d 4h]
Hero: checks
Villain: checks
*** TURN *** [2c 3d 4h] [5s]
Hero: checks
Villain: checks
*** RIVER *** [2c 3d 4h 5s] [9c]
Hero: ALLIN ₮1.98
Villain: ALLIN ₮1.98
*** SHOWDOWN ***
Hero: shows [As Ks] (Straight)
Hero collected ₮3.80 from pot
Villain: shows [Qh Qd] (One Pair)
*** SUMMARY ***
Total pot ₮4.00 | Rake ₮0.20
Hand was run once
Board [ 2c 3d 4h 5s 9c ]
Game ended: 2026/08/27 08:01:20 EDT
"""
    h = parse_hand(hh)
    assert not h.hero_result.allin_adjusted
    assert h.hero_result.allin_adj_cents == h.hero_result.net_cents


def test_locked_main_pot_with_mucked_live_hand_is_marked_estimated(monkeypatch):
    monkeypatch.setattr(
        "cointracker.parser.estimate_equities_with_unknown",
        lambda *a, **k: [0.40, 0.30, 0.30],
    )
    hh = """CoinPoker Hand #6001: NLH (₮0.01/₮0.02) 2026/08/23 20:40:56 EDT
Table 'T' 3-max Seat #1 is the button
Seat 1: Hero (₮2 in chips)
Seat 2: Deep (₮2 in chips)
Seat 3: Short (₮0.25 in chips)
Deep: posts small blind ₮0.01
Short: posts big blind ₮0.02
*** HOLE CARDS ***
Dealt to Hero [8s 8d]
Hero: raises ₮0.05 to ₮0.05
Deep: calls ₮0.04
Short: ALLIN ₮0.23
Hero: calls ₮0.20
Deep: calls ₮0.20
*** FLOP *** [2c 3s 7s]
Deep: checks
Hero: checks
*** TURN *** [2c 3s 7s] [2h]
Deep: checks
Hero: checks
*** RIVER *** [2c 3s 7s 2h] [2s]
Deep: checks
Hero: checks
*** SHOWDOWN ***
Hero: shows [8s 8d] (Full House)
Hero collected ₮0.75 from pot
Short: shows [As Kc] (Three Of A Kind)
Deep: mucks hand
*** SUMMARY ***
Total pot ₮0.75 | Rake ₮0
Hand was run once
Board [ 2c 3s 7s 2h 2s ]
Game ended: 2026/08/23 20:41:20 EDT
"""
    h = parse_hand(hh)
    assert h.hero_result.allin_adjusted
    assert h.hero_result.allin_estimated
    assert abs(h.hero_result.allin_equity - 0.40) < 1e-12
    # Actual net is +0.50. Replacing the 0.75 locked main-pot return with
    # 40% equity (0.30) yields adjusted net +0.05.
    assert abs(h.hero_result.allin_adj_cents - 5.0) < 1e-9
