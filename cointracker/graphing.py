from __future__ import annotations

import math


def nice_step(span: float, target_ticks: int) -> float:
    """Return a readable 1/2/2.5/5/10 × 10^n interval."""
    if span <= 0 or target_ticks <= 0:
        return 1.0
    raw = span / target_ticks
    exponent = math.floor(math.log10(raw))
    magnitude = 10 ** exponent
    fraction = raw / magnitude
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 2.5:
        nice = 2.5
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * magnitude


def money_axis_bounds(lo: float, hi: float, target_ticks: int = 8) -> tuple[float, float, float]:
    """Expand cent values to readable right-axis bounds and a cent-denominated tick step."""
    if lo == hi:
        pad = max(1.0, abs(lo) * 0.1)
        lo -= pad
        hi += pad
    step = max(1.0, nice_step(hi - lo, target_ticks))
    axis_lo = math.floor(lo / step) * step
    axis_hi = math.ceil(hi / step) * step
    if axis_lo == axis_hi:
        axis_hi = axis_lo + step
    return axis_lo, axis_hi, step


def hand_tick_step(hands: int, target_ticks: int = 10) -> int:
    if hands <= 0:
        return 1
    return max(1, int(round(nice_step(float(hands), target_ticks))))


def hand_ticks(hands: int, target_ticks: int = 10) -> list[int]:
    """Return adaptive hand-count ticks, always including 0 and the final hand."""
    if hands <= 0:
        return [0]
    step = hand_tick_step(hands, target_ticks)
    ticks = list(range(0, hands + 1, step)) or [0]
    if ticks[-1] != hands:
        if len(ticks) > 1 and hands - ticks[-1] < step * 0.45:
            ticks[-1] = hands
        else:
            ticks.append(hands)
    return ticks
