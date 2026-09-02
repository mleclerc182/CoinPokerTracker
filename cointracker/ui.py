from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QDate, QSettings, Qt, Signal, QThread
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCalendarWidget, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSplitter, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget
)

from .database import TrackerDB
from .equity import evaluator_available
from .importer import import_file, import_folder
from .graphing import hand_tick_step, hand_ticks, money_axis_bounds, nice_step
from .handtable import card_text_segments, hole_card_sort_key, normalize_hole_cards


OVERVIEW_CARD_TITLES = [
    "Hands", "Net", "Splash won", "bb/100", "All-in Adj Net Won",
    "All-in Adj BB", "Adj bb/100", "AI adj hands", "VPIP", "PFR", "3-Bet",
    "WWSF", "WTSD", "W$SD", "Splash hands", "RIT hands",
]

CARD_ACCENTS = {
    "Hands": "#8b5cf6",
    "Net": "#22c55e",
    "Splash won": "#f59e0b",
    "bb/100": "#10b981",
    "All-in Adj Net Won": "#eab308",
    "All-in Adj BB": "#facc15",
    "Adj bb/100": "#fde047",
    "AI adj hands": "#fb923c",
    "VPIP": "#38bdf8",
    "PFR": "#60a5fa",
    "3-Bet": "#818cf8",
    "WWSF": "#2dd4bf",
    "WTSD": "#c084fc",
    "W$SD": "#f472b6",
    "Splash hands": "#fb7185",
    "RIT hands": "#a78bfa",
}


def fmt_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}₮{cents / 100:.2f}"


def fmt_pct(x: float) -> str:
    return f"{x:.1f}%"


class StatCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        accent = CARD_ACCENTS.get(title, "#38bdf8")
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("statCard")
        self.setMinimumHeight(88)
        self.setStyleSheet(
            f"""
            QFrame#statCard {{
                background-color: #131d33;
                border: 1px solid #263552;
                border-top: 3px solid {accent};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; border: none; }}
            """
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 11)
        lay.setSpacing(3)
        self.title = QLabel(title)
        self.title.setStyleSheet(f"color: {accent}; font-weight: 700;")
        if title == "WWSF":
            self.setToolTip("Won When Saw Flop: percentage of flops seen where Hero won at least part of the pot.")
        self.value = QLabel("—")
        self.value.setStyleSheet("color: #f8fbff;")
        f = self.value.font()
        f.setPointSize(f.pointSize() + 7)
        f.setBold(True)
        self.value.setFont(f)
        lay.addWidget(self.title)
        lay.addWidget(self.value)


class OverviewCardsDialog(QDialog):
    """Reorder and show/hide Overview stat cards.

    Reordering happens in one list so it remains keyboard-accessible while also
    supporting drag-and-drop. Checked items are visible; unchecked items are
    retained in the order but hidden from the Overview grid.
    """

    def __init__(self, order: list[str], hidden: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Overview cards")
        self.resize(430, 560)

        lay = QVBoxLayout(self)
        help_text = QLabel(
            "Drag cards to change their order. Uncheck a card to hide it. "
            "Your layout is saved automatically when you press OK."
        )
        help_text.setWordWrap(True)
        lay.addWidget(help_text)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        # This list is a pure reorder control.  Explicitly disable overwrite
        # semantics and let the list/viewport accept drops between rows.
        # Individual cards must not be drop targets; dropping *on* a card can
        # otherwise make Qt treat the destination row as replaceable.
        self.list.setDragDropOverwriteMode(False)
        self.list.viewport().setAcceptDrops(True)
        self.list.setDropIndicatorShown(True)
        lay.addWidget(self.list, 1)

        reset = QPushButton("Reset to default layout")
        reset.clicked.connect(self.reset_defaults)
        lay.addWidget(reset)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._populate(order, hidden)

    def _populate(self, order: list[str], hidden: set[str]):
        self.list.clear()
        for title in order:
            item = QListWidgetItem(title)
            item.setFlags(
                (
                    item.flags()
                    | Qt.ItemIsUserCheckable
                    | Qt.ItemIsDragEnabled
                )
                & ~Qt.ItemIsDropEnabled
            )
            item.setCheckState(Qt.Unchecked if title in hidden else Qt.Checked)
            self.list.addItem(item)

    def reset_defaults(self):
        self._populate(list(OVERVIEW_CARD_TITLES), set())

    def layout_state(self) -> tuple[list[str], set[str]]:
        # Sanitize before saving so a malformed drag/drop can never persist a
        # missing or duplicate card into QSettings.
        known = set(OVERVIEW_CARD_TITLES)
        order = []
        hidden = set()
        for row in range(self.list.count()):
            item = self.list.item(row)
            title = item.text()
            if title not in known or title in order:
                continue
            order.append(title)
            if item.checkState() != Qt.Checked:
                hidden.add(title)

        for title in OVERVIEW_CARD_TITLES:
            if title not in order:
                order.append(title)

        return order, hidden


class ProfitGraph(QWidget):
    SERIES_COLORS = {
        "showdown": QColor("#3498db"),
        "allin_adj": QColor("#f1c40f"),
        "nonshowdown": QColor("#e74c3c"),
        "net": QColor("#2ecc71"),
    }

    def __init__(self):
        super().__init__()
        self.series: dict[str, list[float]] = {
            "showdown": [0.0],
            "allin_adj": [0.0],
            "nonshowdown": [0.0],
            "net": [0.0],
        }
        self.visible_series = set(self.series)
        self.setMinimumHeight(260)

    @staticmethod
    def _cumulative(changes: list[float]) -> list[float]:
        total = 0.0
        points = [0.0]
        for change in changes:
            total += float(change)
            points.append(total)
        return points

    def set_series_changes(
        self,
        *,
        net: list[float],
        showdown: list[float],
        allin_adj: list[float],
        nonshowdown: list[float],
    ):
        self.series = {
            "showdown": self._cumulative(showdown),
            "allin_adj": self._cumulative(allin_adj),
            "nonshowdown": self._cumulative(nonshowdown),
            "net": self._cumulative(net),
        }
        self.update()

    def set_series_visible(self, key: str, visible: bool):
        if visible:
            self.visible_series.add(key)
        else:
            self.visible_series.discard(key)
        self.update()

    @staticmethod
    def _nice_step(span: float, target_ticks: int) -> float:
        return nice_step(span, target_ticks)

    @staticmethod
    def _axis_bounds(lo: float, hi: float, target_ticks: int = 8) -> tuple[float, float, float]:
        return money_axis_bounds(lo, hi, target_ticks)

    @staticmethod
    def _hand_tick_step(hands: int, target_ticks: int = 10) -> int:
        return hand_tick_step(hands, target_ticks)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0d1627"))

        # Money labels live on the right. Keep enough room for values such as
        # -₮123.45 while leaving the left edge visually clean.
        rect = self.rect().adjusted(12, 15, -86, -38)

        available = [
            (key, points) for key, points in self.series.items()
            if key in self.visible_series and len(points) >= 2
        ]
        if not available:
            p.setPen(self.palette().text().color())
            if any(len(points) >= 2 for points in self.series.values()):
                p.drawText(rect, Qt.AlignCenter, "Select a graph line to display")
            else:
                p.drawText(rect, Qt.AlignCenter, "Import hands to see the profit graph")
            return

        values = [value for _, points in available for value in points]
        axis_lo, axis_hi, y_step = self._axis_bounds(min(values), max(values), 8)
        axis_span = axis_hi - axis_lo
        hands = max(len(points) for _, points in available) - 1

        # Horizontal grid + right-side money labels. These are deliberately
        # denser than v0.16, but use nice intervals so they remain readable.
        grid_pen = QPen(QColor("#273754"))
        grid_pen.setStyle(Qt.DotLine)
        text_pen = QPen(QColor("#b8c7e0"))
        tick_len = 5
        y = axis_lo
        # The +0.5 step tolerance avoids losing the top tick to float error.
        while y <= axis_hi + y_step * 0.5:
            py = rect.bottom() - ((y - axis_lo) / axis_span) * rect.height()
            p.setPen(grid_pen)
            p.drawLine(rect.left(), int(py), rect.right(), int(py))
            p.setPen(text_pen)
            p.drawLine(rect.right(), int(py), rect.right() + tick_len, int(py))
            label = fmt_money(int(round(y)))
            label_rect = self.rect().adjusted(rect.right() + 8, int(py) - 10, -2, 0)
            label_rect.setHeight(20)
            p.drawText(label_rect, Qt.AlignLeft | Qt.AlignVCenter, label)
            y += y_step

        # Vertical grid + adaptive hand-count pips. Always include the final
        # hand count even when it is not a clean multiple of the nice step.
        x_ticks = hand_ticks(hands, 10)
        for hand_no in x_ticks:
            px = rect.left() + (hand_no / max(1, hands)) * rect.width()
            p.setPen(grid_pen)
            p.drawLine(int(px), rect.top(), int(px), rect.bottom())
            p.setPen(text_pen)
            p.drawLine(int(px), rect.bottom(), int(px), rect.bottom() + tick_len)
            label = f"{hand_no:,}"
            fm = p.fontMetrics()
            width = fm.horizontalAdvance(label) + 8
            label_rect = self.rect().adjusted(int(px) - width // 2, rect.bottom() + 8, 0, -2)
            label_rect.setWidth(width)
            label_rect.setHeight(20)
            # Keep the first/last labels inside the widget.
            if label_rect.left() < rect.left():
                label_rect.moveLeft(rect.left())
            if label_rect.right() > rect.right():
                label_rect.moveRight(rect.right())
            p.drawText(label_rect, Qt.AlignHCenter | Qt.AlignTop, label)

        # Main plot border is drawn after the grid so it remains crisp.
        p.setPen(text_pen)
        p.drawRect(rect)

        # Zero line stays slightly stronger than the regular grid.
        if axis_lo <= 0 <= axis_hi:
            zero_pen = QPen(QColor("#526786"))
            zero_pen.setStyle(Qt.DashLine)
            zero_pen.setWidth(1)
            p.setPen(zero_pen)
            y0 = rect.bottom() - (0 - axis_lo) / axis_span * rect.height()
            p.drawLine(rect.left(), int(y0), rect.right(), int(y0))

        # Draw the requested lines in legend order; net goes last so the green
        # total remains visible when it overlaps one of its components.
        draw_order = ["showdown", "allin_adj", "nonshowdown", "net"]
        for key in draw_order:
            if key not in self.visible_series:
                continue
            points = self.series.get(key, [])
            if len(points) < 2:
                continue
            pen = QPen(self.SERIES_COLORS[key])
            pen.setWidth(2)
            p.setPen(pen)
            n = len(points) - 1
            path_points = []
            for i, val in enumerate(points):
                x = rect.left() + (i / n) * rect.width()
                y = rect.bottom() - ((val - axis_lo) / axis_span) * rect.height()
                path_points.append((int(x), int(y)))
            for a, b in zip(path_points, path_points[1:]):
                p.drawLine(a[0], a[1], b[0], b[1])


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem with an explicit typed sort value."""

    def __init__(self, text: str, sort_value=None):
        super().__init__(text)
        self.sort_value = sort_value if sort_value is not None else text.casefold()

    def __lt__(self, other):
        if isinstance(other, SortableTableWidgetItem):
            a = self.sort_value
            b = other.sort_value
            try:
                return a < b
            except TypeError:
                return str(a) < str(b)
        return super().__lt__(other)


class CardSuitDelegate(QStyledItemDelegate):
    """Paint card tokens using a four-colour deck without altering stored text."""

    def paint(self, painter, option, index):
        text = str(index.data(Qt.DisplayRole) or "")
        segments = card_text_segments(text)
        if not segments or not any(color for _, color in segments):
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        painter.save()
        painter.setClipRect(option.rect)
        fm = option.fontMetrics
        x = option.rect.left() + 6
        baseline = option.rect.top() + (option.rect.height() + fm.ascent() - fm.descent()) // 2
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        normal_color = option.palette.highlightedText().color() if selected else option.palette.text().color()

        for chunk, color in segments:
            if not chunk:
                continue
            painter.setPen(QColor(color) if color else normal_color)
            painter.drawText(x, baseline, chunk)
            x += fm.horizontalAdvance(chunk)
            if x >= option.rect.right() - 4:
                break
        painter.restore()


class ImportWorker(QThread):
    finished_import = Signal(int, int, list)
    progress_changed = Signal(int, int, str)
    failed = Signal(str)

    def __init__(self, db_path: str, target: str, is_folder: bool, hero_name: str):
        super().__init__()
        self.db_path = db_path
        self.target = target
        self.is_folder = is_folder
        self.hero_name = hero_name
        self._last_emitted = -1

    def _progress(self, current: int, total: int, filename: str):
        # Small imports update every hand. For very large histories, coalesce a
        # few hand updates so the GUI event queue cannot become the bottleneck.
        step = 1 if total <= 5000 else 10
        if current in (0, total) or current - self._last_emitted >= step:
            self._last_emitted = current
            self.progress_changed.emit(current, total, filename)

    def run(self):
        db = TrackerDB(self.db_path)
        try:
            if self.is_folder:
                result = import_folder(db, self.target, self.hero_name, progress=self._progress)
            else:
                result = import_file(db, self.target, self.hero_name, progress=self._progress)
            self.finished_import.emit(*result)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            db.close()


class ClickableDateField(QLineEdit):
    """Read-only date display that opens its calendar when clicked."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit()


class OptionalDatePicker(QWidget):
    """Date picker with a real empty/Any state and an explicit dropdown button."""

    dateChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._date = None
        self._popup = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.field = ClickableDateField()
        self.field.setText("Any")
        self.field.setMinimumWidth(110)
        self.field.setToolTip("Click to choose a date")
        self.field.clicked.connect(self.show_calendar)
        self.field.setStyleSheet(
            """
            QLineEdit {
                border-top-right-radius: 0;
                border-bottom-right-radius: 0;
                padding-right: 6px;
            }
            """
        )

        self.drop_button = QPushButton("▼")
        self.drop_button.setFixedWidth(30)
        self.drop_button.setToolTip("Open calendar")
        self.drop_button.setFocusPolicy(Qt.NoFocus)
        self.drop_button.clicked.connect(self.show_calendar)
        self.drop_button.setStyleSheet(
            """
            QPushButton {
                border-top-left-radius: 0;
                border-bottom-left-radius: 0;
                padding: 5px 4px;
                font-size: 9pt;
            }
            """
        )

        lay.addWidget(self.field, 1)
        lay.addWidget(self.drop_button)

    def has_date(self) -> bool:
        return self._date is not None and self._date.isValid()

    def date(self) -> QDate:
        return QDate(self._date) if self.has_date() else QDate()

    def setDate(self, date: QDate):
        if date is None or not date.isValid():
            self.clearDate()
            return

        changed = not self.has_date() or self._date != date
        self._date = QDate(date)
        self.field.setText(self._date.toString("M/d/yyyy"))
        if changed:
            self.dateChanged.emit()

    def clearDate(self):
        changed = self.has_date()
        self._date = None
        self.field.setText("Any")
        if changed:
            self.dateChanged.emit()

    def show_calendar(self):
        # With no date filter selected, open on today's actual date.
        selected = self._date if self.has_date() else QDate.currentDate()

        popup = QFrame(self, Qt.Popup)
        popup.setObjectName("dateCalendarPopup")
        popup.setStyleSheet(
            """
            QFrame#dateCalendarPopup {
                background-color: #111c30;
                border: 1px solid #38bdf8;
                border-radius: 7px;
            }
            """
        )

        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(4, 4, 4, 4)

        calendar = QCalendarWidget(popup)
        calendar.setGridVisible(False)
        calendar.setSelectedDate(selected)
        calendar.setCurrentPage(selected.year(), selected.month())
        popup_layout.addWidget(calendar)

        def choose_date(date: QDate):
            self.setDate(date)
            popup.close()

        calendar.clicked.connect(choose_date)

        self._popup = popup
        popup.adjustSize()
        popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        popup.show()
        calendar.setFocus()


class FiltersBar(QWidget):
    changed = Signal()

    def __init__(self, db: TrackerDB):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        # None means "Any". No fake/sentinel date is used.
        self.date_from = OptionalDatePicker()
        self.date_to = OptionalDatePicker()

        self.today_button = QPushButton("Today")
        self.today_button.setToolTip("Show hands played today")
        self.today_button.clicked.connect(self.show_today)

        self.all_dates_button = QPushButton("All Dates")
        self.all_dates_button.setToolTip("Show hands from all dates")
        self.all_dates_button.clicked.connect(self.show_all_dates)

        self.stakes = QComboBox()
        self.splash = QComboBox(); self.splash.addItems(["All pots", "Splash only", "Exclude splash"])
        self.runs = QComboBox(); self.runs.addItems(["All runouts", "Run once", "Run it 2x/3x"])

        self.date_from.dateChanged.connect(self.changed.emit)
        self.date_to.dateChanged.connect(self.changed.emit)
        self.stakes.currentIndexChanged.connect(self.changed.emit)
        self.splash.currentIndexChanged.connect(self.changed.emit)
        self.runs.currentIndexChanged.connect(self.changed.emit)

        lay.addWidget(QLabel("From")); lay.addWidget(self.date_from)
        lay.addWidget(QLabel("To")); lay.addWidget(self.date_to)
        lay.addWidget(self.today_button)
        lay.addWidget(self.all_dates_button)
        lay.addWidget(QLabel("Stakes")); lay.addWidget(self.stakes)
        lay.addWidget(self.splash); lay.addWidget(self.runs)
        lay.addStretch(1)
        self.refresh_stakes(db)

    def show_today(self):
        today = QDate.currentDate()
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self.date_from.setDate(today)
        self.date_to.setDate(today)
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)
        self.changed.emit()

    def show_all_dates(self):
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self.date_from.clearDate()
        self.date_to.clearDate()
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)
        self.changed.emit()

    def refresh_stakes(self, db: TrackerDB):
        old = self.stakes.currentData()
        self.stakes.blockSignals(True)
        self.stakes.clear()
        self.stakes.addItem("All stakes", None)
        for sb, bb in db.distinct_stakes():
            self.stakes.addItem(f"{fmt_money(sb)}/{fmt_money(bb)}", bb)
        idx = self.stakes.findData(old)
        if idx >= 0:
            self.stakes.setCurrentIndex(idx)
        self.stakes.blockSignals(False)

    def filters(self) -> dict:
        f = {}
        if self.date_from.has_date():
            f["date_from"] = self.date_from.date().toString("yyyy-MM-dd")
        if self.date_to.has_date():
            f["date_to"] = self.date_to.date().toString("yyyy-MM-dd")
        if self.stakes.currentData() is not None:
            f["bb_cents"] = int(self.stakes.currentData())
        f["splash"] = {1:"only", 2:"exclude"}.get(self.splash.currentIndex(), "all")
        f["runs"] = {1:"once", 2:"multi"}.get(self.runs.currentIndex(), "all")
        return f


class MainWindow(QMainWindow):
    def __init__(self, db_path: str, migration_progress=None):
        super().__init__()
        self.db_path = db_path
        self.db = TrackerDB(db_path, migration_progress=migration_progress)
        self.settings = QSettings("OpenAI", "CoinPokerTracker")
        self.hero_name = self.settings.value("hero_name", "Hero")
        self.worker = None
        self.setWindowTitle("CoinPoker Tracker v1.0")
        self.resize(1280, 800)
        self._apply_theme()

        self.import_progress = QProgressBar()
        self.import_progress.setMinimumWidth(260)
        self.import_progress.setTextVisible(True)
        self.import_progress.hide()
        self.statusBar().addPermanentWidget(self.import_progress)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_overview()
        self._build_hands()
        self._build_sessions()
        self._build_positions()
        self._build_menu()
        self.refresh_all()
        if self.db.recalculation_errors:
            QMessageBox.warning(
                self,
                "Recalculation incomplete",
                f"{self.db.recalculation_errors:,} stored hand(s) could not be reparsed. "
                "The calculation version was NOT marked complete, so stale EV values will not be hidden. "
                "Please export/re-import those hands or send the raw hand(s) for parser support.",
            )
        elif self.db.recalculated_count:
            self.statusBar().showMessage(
                f"Recalculated {self.db.recalculated_count:,} existing hands with deterministic all-in EV.",
                15000,
            )
        if not evaluator_available():
            self.statusBar().showMessage(
                "eval7 is unavailable; preflop EV remains reproducible but recalculation will be slower.",
                30000,
            )

    def _apply_theme(self):
        """Apply a vibrant dark theme without changing any tracker calculations."""
        self.setStyleSheet(
            """
            QMainWindow, QDialog {
                background-color: #09111f;
                color: #e8eefc;
            }
            QWidget {
                color: #e8eefc;
                font-size: 10pt;
            }
            QMenuBar {
                background-color: #0d1728;
                color: #dbeafe;
                border-bottom: 1px solid #22314d;
                padding: 3px;
            }
            QMenuBar::item:selected, QMenu::item:selected {
                background-color: #24395f;
                color: #ffffff;
                border-radius: 4px;
            }
            QMenu {
                background-color: #111c30;
                border: 1px solid #31405d;
                padding: 5px;
            }
            QTabWidget::pane {
                border: 1px solid #263552;
                border-radius: 8px;
                background-color: #0d1627;
                top: -1px;
            }
            QTabBar::tab {
                background-color: #121d32;
                color: #91a4c8;
                border: 1px solid #263552;
                border-bottom: none;
                padding: 9px 18px;
                margin-right: 3px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: 600;
            }
            QTabBar::tab:hover {
                background-color: #1a2945;
                color: #dbeafe;
            }
            QTabBar::tab:selected {
                background-color: #24395f;
                color: #ffffff;
                border-top: 2px solid #38bdf8;
            }
            QPushButton {
                background-color: #1e3a5f;
                color: #eff6ff;
                border: 1px solid #3b82f6;
                border-radius: 7px;
                padding: 7px 12px;
                font-weight: 650;
            }
            QPushButton:hover {
                background-color: #285184;
                border-color: #60a5fa;
            }
            QPushButton:pressed {
                background-color: #172f50;
            }
            QPushButton:disabled {
                background-color: #172033;
                border-color: #2a3448;
                color: #64748b;
            }
            QComboBox, QDateEdit, QLineEdit, QPlainTextEdit, QListWidget {
                background-color: #111c30;
                color: #edf4ff;
                border: 1px solid #334766;
                border-radius: 6px;
                padding: 5px 7px;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QComboBox:hover, QDateEdit:hover, QLineEdit:hover {
                border-color: #38bdf8;
            }
            QComboBox::drop-down, QDateEdit::drop-down {
                border: none;
                width: 22px;
            }
            QTableWidget {
                background-color: #0f192b;
                alternate-background-color: #121f35;
                color: #e6eefb;
                gridline-color: #25344f;
                border: 1px solid #263552;
                border-radius: 7px;
                selection-background-color: #244e85;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background-color: #1b2a46;
                color: #bfe3ff;
                border: none;
                border-right: 1px solid #2f4262;
                border-bottom: 1px solid #2f4262;
                padding: 7px;
                font-weight: 700;
            }
            QCheckBox {
                spacing: 7px;
                padding: 2px 3px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #4a607f;
                background: #101a2d;
            }
            QCheckBox::indicator:checked {
                background: #2563eb;
                border-color: #60a5fa;
            }
            QProgressBar {
                background-color: #111c30;
                color: #f8fafc;
                border: 1px solid #334766;
                border-radius: 6px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #22c55e;
                border-radius: 5px;
            }
            QStatusBar {
                background-color: #0d1728;
                color: #9fb2cf;
                border-top: 1px solid #22314d;
            }
            QSplitter::handle {
                background-color: #263552;
            }
            QToolTip {
                background-color: #17233a;
                color: #f8fafc;
                border: 1px solid #38bdf8;
                padding: 5px;
            }
            """
        )

    def closeEvent(self, event):
        self.db.close()
        super().closeEvent(event)

    def _build_menu(self):
        menu = self.menuBar().addMenu("Import")
        a_file = QAction("Import hand-history file…", self)
        a_folder = QAction("Import folder…", self)
        a_file.triggered.connect(self.choose_file)
        a_folder.triggered.connect(self.choose_folder)
        menu.addAction(a_file); menu.addAction(a_folder)

    def _build_overview(self):
        w = QWidget(); outer = QVBoxLayout(w)

        top = QHBoxLayout()
        self.filters = FiltersBar(self.db)
        self.filters.changed.connect(self.refresh_all)
        top.addWidget(self.filters, 1)
        self.customize_cards_button = QPushButton("Customize cards…")
        self.customize_cards_button.setToolTip("Reorder, hide, or restore Overview stat cards")
        self.customize_cards_button.clicked.connect(self.customize_overview_cards)
        top.addWidget(self.customize_cards_button)
        outer.addLayout(top)

        self.card_grid = QGridLayout()
        self.cards = {title: StatCard(title) for title in OVERVIEW_CARD_TITLES}
        self.card_order, self.hidden_cards = self._load_overview_card_layout()
        self._apply_overview_card_layout()
        outer.addLayout(self.card_grid)
        graph_controls = QHBoxLayout()
        graph_controls.addWidget(QLabel("Graph:"))
        self.graph_checks = {}
        graph_options = [
            ("net", "Net won", "#2ecc71"),
            ("showdown", "Won at showdown", "#3498db"),
            ("allin_adj", "All-in Adj EV", "#f1c40f"),
            ("nonshowdown", "Won without showdown", "#e74c3c"),
        ]
        for key, label, color in graph_options:
            checkbox = QCheckBox(label)
            stored = self.settings.value(f"overview/graph/{key}", True)
            if isinstance(stored, str):
                checked = stored.lower() not in {"0", "false", "no", "off"}
            else:
                checked = bool(stored)
            checkbox.setChecked(checked)
            checkbox.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: 600; }}")
            checkbox.toggled.connect(lambda checked, k=key: self._graph_visibility_changed(k, checked))
            self.graph_checks[key] = checkbox
            graph_controls.addWidget(checkbox)
        graph_controls.addStretch(1)
        outer.addLayout(graph_controls)

        self.graph = ProfitGraph()
        for key, checkbox in self.graph_checks.items():
            self.graph.set_series_visible(key, checkbox.isChecked())
        outer.addWidget(self.graph, 1)
        self.tabs.addTab(w, "Overview")

    def _load_overview_card_layout(self) -> tuple[list[str], set[str]]:
        """Load and sanitize the persistent Overview card layout."""
        known = set(OVERVIEW_CARD_TITLES)
        try:
            raw_order = self.settings.value("overview/card_order", "")
            parsed_order = json.loads(raw_order) if raw_order else []
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_order = []

        order = []
        for title in parsed_order if isinstance(parsed_order, list) else []:
            if title in known and title not in order:
                order.append(title)
        for title in OVERVIEW_CARD_TITLES:
            if title not in order:
                order.append(title)

        try:
            raw_hidden = self.settings.value("overview/hidden_cards", "")
            parsed_hidden = json.loads(raw_hidden) if raw_hidden else []
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_hidden = []
        hidden = {title for title in parsed_hidden if title in known} if isinstance(parsed_hidden, list) else set()
        return order, hidden

    def _save_overview_card_layout(self):
        self.settings.setValue("overview/card_order", json.dumps(self.card_order))
        self.settings.setValue("overview/hidden_cards", json.dumps(sorted(self.hidden_cards)))
        self.settings.sync()

    def _apply_overview_card_layout(self):
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        visible_index = 0
        for title in self.card_order:
            card = self.cards[title]
            if title in self.hidden_cards:
                card.hide()
                continue
            card.show()
            self.card_grid.addWidget(card, visible_index // 5, visible_index % 5)
            visible_index += 1

        # Keep the first columns from stretching oddly when most cards are hidden.
        for col in range(5):
            self.card_grid.setColumnStretch(col, 1)

    def customize_overview_cards(self):
        dialog = OverviewCardsDialog(self.card_order, self.hidden_cards, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.card_order, self.hidden_cards = dialog.layout_state()
        self._save_overview_card_layout()
        self._apply_overview_card_layout()

    def _graph_visibility_changed(self, key: str, checked: bool):
        self.settings.setValue(f"overview/graph/{key}", checked)
        self.settings.sync()
        if hasattr(self, "graph"):
            self.graph.set_series_visible(key, checked)



    def _build_hands(self):
        w = QWidget(); lay = QVBoxLayout(w)

        toolbar = QHBoxLayout()
        self.delete_hands_button = QPushButton("Delete selected hand(s)")
        self.delete_hands_button.setToolTip("Delete the selected hands from this tracker database")
        self.delete_hands_button.clicked.connect(self.delete_selected_hands)
        toolbar.addWidget(self.delete_hands_button)
        toolbar.addStretch(1)
        lay.addLayout(toolbar)

        split = QSplitter(Qt.Vertical)
        self.hand_table = QTableWidget(0, 13)
        self.hand_table.setHorizontalHeaderLabels([
            "Date", "Hand", "Stakes", "Pos", "Cards", "Board(s)", "Runs",
            "Splash", "Splash won", "Pot", "Net", "AI Eq", "AI Adj BB"
        ])
        header = self.hand_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._sort_hands_by_column)
        self._hand_sort_column = 0
        self._hand_sort_order = Qt.DescendingOrder
        header.setSortIndicator(self._hand_sort_column, self._hand_sort_order)
        self.hand_table.setAlternatingRowColors(True)
        self.hand_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.hand_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.hand_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.hand_table.setItemDelegateForColumn(4, CardSuitDelegate(self.hand_table))
        self.hand_table.setItemDelegateForColumn(5, CardSuitDelegate(self.hand_table))
        self.hand_table.itemSelectionChanged.connect(self.show_selected_hand)
        self.raw = QPlainTextEdit(); self.raw.setReadOnly(True)
        f = QFont("Consolas"); f.setStyleHint(QFont.Monospace); self.raw.setFont(f)
        split.addWidget(self.hand_table); split.addWidget(self.raw); split.setSizes([450,260])
        lay.addWidget(split)
        self.tabs.addTab(w, "Hands")

    def _build_sessions(self):
        w = QWidget(); lay = QVBoxLayout(w)

        toolbar = QHBoxLayout()
        self.delete_sessions_button = QPushButton("Delete selected session(s)")
        self.delete_sessions_button.setToolTip(
            "Delete every hand contained in the selected session(s) from this tracker database"
        )
        self.delete_sessions_button.clicked.connect(self.delete_selected_sessions)
        toolbar.addWidget(self.delete_sessions_button)
        toolbar.addStretch(1)
        lay.addLayout(toolbar)

        self.session_table = QTableWidget(0, 6)
        self.session_table.setHorizontalHeaderLabels(["Start", "End", "Duration", "Hands", "Net", "BB won"])
        self.session_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.session_table.setAlternatingRowColors(True)
        self.session_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.session_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.session_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._session_rows = []
        lay.addWidget(self.session_table)
        self.tabs.addTab(w, "Sessions")

    def _build_positions(self):
        w=QWidget(); lay=QVBoxLayout(w)
        self.pos_table=QTableWidget(0,6)
        self.pos_table.setHorizontalHeaderLabels(["Position","Hands","Net","bb/100","VPIP","PFR"])
        self.pos_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pos_table.setAlternatingRowColors(True)
        self.pos_table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.pos_table); self.tabs.addTab(w,"Position")

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import CoinPoker hand history", "", "Text files (*.txt);;All files (*)")
        if path: self.start_import(path, False)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Import CoinPoker hand-history folder")
        if path: self.start_import(path, True)

    def start_import(self, target: str, is_folder: bool):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Import running", "An import is already running.")
            return
        self.statusBar().showMessage(f"Counting hands in {target}…")
        self.import_progress.setRange(0, 0)
        self.import_progress.setFormat("Counting hands…")
        self.import_progress.show()
        self.worker = ImportWorker(self.db_path, target, is_folder, self.hero_name)
        self.worker.progress_changed.connect(self.import_progress_changed)
        self.worker.finished_import.connect(self.import_finished)
        self.worker.failed.connect(self.import_failed)
        self.worker.start()

    def import_progress_changed(self, current: int, total: int, filename: str):
        if total > 0:
            self.import_progress.setRange(0, total)
            self.import_progress.setValue(min(current, total))
            self.import_progress.setFormat(f"Importing hand {current:,} / {total:,}")
            self.statusBar().showMessage(
                f"Importing {filename} — hand {current:,}/{total:,}"
            )
        else:
            self.import_progress.setRange(0, 1)
            self.import_progress.setValue(0)
            self.import_progress.setFormat("No hands found")

    def import_finished(self, added: int, duplicates: int, errors: list):
        self.import_progress.hide()
        self.statusBar().showMessage(f"Imported {added} new hands; {duplicates} duplicates.", 10000)
        self.filters.refresh_stakes(self.db)
        self.refresh_all()
        if errors:
            QMessageBox.warning(self, "Import completed with parser warnings", "\n".join(errors[:20]) + ("\n…" if len(errors)>20 else ""))

    def import_failed(self, message: str):
        self.import_progress.hide()
        self.statusBar().showMessage("Import failed", 10000)
        QMessageBox.critical(self, "Import failed", message)

    def refresh_all(self):
        f = self.filters.filters() if hasattr(self, 'filters') else {}
        o = self.db.overview(f)
        vals = {
            "Hands": f"{o['hands']:,}", "Net": fmt_money(o['net_cents']),
            "Splash won": fmt_money(o['splash_won_cents']), "bb/100": f"{o['bb100']:.2f}",
            "All-in Adj Net Won": fmt_money(o['allin_adj_cents']),
            "All-in Adj BB": f"{o['allin_adj_bb']:.2f}", "Adj bb/100": f"{o['allin_adj_bb100']:.2f}",
            "AI adj hands": f"{o['allin_adjusted_hands']:,}",
            "VPIP": fmt_pct(o['vpip']), "PFR": fmt_pct(o['pfr']), "3-Bet": fmt_pct(o['three_bet']),
            "WWSF": fmt_pct(o['wwsf']), "WTSD": fmt_pct(o['wtsd']), "W$SD": fmt_pct(o['wsd']),
            "Splash hands": f"{o['splash_hands']:,}", "RIT hands": f"{o['multi_run_hands']:,}",
        }
        for k,v in vals.items(): self.cards[k].value.setText(v)
        graph_rows = self.db.profit_points(f)
        net_changes = [float(r["hero_net_cents"]) for r in graph_rows]
        showdown_changes = [
            float(r["hero_net_cents"]) if r["hero_wtsd"] else 0.0 for r in graph_rows
        ]
        nonshowdown_changes = [
            0.0 if r["hero_wtsd"] else float(r["hero_net_cents"]) for r in graph_rows
        ]
        allin_adj_changes = [float(r["hero_allin_adj_cents"]) for r in graph_rows]
        self.graph.set_series_changes(
            net=net_changes,
            showdown=showdown_changes,
            allin_adj=allin_adj_changes,
            nonshowdown=nonshowdown_changes,
        )
        self.refresh_hands(f); self.refresh_sessions(f); self.refresh_positions(f)

    def _sort_hands_by_column(self, column: int):
        """Sort Hands columns with useful first-click direction and typed values."""
        # Numeric/date columns are usually inspected high-to-low/newest-to-oldest.
        descending_first = {0, 1, 2, 4, 6, 7, 8, 9, 10, 11, 12}
        if column == self._hand_sort_column:
            self._hand_sort_order = (
                Qt.AscendingOrder if self._hand_sort_order == Qt.DescendingOrder else Qt.DescendingOrder
            )
        else:
            self._hand_sort_column = column
            self._hand_sort_order = Qt.DescendingOrder if column in descending_first else Qt.AscendingOrder
        self.hand_table.horizontalHeader().setSortIndicator(column, self._hand_sort_order)
        self.hand_table.sortItems(column, self._hand_sort_order)
        if self.hand_table.rowCount():
            self.hand_table.selectRow(0)

    @staticmethod
    def _hand_sort_values(r, boards: str) -> list:
        try:
            hand_no = int(r['hand_id'])
        except (TypeError, ValueError):
            hand_no = str(r['hand_id'])
        return [
            r['started_at'],
            hand_no,
            (int(r['bb_cents']), int(r['sb_cents'])),
            (r['hero_position'] or '').casefold(),
            hole_card_sort_key(r['hero_cards'] or ''),
            boards.casefold(),
            int(r['run_count']),
            int(r['splash_cents'] or 0),
            int(r['hero_splash_won_cents'] or 0),
            int(r['total_pot_cents'] or 0),
            int(r['hero_net_cents'] or 0),
            float(r['hero_allin_equity']) if r['hero_allin_adjusted'] and r['hero_allin_equity'] is not None else -1.0,
            (float(r['hero_allin_adj_cents']) / int(r['bb_cents'])) if r['hero_allin_adjusted'] and r['bb_cents'] else float('-inf'),
        ]

    def refresh_hands(self, f):
        rows = self.db.hands(f)
        self.hand_table.setRowCount(0)
        self.hand_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            boards = " | ".join(x for x in [r['board1'], r['board2'], r['board3']] if x)
            vals = [
                r['started_at'][:19], r['hand_id'],
                f"{fmt_money(r['sb_cents'])}/{fmt_money(r['bb_cents'])}",
                r['hero_position'] or '', normalize_hole_cards(r['hero_cards'] or ''), boards, str(r['run_count']),
                (f"{r['splash_type']} {fmt_money(r['splash_cents'])}" if r['splash_cents'] else ''),
                (fmt_money(r['hero_splash_won_cents']) if r['hero_splash_won_cents'] else ''),
                fmt_money(r['total_pot_cents']), fmt_money(r['hero_net_cents']),
                (("~" if r['hero_allin_estimated'] else "") + f"{float(r['hero_allin_equity']) * 100:.2f}%"
                 if r['hero_allin_adjusted'] and r['hero_allin_equity'] is not None else ''),
                (("~" if r['hero_allin_estimated'] else "") + f"{float(r['hero_allin_adj_cents']) / r['bb_cents']:.2f}"
                 if r['hero_allin_adjusted'] and r['bb_cents'] else ''),
            ]
            sort_values = self._hand_sort_values(r, boards)
            for j, (value, sort_value) in enumerate(zip(vals, sort_values)):
                self.hand_table.setItem(i, j, SortableTableWidgetItem(str(value), sort_value))

        if rows:
            self.hand_table.sortItems(self._hand_sort_column, self._hand_sort_order)
            self.hand_table.horizontalHeader().setSortIndicator(self._hand_sort_column, self._hand_sort_order)
            self.hand_table.selectRow(0)
        else:
            self.raw.clear()

    def show_selected_hand(self):
        row=self.hand_table.currentRow()
        if row<0: return
        item=self.hand_table.item(row,1)
        if item: self.raw.setPlainText(self.db.raw_hand(item.text()))

    def delete_selected_hands(self):
        rows = sorted({index.row() for index in self.hand_table.selectionModel().selectedRows()})
        hand_ids = [
            self.hand_table.item(row, 1).text()
            for row in rows
            if self.hand_table.item(row, 1) is not None
        ]
        if not hand_ids:
            QMessageBox.information(self, "Delete hands", "Select one or more hands first.")
            return

        if len(hand_ids) == 1:
            detail = f"hand #{hand_ids[0]}"
        else:
            detail = f"{len(hand_ids)} selected hands"
        answer = QMessageBox.question(
            self,
            "Delete hands",
            f"Delete {detail} from the tracker?\n\n"
            "This removes the hand and its stored actions/results from the local database. "
            "If you later import the original hand-history file again, the hand can be imported again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        deleted = self.db.delete_hands(hand_ids)
        self.raw.clear()
        self.filters.refresh_stakes(self.db)
        self.refresh_all()
        self.statusBar().showMessage(f"Deleted {deleted} hand{'s' if deleted != 1 else ''}.", 8000)

    def refresh_sessions(self, f):
        rows = self.db.sessions(30, f)
        self._session_rows = rows
        self.session_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            minutes = max(0, int((r['end'] - r['start']).total_seconds() / 60))
            vals = [
                r['start'].strftime('%Y-%m-%d %H:%M'), r['end'].strftime('%Y-%m-%d %H:%M'),
                f"{minutes//60}h {minutes%60}m", str(r['hands']),
                fmt_money(r['net_cents']), f"{r['net_bb']:.1f}",
            ]
            for j, v in enumerate(vals):
                self.session_table.setItem(i, j, QTableWidgetItem(v))

    def delete_selected_sessions(self):
        rows = sorted({index.row() for index in self.session_table.selectionModel().selectedRows()})
        selected_sessions = [
            self._session_rows[row]
            for row in rows
            if 0 <= row < len(self._session_rows)
        ]
        if not selected_sessions:
            QMessageBox.information(self, "Delete sessions", "Select one or more sessions first.")
            return

        hand_ids = list(dict.fromkeys(
            hand_id
            for session in selected_sessions
            for hand_id in session.get("hand_ids", [])
        ))
        if not hand_ids:
            QMessageBox.information(self, "Delete sessions", "The selected session contains no stored hands.")
            return


        session_count = len(selected_sessions)
        answer = QMessageBox.question(
            self,
            "Delete sessions",
            f"Delete {session_count} selected session{'s' if session_count != 1 else ''} and "
            f"all {len(hand_ids)} hand{'s' if len(hand_ids) != 1 else ''} inside "
            f"{'them' if session_count != 1 else 'it'}?\n\n"
            "This permanently removes those hands and their stored actions/results from the local database. "
            "Re-importing the original hand-history file will add them back.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        deleted = self.db.delete_hands(hand_ids)
        self.raw.clear()
        self.filters.refresh_stakes(self.db)
        self.refresh_all()
        self.statusBar().showMessage(
            f"Deleted {session_count} session{'s' if session_count != 1 else ''} "
            f"containing {deleted} hand{'s' if deleted != 1 else ''}.",
            10000,
        )

    def refresh_positions(self, f):
        rows=self.db.positional(f); self.pos_table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            h=r['hands'] or 0; netbb=float(r['net_bb'] or 0)
            vals=[r['position'] or '—',str(h),fmt_money(r['net_cents'] or 0),f"{(netbb*100/h if h else 0):.2f}",
                  f"{((r['vpip_n'] or 0)*100/h if h else 0):.1f}%",f"{((r['pfr_n'] or 0)*100/h if h else 0):.1f}%"]
            for j,v in enumerate(vals): self.pos_table.setItem(i,j,QTableWidgetItem(v))
