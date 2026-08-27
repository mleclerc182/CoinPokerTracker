import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cointracker.ui import OVERVIEW_CARD_TITLES, OverviewCardsDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_overview_cards_dialog_preserves_order_and_hidden_state():
    _app()
    order = list(OVERVIEW_CARD_TITLES)
    order[0], order[1] = order[1], order[0]
    dialog = OverviewCardsDialog(order, {"Splash won"})

    saved_order, hidden = dialog.layout_state()
    assert saved_order == order
    assert hidden == {"Splash won"}


def test_overview_cards_dialog_drag_order_and_reset_defaults():
    _app()
    dialog = OverviewCardsDialog(list(OVERVIEW_CARD_TITLES), {"Net", "VPIP"})

    moved = dialog.list.takeItem(0)
    dialog.list.insertItem(4, moved)
    moved.setCheckState(Qt.Unchecked)
    order, hidden = dialog.layout_state()
    assert order[4] == OVERVIEW_CARD_TITLES[0]
    assert OVERVIEW_CARD_TITLES[0] in hidden

    dialog.reset_defaults()
    order, hidden = dialog.layout_state()
    assert order == list(OVERVIEW_CARD_TITLES)
    assert hidden == set()

from cointracker.ui import ProfitGraph


def test_profit_graph_builds_four_cumulative_series_and_toggles():
    _app()
    graph = ProfitGraph()
    graph.set_series_changes(
        net=[10, -4, 7],
        showdown=[10, 0, 7],
        allin_adj=[8.5, -2.0, 5.5],
        nonshowdown=[0, -4, 0],
    )

    assert graph.series["net"] == [0.0, 10.0, 6.0, 13.0]
    assert graph.series["showdown"] == [0.0, 10.0, 10.0, 17.0]
    assert graph.series["nonshowdown"] == [0.0, 0.0, -4.0, -4.0]
    assert graph.series["allin_adj"] == [0.0, 8.5, 6.5, 12.0]
    # Net is exactly the sum of showdown and non-showdown cumulative winnings.
    assert all(
        net == sd + ns
        for net, sd, ns in zip(
            graph.series["net"], graph.series["showdown"], graph.series["nonshowdown"]
        )
    )

    graph.set_series_visible("showdown", False)
    assert "showdown" not in graph.visible_series
    graph.set_series_visible("showdown", True)
    assert "showdown" in graph.visible_series


def test_profit_graph_axis_ticks_scale_to_data_range():
    # Money axis uses readable cent-denominated increments and expands to nice bounds.
    lo, hi, step = ProfitGraph._axis_bounds(-437.0, 892.0, 8)
    assert lo <= -437.0
    assert hi >= 892.0
    assert step >= 1.0
    assert 5 <= ((hi - lo) / step) <= 12

    # Hand ticks grow with the sample instead of hard-coding one interval.
    small = ProfitGraph._hand_tick_step(224, 10)
    medium = ProfitGraph._hand_tick_step(1295, 10)
    large = ProfitGraph._hand_tick_step(40000, 10)
    assert 1 <= small < medium < large
    assert 6 <= 224 / small <= 15
    assert 5 <= 40000 / large <= 15
