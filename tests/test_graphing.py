from cointracker.graphing import hand_tick_step, hand_ticks, money_axis_bounds, nice_step


def test_nice_step_uses_readable_intervals():
    assert nice_step(224, 10) == 25
    assert nice_step(1295, 10) == 200
    assert nice_step(40000, 10) == 5000


def test_money_axis_bounds_add_multiple_readable_ticks():
    lo, hi, step = money_axis_bounds(-437.0, 892.0, 8)
    assert lo <= -437.0
    assert hi >= 892.0
    assert step >= 1.0
    assert 5 <= ((hi - lo) / step) <= 12


def test_hand_ticks_scale_and_include_final_hand_without_near_duplicate():
    small = hand_ticks(224, 10)
    medium = hand_ticks(1295, 10)
    large = hand_ticks(40001, 10)
    assert small[0] == medium[0] == large[0] == 0
    assert small[-1] == 224
    assert medium[-1] == 1295
    assert large[-1] == 40001
    assert 7 <= len(small) <= 13
    assert 6 <= len(medium) <= 13
    assert 6 <= len(large) <= 13
    assert large[-1] - large[-2] >= hand_tick_step(40001, 10) * 0.45
