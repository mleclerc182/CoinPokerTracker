import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGridLayout

from app import STARTUP_PROGRESS_DELAY_MS, create_migration_progress
from cointracker.database import TrackerDB
from cointracker.parser import parse_hand
from cointracker.ui import MainWindow, OVERVIEW_CARD_TITLES, OverviewCardsDialog


def _app():
    return QApplication.instance() or QApplication([])


def test_quick_startup_does_not_flash_migration_progress():
    app = _app()
    dialog, update = create_migration_progress(app)
    try:
        update(0, 10)
        app.processEvents()

        assert dialog.minimumDuration() == STARTUP_PROGRESS_DELAY_MS
        assert not dialog.isVisible()
    finally:
        dialog.close()


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


def _session_hand(hand_id: str, minute: int):
    return parse_hand(
        f"""CoinPoker Hand #{hand_id}: NLH (₮0.01/₮0.02) 2026/08/27 07:{minute:02d}:00 EDT
Table 'T' 2-max Seat #1 is the button
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
Game ended: 2026/08/27 07:{minute:02d}:10 EDT
"""
    )


def test_clicking_session_populates_its_hand_table(tmp_path):
    app = _app()
    path = tmp_path / "tracker.sqlite3"
    db = TrackerDB(path)
    try:
        assert db.import_hands(
            [
                _session_hand("990001", 0),
                _session_hand("990002", 10),
            ]
        ) == (2, 0)
    finally:
        db.close()

    window = MainWindow(str(path))
    try:
        assert window.session_table.rowCount() == 1
        assert window.session_hand_table.rowCount() == 0
        assert window.hand_table.horizontalHeaderItem(10).text() == (
            "Hero Contrib (BB)"
        )
        assert window.hand_table.item(0, 10).text() == "1.00"

        window.session_table.cellClicked.emit(0, 0)
        app.processEvents()

        assert window.session_hand_table.rowCount() == 2
        assert window.session_hand_table.item(0, 1).text() == "990002"
        assert window.session_hand_table.item(1, 1).text() == "990001"
        assert window.session_hand_table.item(0, 10).text() == "1.00"
    finally:
        window.close()


def test_file_menu_groups_import_and_overview_actions(tmp_path):
    _app()
    window = MainWindow(str(tmp_path / "tracker.sqlite3"))
    try:
        top_level = window.menuBar().actions()
        assert [action.text() for action in top_level] == [
            "File",
            "Filters",
        ]

        file_actions = top_level[0].menu().actions()
        assert file_actions[0].text() == "Import"
        assert file_actions[1].isSeparator()
        assert file_actions[2].text() == "Add/Edit Rakeback…"
        assert file_actions[3].text() == "Customize Overview cards…"

        import_actions = file_actions[0].menu().actions()
        assert [action.text() for action in import_actions] == [
            "Hand-history file…",
            "Folder…",
        ]
        assert not hasattr(window, "rakeback_button")
        assert not hasattr(window, "customize_cards_button")

        filter_actions = top_level[1].menu().actions()
        assert [action.text() for action in filter_actions] == [
            "Edit filters…",
            "Clear all filters",
        ]
        assert isinstance(window.filters.layout(), QGridLayout)
        filter_rows = {
            window.filters.layout().getItemPosition(
                window.filters.layout().indexOf(control)
            )[0]
            for control in (
                window.filters.date_from,
                window.filters.date_to,
                window.filters.stakes,
                window.filters.splash,
                window.filters.runs,
                window.filters.bb_contributed_min,
                window.filters.bb_contributed_max,
            )
        }
        assert len(filter_rows) == 7
        assert window.filters_dialog.minimumWidth() == 520
        assert window.filter_summary_label.text() == "Filters: All hands"
        assert not window.clear_filters_action.isEnabled()

        window.filters.splash.setCurrentIndex(1)
        assert window.filter_summary_label.text() == "Filters: Splash only"
        assert window.clear_filters_action.isEnabled()

        window.clear_filters_action.trigger()
        assert window.filter_summary_label.text() == "Filters: All hands"
        assert window.filters.filters() == {
            "splash": "all",
            "runs": "all",
        }

        window.filters.bb_contributed_min.setText("1.5")
        window.filters.bb_contributed_max.setText("12")
        assert window.filter_summary_label.text() == (
            "Filters: Contributed 1.5–12 BB"
        )
        assert window.filters.filters() == {
            "splash": "all",
            "runs": "all",
            "contributed_bb_min": 1.5,
            "contributed_bb_max": 12.0,
        }

        window.clear_filters_action.trigger()
        assert window.filters.bb_contributed_min.text() == ""
        assert window.filters.bb_contributed_max.text() == ""
        assert window.filter_summary_label.text() == "Filters: All hands"
    finally:
        window.close()
