from __future__ import annotations

import json
import os
import re
from pathlib import Path
from PySide6.QtCore import QDate, QItemSelectionModel, QLocale, QPoint, QSettings, Qt, Signal, QThread
from PySide6.QtGui import QAction, QColor, QDoubleValidator, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCalendarWidget, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSplitter, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QTabWidget, QTableWidget,
    QTableWidgetItem, QToolTip, QVBoxLayout, QWidget
)
from .database import TrackerDB
from .equity import evaluator_available
from .importer import import_file, import_folder
from .graphing import hand_tick_step, hand_ticks, money_axis_bounds, nice_step
from .handtable import (
    card_text_segments, hole_card_sort_key, normalize_hole_cards,
    starting_hand_sort_key,
)
from .replay import build_replay
from .replayer import HandReplayerDialog


OVERVIEW_CARD_TITLES = [
    "Hands", "Net Won","All-in Adj Net Won","bb/100","Adj bb/100", "Net Won post RB", "bb/100 post RB",
     "VPIP", "PFR",  "3-Bet", "All-in Adj BB",  "AI adj hands",  "WWSF", "WTSD", "W$SD",
     "Splash won", "Splash hands", "RIT hands", "Rakeback Amount",
]
CARD_ACCENTS = {
    "Hands": "#8b5cf6",
    "Net Won": "#22c55e",
    "Rakeback Amount": "#14b8a6",
    "Net Won post RB": "#4ade80",
    "Splash won": "#f59e0b",
    "bb/100": "#10b981",
    "bb/100 post RB": "#34d399",
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

DEFAULT_HAND_LIMIT = 1000
HAND_LIMIT_OPTIONS = (500, 1000, 2500, 5000, 10000, -1)

HAND_TABLE_HEADERS = [
    "Date",
    "Hand",
    "Stakes",
    "Pos",
    "Cards",
    "Board(s)",
    "Runs",
    "Splash",
    "Splash won",
    "Pot",
    "Hero Contrib (BB)",
    "Net Won",
    "BB Won",
    "AI Eq",
    "AI Adj Net Won",
    "AI Adj BB",
]
HERO_CONTRIB_COLUMN = HAND_TABLE_HEADERS.index(
    "Hero Contrib (BB)"
)
NET_WON_COLUMN = HAND_TABLE_HEADERS.index("Net Won")
BB_WON_COLUMN = HAND_TABLE_HEADERS.index("BB Won")
AI_ADJ_NET_WON_COLUMN = HAND_TABLE_HEADERS.index("AI Adj Net Won")
AI_ADJ_BB_COLUMN = HAND_TABLE_HEADERS.index("AI Adj BB")

WINNING_TEXT_COLOR = "#4ade80"
LOSING_TEXT_COLOR = "#ff667d"

HAND_TABLE_TOOLTIPS = {
    "Hero Contrib (BB)": (
        "Hero's total contribution after returned chips, divided by the big blind"
    ),
    "Net Won": "Hero's net winnings in CoinPoker currency",
    "BB Won": "Hero's net winnings divided by this hand's big blind",
    "AI Eq": "Hero's all-in equity when an all-in adjustment was calculated",
    "AI Adj Net Won": (
        "All-in adjusted net winnings; equals Net Won when no adjustment applies. "
        "~ marks an estimated calculation"
    ),
    "AI Adj BB": (
        "All-in adjusted net winnings divided by this hand's big blind; "
        "~ marks an estimated calculation"
    ),
}

GROUP_BY_COLUMNS = {
    "position": (
        "group", "hands", "net_cents", "bb100", "vpip", "pfr",
        "three_bet", "wwsf", "wtsd", "wsd", "allin_adj_cents", "allin_adj_bb100",
    ),
    "stakes": (
        "group", "hands", "net_cents", "net_bb", "bb100",
        "allin_adj_cents", "allin_adj_bb100", "splash_won_cents", "vpip", "pfr", "three_bet",
    ),
    "starting_hands": (
        "group", "hand_type", "hands", "share_pct", "net_cents", "bb100",
        "allin_adj_cents", "allin_adj_bb100", "vpip", "pfr", "three_bet",
    ),
}
GROUP_COLUMN_DETAILS = {
    "hands": ("Hands", "integer", "Number of hands matching the current filters"),
    "hand_type": ("Type", "text", "Pair, suited, offsuit, or another card format"),
    "share_pct": ("% Hands", "percent", "Share of all hands matching the current filters"),
    "net_cents": ("Net Won", "money", "Winnings before manually entered rakeback"),
    "net_bb": ("BB Won", "number", "Sum of each hand's winnings in its own big blinds"),
    "bb100": ("bb/100", "number", "Big blinds won per 100 hands"),
    "allin_adj_cents": ("AI Adj Net Won", "money", "All-in adjusted net winnings"),
    "allin_adj_bb100": ("Adj bb/100", "number", "All-in adjusted big blinds per 100 hands"),
    "splash_won_cents": ("Splash Won", "money", "Splash money won by Hero"),
    "vpip": ("VPIP", "percent", "Voluntarily put money in the pot / hands"),
    "pfr": ("PFR", "percent", "Preflop raises / hands"),
    "three_bet": ("3-Bet", "percent", "Preflop 3-bets / 3-bet opportunities"),
    "wwsf": ("WWSF", "percent", "Hands won after seeing a flop / flops seen"),
    "wtsd": ("WTSD", "percent", "Showdowns / flops seen"),
    "wsd": ("W$SD", "percent", "Showdowns won / showdowns"),
}


def fmt_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}₮{cents / 100:.2f}"


def fmt_pct(x: float) -> str:
    return f"{x:.1f}%"


def parse_hand_limit(text: str) -> int:
    """Parse a positive count (with optional thousands separators) or All."""
    text = text.strip()
    if text.casefold() == "all":
        return -1
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", text):
        raise ValueError("Enter a positive whole number, such as 3,500, or choose All.")
    digits = text.replace(",", "").lstrip("0")
    # Keep custom counts within Qt's signed-integer range; All has no cap.
    if len(digits) > 10 or (digits and int(digits) > 2_147_483_647):
        raise ValueError("That amount is too large. Choose All to load every matching hand.")
    if not digits:
        raise ValueError("Enter at least 1 hand, or choose All.")
    return int(digits)


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
            self.setToolTip(
                "Won When Saw Flop: percentage of flops seen where Hero "
                "won at least part of the pot."
            )
        elif title == "Rakeback Amount":
            self.setToolTip(
                "Manual rakeback stored for the selected stake(s)."
            )
        elif title == "Net Won post RB":
            self.setToolTip(
                "Net winnings plus manual rakeback stored for the selected stake(s)."
            )
        elif title == "bb/100 post RB":
            self.setToolTip(
                "bb/100 after adding each stake's manual rakeback in big-blind terms."
            )
        self.value = QLabel("—")
        self.value.setStyleSheet("color: #f8fbff;")
        f = self.value.font()
        f.setPointSize(f.pointSize() + 7)
        f.setBold(True)
        self.value.setFont(f)
        lay.addWidget(self.title)
        lay.addWidget(self.value)


class OverviewCardsDialog(QDialog):
    """Reorder and show/hide Overview stat cards."""
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

        # Pure reordering only. Items themselves are not drop targets.
        self.list.setDragDropOverwriteMode(False)
        self.list.viewport().setAcceptDrops(True)
        self.list.setDropIndicatorShown(True)

        lay.addWidget(self.list, 1)
        reset = QPushButton("Reset to default layout")
        reset.clicked.connect(self.reset_defaults)
        lay.addWidget(reset)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
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
            item.setCheckState(
                Qt.Unchecked if title in hidden else Qt.Checked
            )
            self.list.addItem(item)

    def reset_defaults(self):
        self._populate(list(OVERVIEW_CARD_TITLES), set())

    def layout_state(self) -> tuple[list[str], set[str]]:
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

        # Defensive fallback so a malformed drag can never permanently
        # remove a stat card from the saved settings.
        for title in OVERVIEW_CARD_TITLES:
            if title not in order:
                order.append(title)

        return order, hidden


class RakebackDialog(QDialog):
    """Edit the manual rakeback amount for one cash-game stake."""

    def __init__(
        self,
        db: TrackerDB,
        selected_bb_cents: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Manual rakeback")
        self.setMinimumWidth(380)

        lay = QVBoxLayout(self)

        help_text = QLabel(
            "Enter your cumulative rakeback for a cash-game stake. "
            "The amount is stored in the tracker database and only "
            "affects that stake's post-RB results."
        )
        help_text.setWordWrap(True)
        lay.addWidget(help_text)

        form = QGridLayout()
        form.addWidget(QLabel("Stake"), 0, 0)

        self.stake = QComboBox()
        self.stake.setMinimumWidth(170)
        for sb, bb in self.db.rakeback_stakes():
            self.stake.addItem(
                f"{fmt_money(sb)}/{fmt_money(bb)}",
                (int(sb), int(bb)),
            )
        form.addWidget(self.stake, 0, 1)

        form.addWidget(QLabel("Rakeback (₮)"), 1, 0)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0.00")
        self.amount.setToolTip(
            "Cumulative manual rakeback for the selected stake."
        )
        form.addWidget(self.amount, 1, 1)
        lay.addLayout(form)

        self.stake.currentIndexChanged.connect(
            self._load_amount
        )

        if selected_bb_cents is not None:
            for index in range(self.stake.count()):
                data = self.stake.itemData(index)
                if data and int(data[1]) == int(selected_bb_cents):
                    self.stake.setCurrentIndex(index)
                    break

        self._load_amount()

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _load_amount(self):
        data = self.stake.currentData()
        if not data:
            self.amount.setText("0.00")
            return

        _sb_cents, bb_cents = data
        cents = self.db.rakeback_cents(int(bb_cents))
        self.amount.setText(f"{cents / 100:.2f}")
        self.amount.selectAll()

    def _amount_cents(self) -> int | None:
        text = (
            self.amount.text()
            .strip()
            .replace(",", "")
            .replace("₮", "")
            .replace("$", "")
        )
        if not text:
            return 0

        try:
            amount = float(text)
        except ValueError:
            return None

        if amount < 0:
            return None

        return int(round(amount * 100))

    def _save(self):
        data = self.stake.currentData()
        if not data:
            return

        cents = self._amount_cents()
        if cents is None:
            QMessageBox.warning(
                self,
                "Invalid rakeback",
                "Enter a non-negative rakeback amount, for example 100.",
            )
            self.amount.setFocus()
            self.amount.selectAll()
            return

        sb_cents, bb_cents = data
        self.db.set_rakeback_cents(
            int(sb_cents),
            int(bb_cents),
            cents,
        )
        self.accept()

    def saved_value(self) -> tuple[int, int, int]:
        data = self.stake.currentData()
        if not data:
            return 0, 0, 0
        sb_cents, bb_cents = data
        return (
            int(sb_cents),
            int(bb_cents),
            self.db.rakeback_cents(int(bb_cents)),
        )


class ProfitGraph(QWidget):
    SERIES_COLORS = {
        "showdown": QColor("#3498db"),
        "allin_adj": QColor("#f1c40f"),
        "nonshowdown": QColor("#e74c3c"),
        "net": QColor("#2ecc71"),
        "net_post_rb": QColor("#CB00F5"),
    }

    def __init__(self):
        super().__init__()

        self.series: dict[str, list[float]] = {
            "showdown": [0.0],
            "allin_adj": [0.0],
            "nonshowdown": [0.0],
            "net": [0.0],
            "net_post_rb": [0.0],
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
        net_post_rb: list[float],
        showdown: list[float],
        allin_adj: list[float],
        nonshowdown: list[float],
    ):
        self.series = {
            "showdown": self._cumulative(showdown),
            "allin_adj": self._cumulative(allin_adj),
            "nonshowdown": self._cumulative(nonshowdown),
            "net": self._cumulative(net),
            "net_post_rb": self._cumulative(net_post_rb),
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
    def _axis_bounds(
        lo: float,
        hi: float,
        target_ticks: int = 8,
    ) -> tuple[float, float, float]:
        return money_axis_bounds(lo, hi, target_ticks)

    @staticmethod
    def _hand_tick_step(hands: int, target_ticks: int = 10) -> int:
        return hand_tick_step(hands, target_ticks)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0d1627"))
        rect = self.rect().adjusted(12, 15, -86, -38)

        available = [
            (key, points)
            for key, points in self.series.items()
            if key in self.visible_series and len(points) >= 2
        ]

        if not available:
            p.setPen(self.palette().text().color())
            if any(len(points) >= 2 for points in self.series.values()):
                p.drawText(
                    rect,
                    Qt.AlignCenter,
                    "Select a graph line to display",
                )
            else:
                p.drawText(
                    rect,
                    Qt.AlignCenter,
                    "Import hands to see the profit graph",
                )

            return

        values = [
            value
            for _, points in available
            for value in points
        ]

        axis_lo, axis_hi, y_step = self._axis_bounds(
            min(values),
            max(values),
            8,
        )

        axis_span = axis_hi - axis_lo
        hands = max(len(points) for _, points in available) - 1

        grid_pen = QPen(QColor("#273754"))
        grid_pen.setStyle(Qt.DotLine)

        text_pen = QPen(QColor("#b8c7e0"))
        tick_len = 5
        y = axis_lo

        while y <= axis_hi + y_step * 0.5:
            py = rect.bottom() - (
                (y - axis_lo) / axis_span
            ) * rect.height()

            p.setPen(grid_pen)
            p.drawLine(
                rect.left(),
                int(py),
                rect.right(),
                int(py),
            )
            p.setPen(text_pen)
            p.drawLine(
                rect.right(),
                int(py),
                rect.right() + tick_len,
                int(py),
            )

            label = fmt_money(int(round(y)))

            label_rect = self.rect().adjusted(
                rect.right() + 8,
                int(py) - 10,
                -2,
                0,
            )
            label_rect.setHeight(20)
            p.drawText(
                label_rect,
                Qt.AlignLeft | Qt.AlignVCenter,
                label,
            )

            y += y_step

        x_ticks = hand_ticks(hands, 10)

        for hand_no in x_ticks:
            px = rect.left() + (
                hand_no / max(1, hands)
            ) * rect.width()
            p.setPen(grid_pen)
            p.drawLine(
                int(px),
                rect.top(),
                int(px),
                rect.bottom(),
            )

            p.setPen(text_pen)
            p.drawLine(
                int(px),
                rect.bottom(),
                int(px),
                rect.bottom() + tick_len,
            )

            label = f"{hand_no:,}"
            fm = p.fontMetrics()
            width = fm.horizontalAdvance(label) + 8
            label_rect = self.rect().adjusted(
                int(px) - width // 2,
                rect.bottom() + 8,
                0,
                -2,
            )
            label_rect.setWidth(width)
            label_rect.setHeight(20)

            if label_rect.left() < rect.left():
                label_rect.moveLeft(rect.left())

            if label_rect.right() > rect.right():
                label_rect.moveRight(rect.right())
            p.drawText(
                label_rect,
                Qt.AlignHCenter | Qt.AlignTop,
                label,
            )

        p.setPen(text_pen)
        p.drawRect(rect)

        if axis_lo <= 0 <= axis_hi:
            zero_pen = QPen(QColor("#526786"))
            zero_pen.setStyle(Qt.DashLine)
            zero_pen.setWidth(1)

            p.setPen(zero_pen)

            y0 = rect.bottom() - (
                (0 - axis_lo) / axis_span
            ) * rect.height()
            p.drawLine(
                rect.left(),
                int(y0),
                rect.right(),
                int(y0),
            )

        draw_order = [
            "showdown",
            "allin_adj",
            "nonshowdown",
            "net",
            "net_post_rb",
        ]

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
                x = rect.left() + (
                    i / n
                ) * rect.width()

                y = rect.bottom() - (
                    (val - axis_lo) / axis_span
                ) * rect.height()
                path_points.append(
                    (int(x), int(y))
                )

            for a, b in zip(
                path_points,
                path_points[1:],
            ):
                p.drawLine(
                    a[0],
                    a[1],
                    b[0],
                    b[1],
                )


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem with an explicit typed sort value."""
    def __init__(self, text: str, sort_value=None):
        super().__init__(text)

        self.sort_value = (
            sort_value
            if sort_value is not None
            else text.casefold()
        )

    def __lt__(self, other):
        if isinstance(
            other,
            SortableTableWidgetItem,
        ):
            a = self.sort_value
            b = other.sort_value
            try:
                return a < b
            except TypeError:
                return str(a) < str(b)

        return super().__lt__(other)


class CardSuitDelegate(QStyledItemDelegate):
    """Paint card tokens using a four-colour deck."""

    def paint(
        self,
        painter,
        option,
        index,
    ):
        text = str(
            index.data(Qt.DisplayRole) or ""
        )

        segments = card_text_segments(text)
        if (
            not segments
            or not any(
                color
                for _, color in segments
            )
        ):
            super().paint(
                painter,
                option,
                index,
            )
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = (
            opt.widget.style()
            if opt.widget
            else QApplication.style()
        )

        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            opt,
            painter,
            opt.widget,
        )

        painter.save()
        painter.setClipRect(option.rect)

        fm = option.fontMetrics
        x = option.rect.left() + 6
        baseline = option.rect.top() + (
            option.rect.height()
            + fm.ascent()
            - fm.descent()
        ) // 2

        selected = bool(
            option.state
            & QStyle.StateFlag.State_Selected
        )

        normal_color = (
            option.palette.highlightedText().color()
            if selected
            else option.palette.text().color()
        )

        for chunk, color in segments:
            if not chunk:
                continue
            painter.setPen(
                QColor(color)
                if color
                else normal_color
            )

            painter.drawText(
                x,
                baseline,
                chunk,
            )

            x += fm.horizontalAdvance(chunk)

            if x >= option.rect.right() - 4:
                break

        painter.restore()


class ImportWorker(QThread):
    finished_import = Signal(int, int, list)
    progress_changed = Signal(int, int, str)
    failed = Signal(str)

    def __init__(
        self,
        db_path: str,
        target: str,
        is_folder: bool,
        hero_name: str,
    ):
        super().__init__()

        self.db_path = db_path
        self.target = target
        self.is_folder = is_folder
        self.hero_name = hero_name
        self._last_emitted = -1

    def _progress(
        self,
        current: int,
        total: int,
        filename: str,
    ):
        step = 1 if total <= 5000 else 10

        if (
            current in (0, total)
            or current - self._last_emitted >= step
        ):
            self._last_emitted = current

            self.progress_changed.emit(
                current,
                total,
                filename,
            )

    def run(self):
        db = TrackerDB(self.db_path)
        try:
            if self.is_folder:
                result = import_folder(
                    db,
                    self.target,
                    self.hero_name,
                    progress=self._progress,
                )
            else:
                result = import_file(
                    db,
                    self.target,
                    self.hero_name,
                    progress=self._progress,
                )

            self.finished_import.emit(*result)
        except Exception as e:
            self.failed.emit(
                f"{type(e).__name__}: {e}"
            )

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
    """Optional date picker with a real empty/Any state."""

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
        self.field.setToolTip(
            "Click to choose a date"
        )
        self.field.clicked.connect(
            self.show_calendar
        )
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
        self.drop_button.setToolTip(
            "Open calendar"
        )
        self.drop_button.setFocusPolicy(
            Qt.NoFocus
        )
        self.drop_button.clicked.connect(
            self.show_calendar
        )
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

        lay.addWidget(
            self.field,
            1,
        )
        lay.addWidget(
            self.drop_button,
        )

    def has_date(self) -> bool:
        return (
            self._date is not None
            and self._date.isValid()
        )

    def date(self) -> QDate:
        if self.has_date():
            return QDate(self._date)

        return QDate()

    def setDate(self, date: QDate):
        if (
            date is None
            or not date.isValid()
        ):
            self.clearDate()
            return
        changed = (
            not self.has_date()
            or self._date != date
        )

        self._date = QDate(date)

        self.field.setText(
            self._date.toString(
                "M/d/yyyy"
            )
        )

        if changed:
            self.dateChanged.emit()

    def clearDate(self):
        changed = self.has_date()

        self._date = None
        self.field.setText("Any")

        if changed:
            self.dateChanged.emit()

    def show_calendar(self):
        selected = (
            self._date
            if self.has_date()
            else QDate.currentDate()
        )

        popup = QFrame(
            self,
            Qt.Popup,
        )

        popup.setObjectName(
            "dateCalendarPopup"
        )
        popup.setStyleSheet(
            """
            QFrame#dateCalendarPopup {
                background-color: #111c30;
                border: 1px solid #38bdf8;
                border-radius: 7px;
            }
            """
        )

        popup_layout = QVBoxLayout(
            popup
        )

        popup_layout.setContentsMargins(
            4,
            4,
            4,
            4,
        )

        calendar = QCalendarWidget(
            popup
        )
        calendar.setGridVisible(False)
        calendar.setSelectedDate(selected)
        calendar.setCurrentPage(
            selected.year(),
            selected.month(),
        )

        popup_layout.addWidget(calendar)

        def choose_date(date: QDate):
            self.setDate(date)
            popup.close()

        calendar.clicked.connect(
            choose_date
        )

        self._popup = popup

        popup.adjustSize()
        popup.move(
            self.mapToGlobal(
                self.rect().bottomLeft()
            )
        )

        popup.show()
        calendar.setFocus()


class FiltersBar(QWidget):
    changed = Signal()

    def __init__(
        self,
        db: TrackerDB,
    ):
        super().__init__()

        lay = QGridLayout(self)
        lay.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(10)
        lay.setColumnStretch(1, 1)
        # None means "Any".
        # No fake year-2000 sentinel is used.
        self.date_from = OptionalDatePicker()
        self.date_to = OptionalDatePicker()

        self.all_dates_button = QPushButton(
            "All Dates"
        )
        self.all_dates_button.setToolTip(
            "Show hands from all dates"
        )
        self.all_dates_button.clicked.connect(
            self.show_all_dates
        )
        self.today_button = QPushButton(
            "Today"
        )
        self.today_button.setToolTip(
            "Show hands played today"
        )
        self.today_button.clicked.connect(
            self.show_today
        )

        self.stakes = QComboBox()

        self.splash = QComboBox()
        self.splash.addItems(
            [
                "All pots",
                "Splash only",
                "Exclude splash",
            ]
        )
        self.runs = QComboBox()
        self.runs.addItems(
            [
                "All runouts",
                "Run once",
                "Run it 2x/3x",
            ]
        )
        self.bb_contributed_min = QLineEdit()
        self.bb_contributed_max = QLineEdit()
        for control, placeholder, tooltip in (
            (
                self.bb_contributed_min,
                "Any minimum",
                "Minimum BB Hero put into the pot after returned chips",
            ),
            (
                self.bb_contributed_max,
                "Any maximum",
                "Maximum BB Hero put into the pot after returned chips",
            ),
        ):
            validator = QDoubleValidator(
                0.0,
                1_000_000.0,
                2,
                control,
            )
            validator.setLocale(QLocale.c())
            validator.setNotation(
                QDoubleValidator.StandardNotation
            )
            control.setValidator(validator)
            control.setPlaceholderText(placeholder)
            control.setToolTip(tooltip)
            control.setClearButtonEnabled(True)
        self.date_from.dateChanged.connect(
            self.changed.emit
        )
        self.date_to.dateChanged.connect(
            self.changed.emit
        )
        self.stakes.currentIndexChanged.connect(
            lambda _index: self.changed.emit()
        )
        self.splash.currentIndexChanged.connect(
            lambda _index: self.changed.emit()
        )
        self.runs.currentIndexChanged.connect(
            lambda _index: self.changed.emit()
        )
        self.bb_contributed_min.textChanged.connect(
            lambda _text: self.changed.emit()
        )
        self.bb_contributed_max.textChanged.connect(
            lambda _text: self.changed.emit()
        )
        for control in (
            self.date_from,
            self.date_to,
            self.stakes,
            self.splash,
            self.runs,
            self.bb_contributed_min,
            self.bb_contributed_max,
        ):
            control.setMinimumWidth(300)

        lay.addWidget(QLabel("From"), 0, 0)
        lay.addWidget(self.date_from, 0, 1)
        lay.addWidget(QLabel("To"), 1, 0)
        lay.addWidget(self.date_to, 1, 1)

        quick_dates = QHBoxLayout()
        quick_dates.setContentsMargins(0, 0, 0, 0)
        quick_dates.addWidget(
            self.all_dates_button
        )
        quick_dates.addWidget(
            self.today_button
        )
        quick_dates.addStretch(1)
        lay.addWidget(QLabel("Quick dates"), 2, 0)
        lay.addLayout(quick_dates, 2, 1)

        lay.addWidget(QLabel("Stakes"), 3, 0)
        lay.addWidget(self.stakes, 3, 1)
        lay.addWidget(QLabel("Splash pots"), 4, 0)
        lay.addWidget(self.splash, 4, 1)
        lay.addWidget(QLabel("Runouts"), 5, 0)
        lay.addWidget(self.runs, 5, 1)
        lay.addWidget(QLabel("Min contributed (BB)"), 6, 0)
        lay.addWidget(self.bb_contributed_min, 6, 1)
        lay.addWidget(QLabel("Max contributed (BB)"), 7, 0)
        lay.addWidget(self.bb_contributed_max, 7, 1)

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

    def clear_all(self):
        controls = [
            self.date_from,
            self.date_to,
            self.stakes,
            self.splash,
            self.runs,
            self.bb_contributed_min,
            self.bb_contributed_max,
        ]
        for control in controls:
            control.blockSignals(True)

        self.date_from.clearDate()
        self.date_to.clearDate()
        self.stakes.setCurrentIndex(0)
        self.splash.setCurrentIndex(0)
        self.runs.setCurrentIndex(0)
        self.bb_contributed_min.clear()
        self.bb_contributed_max.clear()

        for control in controls:
            control.blockSignals(False)
        self.changed.emit()

    def refresh_stakes(
        self,
        db: TrackerDB,
    ):
        old = self.stakes.currentData()
        old_sb = self.stakes.currentData(Qt.UserRole + 1)

        self.stakes.blockSignals(True)
        self.stakes.clear()

        self.stakes.addItem(
            "All stakes",
            None,
        )
        for sb, bb in db.distinct_stakes():
            self.stakes.addItem(
                f"{fmt_money(sb)}/{fmt_money(bb)}",
                bb,
            )
            self.stakes.setItemData(
                self.stakes.count() - 1, sb, Qt.UserRole + 1,
            )

        for index in range(self.stakes.count()):
            if (
                self.stakes.itemData(index) == old
                and self.stakes.itemData(index, Qt.UserRole + 1) == old_sb
            ):
                self.stakes.setCurrentIndex(index)
                break

        self.stakes.blockSignals(False)

    def filters(self) -> dict:
        f = {}
        if self.date_from.has_date():
            f["date_from"] = (
                self.date_from.date()
                .toString("yyyy-MM-dd")
            )

        if self.date_to.has_date():
            f["date_to"] = (
                self.date_to.date()
                .toString("yyyy-MM-dd")
            )

        if self.stakes.currentData() is not None:
            f["bb_cents"] = int(
                self.stakes.currentData()
            )
            f["sb_cents"] = int(self.stakes.currentData(Qt.UserRole + 1))
        f["splash"] = {
            1: "only",
            2: "exclude",
        }.get(
            self.splash.currentIndex(),
            "all",
        )

        f["runs"] = {
            1: "once",
            2: "multi",
        }.get(
            self.runs.currentIndex(),
            "all",
        )

        contributed_min = self._optional_bb_value(
            self.bb_contributed_min
        )
        contributed_max = self._optional_bb_value(
            self.bb_contributed_max
        )
        if contributed_min is not None:
            f["contributed_bb_min"] = contributed_min
        if contributed_max is not None:
            f["contributed_bb_max"] = contributed_max

        return f

    @staticmethod
    def _optional_bb_value(control: QLineEdit) -> float | None:
        text = control.text().strip()
        if not text:
            return None
        try:
            return max(0.0, float(text))
        except ValueError:
            return None

    def summary(self) -> str:
        parts = []
        has_from = self.date_from.has_date()
        has_to = self.date_to.has_date()
        if has_from and has_to:
            date_from = self.date_from.date().toString(
                "yyyy-MM-dd"
            )
            date_to = self.date_to.date().toString(
                "yyyy-MM-dd"
            )
            if date_from == date_to:
                parts.append(
                    date_from
                )
            else:
                parts.append(
                    f"{date_from} to {date_to}"
                )
        elif has_from:
            parts.append(
                "From "
                + self.date_from.date().toString(
                    "yyyy-MM-dd"
                )
            )
        elif has_to:
            parts.append(
                "Through "
                + self.date_to.date().toString(
                    "yyyy-MM-dd"
                )
            )

        if self.stakes.currentData() is not None:
            parts.append(
                self.stakes.currentText()
            )
        if self.splash.currentIndex() == 1:
            parts.append(
                "Splash only"
            )
        elif self.splash.currentIndex() == 2:
            parts.append(
                "No splash pots"
            )
        if self.runs.currentIndex() == 1:
            parts.append(
                "Run once"
            )
        elif self.runs.currentIndex() == 2:
            parts.append(
                "Multi-run only"
            )
        contributed_min = self._optional_bb_value(
            self.bb_contributed_min
        )
        contributed_max = self._optional_bb_value(
            self.bb_contributed_max
        )
        if (
            contributed_min is not None
            and contributed_max is not None
        ):
            parts.append(
                "Contributed "
                f"{contributed_min:g}–{contributed_max:g} BB"
            )
        elif contributed_min is not None:
            parts.append(
                f"Contributed ≥ {contributed_min:g} BB"
            )
        elif contributed_max is not None:
            parts.append(
                f"Contributed ≤ {contributed_max:g} BB"
            )
        return " · ".join(parts) if parts else "All hands"


class FiltersDialog(QDialog):
    """Compact editor for the application-wide tracker filters."""

    def __init__(
        self,
        filters: FiltersBar,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            "Filters"
        )
        self.setMinimumWidth(
            520
        )

        lay = QVBoxLayout(self)
        help_text = QLabel(
            "These filters apply to Overview, Hands, Sessions, and Position. "
            "Changes are applied immediately."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet(
            "color: #9fc5f8;"
        )
        lay.addWidget(
            help_text
        )
        lay.addWidget(
            filters
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.Close
        )
        clear_button = buttons.addButton(
            "Clear all filters",
            QDialogButtonBox.ResetRole,
        )
        clear_button.clicked.connect(
            filters.clear_all
        )
        buttons.rejected.connect(
            self.reject
        )
        lay.addWidget(
            buttons
        )


class MainWindow(QMainWindow):
    def __init__(
        self,
        db_path: str,
        migration_progress=None,
    ):
        super().__init__()
        self.db_path = db_path
        self.db = TrackerDB(
            db_path,
            migration_progress=migration_progress,
        )

        self.settings = QSettings(
            "OpenAI",
            "CoinPokerTracker",
        )

        self.hero_name = self.settings.value(
            "hero_name",
            "Hero",
        )

        self.worker = None

        self.setWindowTitle(
            "CoinPoker Tracker v1.0.6"
        )
        self.resize(
            1280,
            800,
        )

        self._apply_theme()

        self.filters = FiltersBar(
            self.db
        )
        self.filters.changed.connect(
            self._filters_changed
        )
        self.filters_dialog = FiltersDialog(
            self.filters,
            self,
        )

        self.filter_summary_label = QLabel()
        self.filter_summary_label.setMaximumWidth(
            720
        )
        self.filter_summary_label.setToolTip(
            "Use the Filters menu to change application-wide filters."
        )

        self.import_progress = QProgressBar()
        self.import_progress.setMinimumWidth(260)
        self.import_progress.setTextVisible(True)
        self.import_progress.hide()

        self.statusBar().addPermanentWidget(
            self.filter_summary_label,
            1,
        )
        self.statusBar().addPermanentWidget(
            self.import_progress
        )

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_overview()
        self._build_hands()
        self._build_sessions()
        self._build_group_by()
        self._build_menu()

        self.refresh_all()
        if self.db.recalculation_errors:
            QMessageBox.warning(
                self,
                "Recalculation incomplete",
                f"{self.db.recalculation_errors:,} stored hand(s) "
                "could not be reparsed. "
                "The calculation version was NOT marked complete, "
                "so stale EV values will not be hidden. "
                "Please export/re-import those hands or send the raw "
                "hand(s) for parser support.",
            )
        elif self.db.recalculated_count:
            self.statusBar().showMessage(
                f"Recalculated "
                f"{self.db.recalculated_count:,} "
                f"existing hands with deterministic all-in EV.",
                15000,
            )
        if not evaluator_available():
            self.statusBar().showMessage(
                "eval7 is unavailable; preflop EV remains reproducible "
                "but recalculation will be slower.",
                30000,
            )

    def _apply_theme(self):
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

            QMenuBar::item:selected,
            QMenu::item:selected {
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
            QComboBox,
            QDateEdit,
            QLineEdit,
            QPlainTextEdit,
            QListWidget {
                background-color: #111c30;
                color: #edf4ff;
                border: 1px solid #334766;
                border-radius: 6px;
                padding: 5px 7px;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QComboBox:hover,
            QDateEdit:hover,
            QLineEdit:hover {
                border-color: #38bdf8;
            }

            QComboBox::drop-down,
            QDateEdit::drop-down {
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

    def closeEvent(
        self,
        event,
    ):
        self.db.close()
        super().closeEvent(event)

    def _build_menu(self):
        file_menu = self.menuBar().addMenu(
            "File"
        )
        import_menu = file_menu.addMenu(
            "Import"
        )

        a_file = QAction(
            "Hand-history file…",
            self,
        )

        a_folder = QAction(
            "Folder…",
            self,
        )

        a_file.triggered.connect(
            self.choose_file
        )
        a_folder.triggered.connect(
            self.choose_folder
        )

        import_menu.addAction(a_file)
        import_menu.addAction(a_folder)

        file_menu.addSeparator()

        rakeback = QAction(
            "Add/Edit Rakeback…",
            self,
        )
        rakeback.setToolTip(
            "Enter manual rakeback for a cash-game stake"
        )
        rakeback.triggered.connect(
            self.edit_rakeback
        )
        file_menu.addAction(
            rakeback
        )

        customize_cards = QAction(
            "Customize Overview cards…",
            self,
        )
        customize_cards.setToolTip(
            "Reorder, hide, or restore Overview stat cards"
        )
        customize_cards.triggered.connect(
            self.customize_overview_cards
        )
        file_menu.addAction(
            customize_cards
        )

        filters_menu = self.menuBar().addMenu(
            "Filters"
        )
        edit_filters = QAction(
            "Edit filters…",
            self,
        )
        edit_filters.triggered.connect(
            self.open_filters
        )
        filters_menu.addAction(
            edit_filters
        )

        self.clear_filters_action = QAction(
            "Clear all filters",
            self,
        )
        self.clear_filters_action.triggered.connect(
            self.filters.clear_all
        )
        filters_menu.addAction(
            self.clear_filters_action
        )

    def open_filters(self):
        self.filters.refresh_stakes(
            self.db
        )
        self.filters_dialog.exec()

    def _filters_changed(self):
        self.refresh_all()

    def _update_filter_summary(self):
        summary = self.filters.summary()
        active = summary != "All hands"
        self.filter_summary_label.setText(
            f"Filters: {summary}"
        )
        self.filter_summary_label.setStyleSheet(
            "padding: 2px 8px; font-weight: 700; color: "
            + (
                "#fbbf24;"
                if active
                else "#8fa9c9;"
            )
        )
        self.filter_summary_label.setToolTip(
            (
                "Active across Overview, Hands, Sessions, and Position: "
                + summary
                if active
                else "No filters are active. Use the Filters menu to narrow all tabs."
            )
        )
        if hasattr(
            self,
            "clear_filters_action",
        ):
            self.clear_filters_action.setEnabled(
                active
            )

    def _build_overview(self):
        w = QWidget()
        outer = QVBoxLayout(w)

        self.card_grid = QGridLayout()
        self.cards = {
            title: StatCard(title)
            for title in OVERVIEW_CARD_TITLES
        }

        (
            self.card_order,
            self.hidden_cards,
        ) = self._load_overview_card_layout()

        self._apply_overview_card_layout()

        outer.addLayout(
            self.card_grid
        )

        graph_controls = QHBoxLayout()
        graph_controls.addWidget(
            QLabel("Graph:")
        )

        self.graph_checks = {}
        graph_options = [
            (
                "net",
                "Net Won",
                "#2ecc71",
            ),
            (
                "net_post_rb",
                "Net Won post RB",
                "#CB00F5",
            ),
            (
                "showdown",
                "Won at showdown",
                "#3498db",
            ),
            (
                "allin_adj",
                "All-in Adj EV",
                "#f1c40f",
            ),
            (
                "nonshowdown",
                "Won without showdown",
                "#e74c3c",
            ),
        ]
        for key, label, color in graph_options:
            checkbox = QCheckBox(label)
            if key == "net_post_rb":
                checkbox.setToolTip(
                    "Net Won plus manual rakeback. Because rakeback is stored "
                    "as a cumulative amount, it is spread evenly across the "
                    "displayed hands for graphing."
                )

            stored = self.settings.value(
                f"overview/graph/{key}",
                True,
            )

            if isinstance(stored, str):
                checked = stored.lower() not in {
                    "0",
                    "false",
                    "no",
                    "off",
                }
            else:
                checked = bool(stored)
            checkbox.setChecked(
                checked
            )

            checkbox.setStyleSheet(
                f"QCheckBox {{ "
                f"color: {color}; "
                f"font-weight: 600; "
                f"}}"
            )

            checkbox.toggled.connect(
                lambda checked, k=key:
                self._graph_visibility_changed(
                    k,
                    checked,
                )
            )

            self.graph_checks[key] = checkbox
            graph_controls.addWidget(
                checkbox
            )

        graph_controls.addStretch(1)

        outer.addLayout(
            graph_controls
        )

        self.graph = ProfitGraph()

        for key, checkbox in self.graph_checks.items():
            self.graph.set_series_visible(
                key,
                checkbox.isChecked(),
            )

        outer.addWidget(
            self.graph,
            1,
        )
        # Subtle optional support link in the bottom-right
        # of the Overview tab.
        # Optional support button in the bottom-right of the Overview tab.
        support_row = QHBoxLayout()
        support_row.addStretch(1)

        self.support_button = QPushButton("☕ Buy me a coffee")
        self.support_button.setToolTip(
            "Support the development of CoinPoker Tracker"
        )
        self.support_button.setStyleSheet(
            """
            QPushButton {
                background-color: #2a3d5f;
                color: #f8fafc;
                border: 1px solid #7dd3fc;
                border-radius: 7px;
                padding: 6px 12px;
                font-weight: 600;
            }

            QPushButton:hover {
                background-color: #36527d;
                border-color: #bae6fd;
            }
            QPushButton:pressed {
                background-color: #22344f;
            }
            """
        )

        self.support_button.clicked.connect(
            lambda: os.startfile(
                "https://buymeacoffee.com/mleclerc182"
            )
        )

        support_row.addWidget(self.support_button)
        outer.addLayout(support_row)

        self.tabs.addTab(
            w,
            "Overview",
        )

    def _load_overview_card_layout(
        self,
    ) -> tuple[list[str], set[str]]:
        known = set(
            OVERVIEW_CARD_TITLES
        )

        try:
            raw_order = self.settings.value(
                "overview/card_order",
                "",
            )

            parsed_order = (
                json.loads(raw_order)
                if raw_order
                else []
            )
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            parsed_order = []

        order = []

        for title in (
            parsed_order
            if isinstance(
                parsed_order,
                list,
            )
            else []
        ):
            if (
                title in known
                and title not in order
            ):
                order.append(title)
        for title in OVERVIEW_CARD_TITLES:
            if title not in order:
                order.append(title)

        try:
            raw_hidden = self.settings.value(
                "overview/hidden_cards",
                "",
            )

            parsed_hidden = (
                json.loads(raw_hidden)
                if raw_hidden
                else []
            )
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            parsed_hidden = []

        hidden = (
            {
                title
                for title in parsed_hidden
                if title in known
            }
            if isinstance(
                parsed_hidden,
                list,
            )
            else set()
        )

        return order, hidden

    def _save_overview_card_layout(self):
        self.settings.setValue(
            "overview/card_order",
            json.dumps(
                self.card_order
            ),
        )

        self.settings.setValue(
            "overview/hidden_cards",
            json.dumps(
                sorted(
                    self.hidden_cards
                )
            ),
        )

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
            self.card_grid.addWidget(
                card,
                visible_index // 5,
                visible_index % 5,
            )

            visible_index += 1

        for col in range(5):
            self.card_grid.setColumnStretch(
                col,
                1,
            )

    def customize_overview_cards(self):
        dialog = OverviewCardsDialog(
            self.card_order,
            self.hidden_cards,
            self,
        )
        if (
            dialog.exec()
            != QDialog.Accepted
        ):
            return

        (
            self.card_order,
            self.hidden_cards,
        ) = dialog.layout_state()

        self._save_overview_card_layout()
        self._apply_overview_card_layout()

    def edit_rakeback(self):
        selected_bb_cents = None
        if hasattr(self, "filters"):
            selected_bb_cents = self.filters.filters().get(
                "bb_cents"
            )

        dialog = RakebackDialog(
            self.db,
            selected_bb_cents,
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        sb_cents, bb_cents, cents = dialog.saved_value()
        self.statusBar().showMessage(
            f"Saved {fmt_money(cents)} rakeback for "
            f"{fmt_money(sb_cents)}/{fmt_money(bb_cents)}.",
            5000,
        )
        self.refresh_all()

    def _graph_visibility_changed(
        self,
        key: str,
        checked: bool,
    ):
        self.settings.setValue(
            f"overview/graph/{key}",
            checked,
        )
        self.settings.sync()

        if hasattr(
            self,
            "graph",
        ):
            self.graph.set_series_visible(
                key,
                checked,
            )

    @staticmethod
    def _configure_table_columns(table: QTableWidget):
        """Set initial widths once, leaving later layout changes to the user."""
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setToolTip(
            "Click a heading to sort; drag headings to reorder or edges to resize."
        )
        table.resizeColumnsToContents()
        initial_widths = {
            "Date": 165, "Start": 165, "End": 165, "Hand": 115,
            "Stakes": 125, "Pos": 65, "Cards": 110, "Board(s)": 280,
            "Net Won": 105, "BB Won": 90, "AI Adj Net Won": 125,
        }
        for column in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(column)
            name = header_item.text()
            tooltip = HAND_TABLE_TOOLTIPS.get(name)
            if tooltip:
                header_item.setToolTip(tooltip)
            table.setColumnWidth(
                column, max(table.columnWidth(column), initial_widths.get(name, 90)),
            )

    @staticmethod
    def _apply_result_color(item: QTableWidgetItem, value: float):
        if value:
            item.setForeground(QColor(
                WINNING_TEXT_COLOR if value > 0 else LOSING_TEXT_COLOR
            ))

    @staticmethod
    def _add_hand_limit_control(layout: QHBoxLayout, reload_hands, context: str):
        label = QLabel("Show hands:")

        # Build this like OptionalDatePicker: field on the left,
        # dedicated ▼ button on the right.
        control = QWidget()
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(0)

        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setCompleter(None)
        combo.setMinimumWidth(120)
        combo.setAccessibleName(f"{context} hand display limit")
        combo.setToolTip(
            "Choose a preset or type a positive hand count (for example, 3,500). "
            "Press Enter or leave the field to load the latest matching hands. "
            "Current filters apply; column headings sort the loaded hands."
        )

        # Hide the combo's native drop-down area so the dedicated button is
        # the only arrow, matching OptionalDatePicker's split-field appearance.
        combo.setStyleSheet(
            """
            QComboBox {
                border-top-right-radius: 0;
                border-bottom-right-radius: 0;
                padding-right: 6px;
            }

            QComboBox::drop-down {
                border: none;
                width: 0px;
            }

            QComboBox::down-arrow {
                width: 0px;
                height: 0px;
            }
            """
        )

        editor = combo.lineEdit()
        editor.setStyleSheet(
            """
            QLineEdit {
                border: none;
                background: transparent;
                padding: 0;
            }
            """
        )

        drop_button = QPushButton("▼")
        drop_button.setFixedWidth(30)
        drop_button.setToolTip("Show preset hand counts")
        drop_button.setFocusPolicy(Qt.NoFocus)
        drop_button.clicked.connect(combo.showPopup)
        drop_button.setStyleSheet(
            """
            QPushButton {
                border-top-left-radius: 0;
                border-bottom-left-radius: 0;
                padding: 5px 4px;
                font-size: 9pt;
            }
            """
        )

        control_layout.addWidget(combo, 1)
        control_layout.addWidget(drop_button)

        for limit in HAND_LIMIT_OPTIONS:
            combo.addItem("All" if limit < 0 else f"{limit:,}", limit)

        combo.setCurrentIndex(combo.findData(DEFAULT_HAND_LIMIT))

        label.setBuddy(combo)
        layout.addWidget(label)
        layout.addWidget(control)

        # Keep convenient references alive/accessible from the returned combo.
        combo._drop_button = drop_button
        combo._split_control = control

        applied_limit = DEFAULT_HAND_LIMIT
        custom_index = None

        def apply_limit(limit: int):
            nonlocal applied_limit, custom_index

            text = "All" if limit < 0 else f"{limit:,}"
            was_blocked = combo.blockSignals(True)
            editor_was_blocked = editor.blockSignals(True)

            try:
                index = combo.findData(limit)

                if index < 0:
                    # Keep one reusable custom choice immediately before "All".
                    if custom_index is None:
                        custom_index = combo.findData(-1)
                        combo.insertItem(custom_index, text, limit)
                    else:
                        combo.setItemText(custom_index, text)
                        combo.setItemData(custom_index, limit)

                    index = custom_index

                combo.setCurrentIndex(index)
                combo.setEditText(text)
            finally:
                editor.blockSignals(editor_was_blocked)
                combo.blockSignals(was_blocked)

            QToolTip.hideText()

            changed = limit != applied_limit
            applied_limit = limit

            if changed:
                reload_hands()

        def select_limit(index: int):
            if index < 0:
                return

            limit = combo.itemData(index)

            if isinstance(limit, int) and (limit > 0 or limit == -1):
                apply_limit(limit)

        def commit_text():
            try:
                limit = parse_hand_limit(combo.currentText())
            except ValueError as exc:
                apply_limit(applied_limit)
                QToolTip.showText(
                    combo.mapToGlobal(QPoint(0, combo.height())),
                    str(exc),
                    combo,
                )
                return

            apply_limit(limit)

        combo.currentIndexChanged.connect(select_limit)
        # Activation also handles reselecting the current preset after typing.
        combo.activated.connect(select_limit)
        editor.editingFinished.connect(commit_text)

        return combo

    @staticmethod
    def _hand_count_text(shown: int, total: int) -> str:
        if shown < total:
            return f"Showing latest {shown:,} of {total:,} hands"
        return f"Showing {shown:,} of {total:,} hand{'s' if total != 1 else ''}"

    def _build_hands(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        toolbar = QHBoxLayout()

        self.delete_hands_button = QPushButton(
            "Delete selected hand(s)"
        )
        self.delete_hands_button.setToolTip(
            "Delete the selected hands from this tracker database"
        )

        self.delete_hands_button.clicked.connect(
            self.delete_selected_hands
        )

        toolbar.addWidget(
            self.delete_hands_button
        )
        replay_hint = QLabel(
            "Double-click a hand to open the replayer"
        )
        replay_hint.setStyleSheet(
            "color: #8fa9c9;"
        )
        toolbar.addWidget(replay_hint)
        toolbar.addStretch(1)

        lay.addLayout(toolbar)
        hand_controls = QHBoxLayout()
        self.hands_count_label = QLabel()
        self.hands_count_label.setStyleSheet("color: #9fc5f8;")
        hand_controls.addWidget(self.hands_count_label, 1)
        self.hand_limit_combo = self._add_hand_limit_control(
            hand_controls,
            lambda: self.refresh_hands(self.filters.filters()),
            "Hands",
        )
        lay.addLayout(hand_controls)

        split = QSplitter(
            Qt.Vertical
        )

        self.hand_table = QTableWidget(
            0,
            len(HAND_TABLE_HEADERS),
        )
        self.hand_table.setHorizontalHeaderLabels(
            HAND_TABLE_HEADERS
        )

        self._configure_table_columns(self.hand_table)
        header = (
            self.hand_table
            .horizontalHeader()
        )

        header.setSortIndicatorShown(
            True
        )

        header.setSectionsClickable(
            True
        )

        header.sectionClicked.connect(
            self._sort_hands_by_column
        )
        self._hand_sort_column = 0
        self._hand_sort_order = (
            Qt.DescendingOrder
        )

        header.setSortIndicator(
            self._hand_sort_column,
            self._hand_sort_order,
        )

        self.hand_table.setAlternatingRowColors(
            True
        )

        self.hand_table.setSelectionBehavior(
            QTableWidget.SelectRows
        )

        self.hand_table.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )
        self.hand_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )

        self.hand_table.setItemDelegateForColumn(
            4,
            CardSuitDelegate(
                self.hand_table
            ),
        )

        self.hand_table.setItemDelegateForColumn(
            5,
            CardSuitDelegate(
                self.hand_table
            ),
        )

        self.hand_table.itemSelectionChanged.connect(
            self.show_selected_hand
        )
        self.hand_table.cellDoubleClicked.connect(
            self.open_hand_replayer
        )
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)

        f = QFont("Consolas")
        f.setStyleHint(
            QFont.Monospace
        )

        self.raw.setFont(f)

        split.addWidget(
            self.hand_table
        )
        split.addWidget(
            self.raw
        )

        split.setSizes(
            [450, 260]
        )

        lay.addWidget(split)

        self.tabs.addTab(
            w,
            "Hands",
        )

    def _build_sessions(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        toolbar = QHBoxLayout()

        self.delete_sessions_button = QPushButton(
            "Delete selected session(s)"
        )

        self.delete_sessions_button.setToolTip(
            "Delete every hand contained in the selected "
            "session(s) from this tracker database"
        )

        self.delete_sessions_button.clicked.connect(
            self.delete_selected_sessions
        )
        toolbar.addWidget(
            self.delete_sessions_button
        )

        toolbar.addStretch(1)

        lay.addLayout(toolbar)

        self.session_table = QTableWidget(
            0,
            6,
        )

        self.session_table.setHorizontalHeaderLabels(
            [
                "Start",
                "End",
                "Duration",
                "Hands",
                "Net Won",
                "BB Won",
            ]
        )
        self._configure_table_columns(self.session_table)
        self.session_table.horizontalHeaderItem(4).setToolTip(
            "Combined net winnings for the hands in this session"
        )
        self.session_table.horizontalHeaderItem(5).setToolTip(
            "Sum of each hand's net winnings divided by its own big blind"
        )
        self.session_table.horizontalHeader().setSortIndicator(0, Qt.DescendingOrder)
        self.session_table.setSortingEnabled(True)

        self.session_table.setAlternatingRowColors(
            True
        )

        self.session_table.setSelectionBehavior(
            QTableWidget.SelectRows
        )

        self.session_table.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )

        self.session_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )
        self._session_rows = []

        self.session_table.cellClicked.connect(
            self.show_selected_session_hands
        )

        split = QSplitter(
            Qt.Vertical
        )
        split.addWidget(
            self.session_table
        )

        hands_panel = QWidget()
        hands_layout = QVBoxLayout(
            hands_panel
        )
        hands_layout.setContentsMargins(
            0,
            5,
            0,
            0,
        )
        self.session_hands_label = QLabel(
            "Select a session to view its hands"
        )
        self.session_hands_label.setStyleSheet(
            "color: #9fc5f8; font-weight: 700;"
        )
        self.session_hands_label.setWordWrap(True)
        hand_controls = QHBoxLayout()
        hand_controls.addWidget(self.session_hands_label, 1)
        self.session_hand_limit_combo = self._add_hand_limit_control(
            hand_controls, self.show_selected_session_hands, "Session",
        )
        hands_layout.addLayout(hand_controls)

        self.session_hand_table = QTableWidget(
            0,
            len(HAND_TABLE_HEADERS),
        )
        self.session_hand_table.setHorizontalHeaderLabels(
            HAND_TABLE_HEADERS
        )
        self._configure_table_columns(self.session_hand_table)
        session_hand_header = (
            self.session_hand_table
            .horizontalHeader()
        )
        session_hand_header.setSortIndicator(
            0,
            Qt.DescendingOrder,
        )
        self.session_hand_table.setAlternatingRowColors(
            True
        )
        self.session_hand_table.setSelectionBehavior(
            QTableWidget.SelectRows
        )
        self.session_hand_table.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        self.session_hand_table.setEditTriggers(
            QTableWidget.NoEditTriggers
        )
        self.session_hand_table.setItemDelegateForColumn(
            4,
            CardSuitDelegate(
                self.session_hand_table
            ),
        )
        self.session_hand_table.setItemDelegateForColumn(
            5,
            CardSuitDelegate(
                self.session_hand_table
            ),
        )
        self.session_hand_table.cellDoubleClicked.connect(
            self.open_hand_replayer
        )
        self.session_hand_table.setSortingEnabled(
            True
        )
        hands_layout.addWidget(
            self.session_hand_table
        )
        split.addWidget(
            hands_panel
        )
        split.setSizes(
            [310, 360]
        )
        lay.addWidget(
            split
        )

        self.tabs.addTab(
            w,
            "Sessions",
        )

    def _build_group_by(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        toolbar = QHBoxLayout()
        group_label = QLabel("Group by:")
        self.group_by_combo = QComboBox()
        self.group_by_combo.setMinimumWidth(180)
        self.group_by_combo.setAccessibleName("Group results by")
        self.group_by_combo.addItem("Position", "position")
        self.group_by_combo.addItem("Stakes", "stakes")
        self.group_by_combo.addItem("Starting Hands", "starting_hands")
        group_label.setBuddy(self.group_by_combo)
        toolbar.addWidget(group_label)
        toolbar.addWidget(self.group_by_combo)
        toolbar.addStretch(1)
        self.group_count_label = QLabel()
        toolbar.addWidget(self.group_count_label)
        lay.addLayout(toolbar)

        self.group_hint = QLabel()
        self.group_hint.setWordWrap(True)
        self.group_hint.setStyleSheet("color: #8fa9c9;")
        lay.addWidget(self.group_hint)

        self.group_table = QTableWidget(0, 0)
        self.group_table.setAlternatingRowColors(True)
        self.group_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.group_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.group_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.group_table.verticalHeader().setVisible(False)
        header = self.group_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        self._group_column_mode = None
        self._group_column_states = {}
        # Sort the cached data ourselves so the total remains the last row
        # in both directions. Header clicks do not query the database again.
        self._group_sorts = {
            "position": ("group", Qt.AscendingOrder),
            "stakes": ("group", Qt.AscendingOrder),
            "starting_hands": ("group", Qt.DescendingOrder),
        }
        self._group_rows = []
        self._group_total = {}
        self._group_display_rows = []
        self._selected_group_keys = set()
        self._group_filters = {}
        header.sectionClicked.connect(self._sort_groups_by_column)
        self.group_by_combo.currentIndexChanged.connect(
            lambda _index: self.refresh_group_by()
        )
        self.group_table.itemSelectionChanged.connect(self.show_selected_group_hands)

        self.group_splitter = QSplitter(Qt.Vertical)
        self.group_splitter.addWidget(self.group_table)
        hands_panel = QWidget()
        hands_layout = QVBoxLayout(hands_panel)
        hands_layout.setContentsMargins(0, 5, 0, 0)
        self.group_hands_label = QLabel("Select a group to view its hands")
        self.group_hands_label.setStyleSheet("color: #9fc5f8; font-weight: 700;")
        self.group_hands_label.setWordWrap(True)
        hand_controls = QHBoxLayout()
        hand_controls.addWidget(self.group_hands_label, 1)
        self.group_hand_limit_combo = self._add_hand_limit_control(
            hand_controls, self.show_selected_group_hands, "Group",
        )
        hands_layout.addLayout(hand_controls)

        self.group_hand_table = QTableWidget(0, len(HAND_TABLE_HEADERS))
        self.group_hand_table.setHorizontalHeaderLabels(HAND_TABLE_HEADERS)
        self._configure_table_columns(self.group_hand_table)
        hand_header = self.group_hand_table.horizontalHeader()
        hand_header.setSortIndicator(0, Qt.DescendingOrder)
        self.group_hand_table.setAlternatingRowColors(True)
        self.group_hand_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.group_hand_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.group_hand_table.setEditTriggers(QTableWidget.NoEditTriggers)
        for column in (4, 5):
            self.group_hand_table.setItemDelegateForColumn(
                column, CardSuitDelegate(self.group_hand_table),
            )
        self.group_hand_table.cellDoubleClicked.connect(self.open_hand_replayer)
        self.group_hand_table.setSortingEnabled(True)
        hands_layout.addWidget(self.group_hand_table)
        self.group_splitter.addWidget(hands_panel)
        self.group_splitter.setSizes([310, 360])
        lay.addWidget(self.group_splitter)
        self.tabs.addTab(w, "Group By")

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import CoinPoker hand history",
            "",
            "Text files (*.txt);;All files (*)",
        )

        if path:
            self.start_import(
                path,
                False,
            )

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Import CoinPoker hand-history folder",
        )

        if path:
            self.start_import(
                path,
                True,
            )

    def start_import(
        self,
        target: str,
        is_folder: bool,
    ):
        if (
            self.worker
            and self.worker.isRunning()
        ):
            QMessageBox.information(
                self,
                "Import running",
                "An import is already running.",
            )
            return

        self.statusBar().showMessage(
            f"Counting hands in {target}…"
        )
        self.import_progress.setRange(
            0,
            0,
        )

        self.import_progress.setFormat(
            "Counting hands…"
        )

        self.import_progress.show()

        self.worker = ImportWorker(
            self.db_path,
            target,
            is_folder,
            self.hero_name,
        )

        self.worker.progress_changed.connect(
            self.import_progress_changed
        )
        self.worker.finished_import.connect(
            self.import_finished
        )

        self.worker.failed.connect(
            self.import_failed
        )

        self.worker.start()

    def import_progress_changed(
        self,
        current: int,
        total: int,
        filename: str,
    ):
        if total > 0:
            self.import_progress.setRange(
                0,
                total,
            )
            self.import_progress.setValue(
                min(
                    current,
                    total,
                )
            )

            self.import_progress.setFormat(
                f"Importing hand "
                f"{current:,} / {total:,}"
            )

            self.statusBar().showMessage(
                f"Importing {filename} — "
                f"hand {current:,}/{total:,}"
            )
        else:
            self.import_progress.setRange(
                0,
                1,
            )

            self.import_progress.setValue(
                0
            )

            self.import_progress.setFormat(
                "No hands found"
            )

    def import_finished(
        self,
        added: int,
        duplicates: int,
        errors: list,
    ):
        self.import_progress.hide()
        self.statusBar().showMessage(
            f"Imported {added} new hands; "
            f"{duplicates} duplicates.",
            10000,
        )

        self.filters.refresh_stakes(
            self.db
        )
        self.refresh_all()
        if errors:
            QMessageBox.warning(
                self,
                "Import completed with parser warnings",
                "\n".join(
                    errors[:20]
                )
                + (
                    "\n…"
                    if len(errors) > 20
                    else ""
                ),
            )

    def import_failed(
        self,
        message: str,
    ):
        self.import_progress.hide()
        self.statusBar().showMessage(
            "Import failed",
            10000,
        )

        QMessageBox.critical(
            self,
            "Import failed",
            message,
        )

    def refresh_all(self):
        f = self.filters.filters()
        self._update_filter_summary()

        o = self.db.overview(f)

        vals = {
            "Hands": f"{o['hands']:,}",
            "Net Won": fmt_money(
                o["net_cents"]
            ),
            "Rakeback Amount": fmt_money(
                o["rakeback_cents"]
            ),
            "Net Won post RB": fmt_money(
                o["net_post_rb_cents"]
            ),
            "Splash won": fmt_money(
                o["splash_won_cents"]
            ),
            "bb/100": (
                f"{o['bb100']:.2f}"
            ),
            "bb/100 post RB": (
                f"{o['bb100_post_rb']:.2f}"
            ),
            "All-in Adj Net Won": fmt_money(
                o["allin_adj_cents"]
            ),
            "All-in Adj BB": (
                f"{o['allin_adj_bb']:.2f}"
            ),
            "Adj bb/100": (
                f"{o['allin_adj_bb100']:.2f}"
            ),
            "AI adj hands": (
                f"{o['allin_adjusted_hands']:,}"
            ),
            "VPIP": fmt_pct(
                o["vpip"]
            ),
            "PFR": fmt_pct(
                o["pfr"]
            ),
            "3-Bet": fmt_pct(
                o["three_bet"]
            ),
            "WWSF": fmt_pct(
                o["wwsf"]
            ),
            "WTSD": fmt_pct(
                o["wtsd"]
            ),
            "W$SD": fmt_pct(
                o["wsd"]
            ),
            "Splash hands": (
                f"{o['splash_hands']:,}"
            ),
            "RIT hands": (
                f"{o['multi_run_hands']:,}"
            ),
        }
        for k, v in vals.items():
            self.cards[k].value.setText(v)

        graph_rows = self.db.profit_points(f)

        net_changes = [
            float(
                r["hero_net_cents"]
            )
            for r in graph_rows
        ]

        # Rakeback is stored as one cumulative manual amount rather than
        # timestamped per hand. For the graph, spread the selected total evenly
        # across the displayed hands so the post-RB line starts at zero and its
        # final point exactly represents Net Won + Rakeback Amount.
        if net_changes:
            rakeback_total = int(o["rakeback_cents"])
            base_rb, extra_cents = divmod(
                rakeback_total,
                len(net_changes),
            )
            rakeback_changes = [
                float(base_rb + (1 if i < extra_cents else 0))
                for i in range(len(net_changes))
            ]
            net_post_rb_changes = [
                net_change + rb_change
                for net_change, rb_change in zip(
                    net_changes,
                    rakeback_changes,
                )
            ]
        else:
            net_post_rb_changes = []

        showdown_changes = [
            (
                float(
                    r["hero_net_cents"]
                )
                if r["hero_wtsd"]
                else 0.0
            )
            for r in graph_rows
        ]
        nonshowdown_changes = [
            (
                0.0
                if r["hero_wtsd"]
                else float(
                    r["hero_net_cents"]
                )
            )
            for r in graph_rows
        ]

        allin_adj_changes = [
            float(
                r["hero_allin_adj_cents"]
            )
            for r in graph_rows
        ]
        self.graph.set_series_changes(
            net=net_changes,
            net_post_rb=net_post_rb_changes,
            showdown=showdown_changes,
            allin_adj=allin_adj_changes,
            nonshowdown=nonshowdown_changes,
        )

        self.refresh_hands(f)
        self.refresh_sessions(f)
        self.refresh_group_by(f)

    def _sort_hands_by_column(
        self,
        column: int,
    ):
        descending_first = {
            0,
            1,
            2,
            4,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
        }
        if column == self._hand_sort_column:
            self._hand_sort_order = (
                Qt.AscendingOrder
                if self._hand_sort_order
                == Qt.DescendingOrder
                else Qt.DescendingOrder
            )

        else:
            self._hand_sort_column = column

            self._hand_sort_order = (
                Qt.DescendingOrder
                if column in descending_first
                else Qt.AscendingOrder
            )
        self.hand_table.horizontalHeader().setSortIndicator(
            column,
            self._hand_sort_order,
        )

        self.hand_table.sortItems(
            column,
            self._hand_sort_order,
        )

        if self.hand_table.rowCount():
            self.hand_table.selectRow(0)

    @staticmethod
    def _hand_sort_values(
        r,
        boards: str,
    ) -> list:
        try:
            hand_no = int(
                r["hand_id"]
            )
        except (
            TypeError,
            ValueError,
        ):
            hand_no = str(
                r["hand_id"]
            )
        net_cents = float(r["hero_net_cents"] or 0)
        allin_adj_cents = float(r["hero_allin_adj_cents"] or 0)
        bb_cents = int(r["bb_cents"] or 0)
        net_bb = net_cents / bb_cents if bb_cents else float("-inf")
        allin_adj_bb = (
            allin_adj_cents / bb_cents if bb_cents else float("-inf")
        )
        return [
            r["started_at"],
            hand_no,
            (
                int(
                    r["bb_cents"]
                ),
                int(
                    r["sb_cents"]
                ),
            ),
            (
                r["hero_position"]
                or ""
            ).casefold(),
            hole_card_sort_key(
                r["hero_cards"]
                or ""
            ),
            boards.casefold(),
            int(
                r["run_count"]
            ),
            int(
                r["splash_cents"]
                or 0
            ),
            int(
                r["hero_splash_won_cents"]
                or 0
            ),
            int(
                r["total_pot_cents"]
                or 0
            ),
            (
                float(
                    int(r["hero_contributed_cents"])
                    - int(r["hero_returned_cents"])
                )
                / int(r["bb_cents"])
                if r["bb_cents"]
                else float("-inf")
            ),
            net_cents,
            net_bb,
            (
                float(
                    r["hero_allin_equity"]
                )
                if (
                    r["hero_allin_adjusted"]
                    and r["hero_allin_equity"]
                    is not None
                )
                else -1.0
            ),
            allin_adj_cents,
            allin_adj_bb,
        ]

    def _populate_hand_table(
        self,
        table: QTableWidget,
        rows,
    ):
        table.setRowCount(0)
        table.setRowCount(
            len(rows)
        )
        for i, r in enumerate(rows):
            boards = " | ".join(
                x
                for x in [
                    r["board1"],
                    r["board2"],
                    r["board3"],
                ]
                if x
            )
            hero_contributed_bb = (
                (
                    int(r["hero_contributed_cents"])
                    - int(r["hero_returned_cents"])
                )
                / int(r["bb_cents"])
                if r["bb_cents"]
                else None
            )
            hero_net_cents = float(r["hero_net_cents"] or 0)
            hero_allin_adj_cents = float(r["hero_allin_adj_cents"] or 0)
            bb_cents = int(r["bb_cents"] or 0)
            hero_net_bb = hero_net_cents / bb_cents if bb_cents else None
            hero_allin_adj_bb = (
                hero_allin_adj_cents / bb_cents if bb_cents else None
            )
            allin_prefix = "~" if r["hero_allin_estimated"] else ""
            vals = [
                r["started_at"][:19],
                r["hand_id"],
                (
                    f"{fmt_money(r['sb_cents'])}/"
                    f"{fmt_money(r['bb_cents'])}"
                ),
                r["hero_position"]
                or "",
                normalize_hole_cards(
                    r["hero_cards"]
                    or ""
                ),
                boards,
                str(
                    r["run_count"]
                ),
                (
                    f"{r['splash_type']} "
                    f"{fmt_money(r['splash_cents'])}"
                    if r["splash_cents"]
                    else ""
                ),
                (
                    fmt_money(
                        r["hero_splash_won_cents"]
                    )
                    if r["hero_splash_won_cents"]
                    else ""
                ),
                fmt_money(
                    r["total_pot_cents"]
                ),
                (
                    f"{hero_contributed_bb:.2f}"
                    if hero_contributed_bb is not None
                    else ""
                ),
                fmt_money(
                    r["hero_net_cents"]
                ),
                (
                    f"{hero_net_bb:.2f}"
                    if hero_net_bb is not None
                    else ""
                ),
                (
                    (
                        "~"
                        if r["hero_allin_estimated"]
                        else ""
                    )
                    + (
                        f"{float(r['hero_allin_equity']) * 100:.2f}%"
                    )
                    if (
                        r["hero_allin_adjusted"]
                        and r["hero_allin_equity"]
                        is not None
                    )
                    else ""
                ),
                (
                    allin_prefix
                    + fmt_money(round(hero_allin_adj_cents))
                ),
                (
                    allin_prefix
                    + f"{hero_allin_adj_bb:.2f}"
                    if hero_allin_adj_bb is not None
                    else ""
                ),
            ]
            sort_values = (
                self._hand_sort_values(
                    r,
                    boards,
                )
            )
            for j, (
                value,
                sort_value,
            ) in enumerate(
                zip(
                    vals,
                    sort_values,
                )
            ):
                item = SortableTableWidgetItem(
                    str(value),
                    sort_value,
                )
                if j in {NET_WON_COLUMN, BB_WON_COLUMN}:
                    self._apply_result_color(item, hero_net_cents)
                elif j in {AI_ADJ_NET_WON_COLUMN, AI_ADJ_BB_COLUMN}:
                    self._apply_result_color(item, hero_allin_adj_cents)
                table.setItem(i, j, item)

    def refresh_hands(
        self,
        f,
    ):
        rows = self.db.hands(f, limit=self.hand_limit_combo.currentData())
        self.hands_count_label.setText(
            self._hand_count_text(len(rows), self.db.hand_count(f))
        )
        self._populate_hand_table(
            self.hand_table,
            rows,
        )
        if rows:
            self.hand_table.sortItems(
                self._hand_sort_column,
                self._hand_sort_order,
            )

            self.hand_table.horizontalHeader().setSortIndicator(
                self._hand_sort_column,
                self._hand_sort_order,
            )

            self.hand_table.selectRow(0)

        else:
            self.raw.clear()

    def show_selected_hand(self):
        row = self.hand_table.currentRow()
        if row < 0:
            return

        item = self.hand_table.item(
            row,
            1,
        )

        if item:
            self.raw.setPlainText(
                self.db.raw_hand(
                    item.text()
                )
            )

    def open_hand_replayer(
        self,
        row: int,
        _column: int,
    ):
        source_table = self.sender()
        table = (
            source_table
            if isinstance(
                source_table,
                QTableWidget,
            )
            else self.hand_table
        )
        item = table.item(
            row,
            1,
        )
        if item is None:
            return

        try:
            hand = self.db.replay_hand(
                item.text()
            )
            if hand is None:
                raise ValueError(
                    "The selected hand is no longer in the database."
                )
            replay = build_replay(hand)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Hand Replayer",
                "This hand could not be prepared for replay.\n\n"
                f"{type(exc).__name__}: {exc}",
            )
            return

        dialog = HandReplayerDialog(
            replay,
            self,
        )
        dialog.exec()

    def delete_selected_hands(self):
        rows = sorted(
            {
                index.row()
                for index
                in self.hand_table
                .selectionModel()
                .selectedRows()
            }
        )

        hand_ids = [
            self.hand_table
            .item(row, 1)
            .text()
            for row in rows
            if self.hand_table.item(
                row,
                1,
            )
            is not None
        ]
        if not hand_ids:
            QMessageBox.information(
                self,
                "Delete hands",
                "Select one or more hands first.",
            )
            return

        if len(hand_ids) == 1:
            detail = (
                f"hand #{hand_ids[0]}"
            )
        else:
            detail = (
                f"{len(hand_ids)} "
                f"selected hands"
            )
        answer = QMessageBox.question(
            self,
            "Delete hands",
            f"Delete {detail} from the tracker?\n\n"
            "This removes the hand and its stored actions/results "
            "from the local database. "
            "If you later import the original hand-history file "
            "again, the hand can be imported again.",
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        deleted = self.db.delete_hands(
            hand_ids
        )

        self.raw.clear()

        self.filters.refresh_stakes(
            self.db
        )
        self.refresh_all()

        self.statusBar().showMessage(
            f"Deleted {deleted} hand"
            f"{'s' if deleted != 1 else ''}.",
            8000,
        )

    def refresh_sessions(
        self,
        f,
    ):
        rows = self.db.sessions(
            30,
            f,
        )

        table = self.session_table
        was_blocked = table.blockSignals(True)
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        try:
            self._session_rows = rows
            table.clearSelection()
            table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                seconds = max(0, (r["end"] - r["start"]).total_seconds())
                minutes = int(seconds / 60)
                vals = [
                    r["start"].strftime("%Y-%m-%d %H:%M"),
                    r["end"].strftime("%Y-%m-%d %H:%M"),
                    f"{minutes // 60}h {minutes % 60}m",
                    str(r["hands"]),
                    fmt_money(r["net_cents"]),
                    f"{r['net_bb']:.1f}",
                ]
                sort_values = [
                    r["start"], r["end"], seconds,
                    r["hands"], r["net_cents"], r["net_bb"],
                ]
                for j, (value, sort_value) in enumerate(zip(vals, sort_values)):
                    item = SortableTableWidgetItem(value, sort_value)
                    if j in {4, 5}:
                        self._apply_result_color(item, sort_value)
                    if j == 0:
                        # This index travels with the row when Qt sorts it.
                        item.setData(Qt.UserRole, i)
                    table.setItem(i, j, item)
        finally:
            # Reapply the chosen sort only after every cell is populated.
            table.setSortingEnabled(True)
            table.blockSignals(was_blocked)
            table.setUpdatesEnabled(True)
        self.show_selected_session_hands()

    def _sessions_for_rows(self, rows) -> list[dict]:
        """Resolve visible rows to their sessions after sorting or header moves."""
        sessions = []
        for row in rows:
            item = self.session_table.item(row, 0)
            index = item.data(Qt.UserRole) if item is not None else None
            if isinstance(index, int) and 0 <= index < len(self._session_rows):
                sessions.append(self._session_rows[index])
        return sessions

    def show_selected_session_hands(
        self,
        clicked_row: int | None = None,
        _column: int | None = None,
    ):
        selected_rows = sorted(
            {
                index.row()
                for index
                in self.session_table
                .selectionModel()
                .selectedRows()
            }
        )
        if (
            clicked_row is not None
            and clicked_row >= 0
            and clicked_row not in selected_rows
        ):
            selected_rows.append(
                clicked_row
            )
            selected_rows.sort()
        sessions = self._sessions_for_rows(selected_rows)
        hand_ids = list(
            dict.fromkeys(
                hand_id
                for session in sessions
                for hand_id in session.get(
                    "hand_ids",
                    [],
                )
            )
        )
        try:
            rows = self.db.hands_by_ids(
                hand_ids, limit=self.session_hand_limit_combo.currentData(),
            )

            self.session_hand_table.setSortingEnabled(
                False
            )
            self._populate_hand_table(
                self.session_hand_table,
                rows,
            )
            self.session_hand_table.setSortingEnabled(
                True
            )
        except Exception as exc:
            self.session_hand_table.setSortingEnabled(
                False
            )
            self.session_hand_table.setRowCount(
                0
            )
            self.session_hand_table.setSortingEnabled(
                True
            )
            self.session_hands_label.setText(
                "Could not load this session's hands"
            )
            QMessageBox.warning(
                self,
                "Session hands",
                "The selected session's hands could not be loaded.\n\n"
                "Make sure both ui.py and database.py are from the "
                "same download.\n\n"
                f"{type(exc).__name__}: {exc}",
            )
            return

        if not sessions:
            self.session_hands_label.setText(
                "Select a session to view its hands"
            )
        elif len(sessions) == 1:
            session = sessions[0]
            self.session_hands_label.setText(
                "Hands in session · "
                f"{session['start']:%Y-%m-%d %H:%M}–"
                f"{session['end']:%H:%M} · "
                + self._hand_count_text(len(rows), len(hand_ids))
            )
        else:
            self.session_hands_label.setText(
                f"Hands in {len(sessions)} selected sessions · "
                + self._hand_count_text(len(rows), len(hand_ids))
            )

        if rows:
            self.session_hand_table.selectRow(
                0
            )

    def delete_selected_sessions(self):
        rows = sorted(
            {
                index.row()
                for index
                in self.session_table
                .selectionModel()
                .selectedRows()
            }
        )
        selected_sessions = self._sessions_for_rows(rows)

        if not selected_sessions:
            QMessageBox.information(
                self,
                "Delete sessions",
                "Select one or more sessions first.",
            )
            return
        hand_ids = list(
            dict.fromkeys(
                hand_id
                for session
                in selected_sessions
                for hand_id
                in session.get(
                    "hand_ids",
                    [],
                )
            )
        )
        if not hand_ids:
            QMessageBox.information(
                self,
                "Delete sessions",
                "The selected session contains no stored hands.",
            )
            return

        session_count = len(
            selected_sessions
        )
        answer = QMessageBox.question(
            self,
            "Delete sessions",
            f"Delete {session_count} selected session"
            f"{'s' if session_count != 1 else ''} and "
            f"all {len(hand_ids)} hand"
            f"{'s' if len(hand_ids) != 1 else ''} inside "
            f"{'them' if session_count != 1 else 'it'}?\n\n"
            "This permanently removes those hands and their stored "
            "actions/results from the local database. "
            "Re-importing the original hand-history file will add them back.",
            QMessageBox.Yes
            | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        deleted = self.db.delete_hands(
            hand_ids
        )

        self.raw.clear()

        self.filters.refresh_stakes(
            self.db
        )
        self.refresh_all()

        self.statusBar().showMessage(
            f"Deleted {session_count} session"
            f"{'s' if session_count != 1 else ''} "
            f"containing {deleted} hand"
            f"{'s' if deleted != 1 else ''}.",
            10000,
        )

    def refresh_group_by(self, filters: dict | None = None):
        group_by = self.group_by_combo.currentData()
        if filters is None:
            filters = self.filters.filters()
        self._selected_group_keys = {
            key for key in self._selected_group_keys
            if key[0] == group_by
        }
        self._group_filters = dict(filters)
        self._group_rows, self._group_total = self.db.grouped_results(group_by, filters)
        if group_by == "stakes":
            for row in self._group_rows:
                row["group"] = f"{fmt_money(row['sb_cents'])}/{fmt_money(row['bb_cents'])}"
        self._group_total["group"] = (
            "All stakes (filtered)" if group_by == "stakes" else "Total (filtered)"
        )
        self._group_total["hand_type"] = ""
        self.group_count_label.setText(
            f"{self._group_total['hands']:,} hands · {len(self._group_rows):,} groups"
        )
        hint = (
            "Current filters apply. Select one or more groups to view their hands below. "
            "Click a heading to sort; drag headings to reorder or edges to resize."
        )
        if group_by == "starting_hands":
            hint += " AA = pair, AKs = suited, AKo = offsuit."
        if not self._group_rows:
            hint = "No hands match the current filters. " + hint
        self.group_hint.setText(hint)

        columns = GROUP_BY_COLUMNS[group_by]
        header = self.group_table.horizontalHeader()
        columns_changed = self._group_column_mode != group_by
        if columns_changed and self._group_column_mode is not None:
            self._group_column_states[self._group_column_mode] = header.saveState()
        was_blocked = self.group_table.blockSignals(True)
        try:
            self.group_table.clearContents()
            self.group_table.setColumnCount(len(columns))
            labels = {
                "position": "Position", "stakes": "Stakes", "starting_hands": "Starting Hand",
            }
            self.group_table.setHorizontalHeaderLabels([
                labels[group_by] if key == "group" else GROUP_COLUMN_DETAILS[key][0]
                for key in columns
            ])
            for column, key in enumerate(columns):
                tooltip = (
                    "Sort by position, stake size, or starting-card ranks"
                    if key == "group" else GROUP_COLUMN_DETAILS[key][2]
                )
                self.group_table.horizontalHeaderItem(column).setToolTip(tooltip)
            if columns_changed:
                # Each grouping has different columns. Restore its own layout
                # before rendering so its saved sort choice takes precedence.
                state = self._group_column_states.get(group_by)
                layout_restored = state is not None and header.restoreState(state)
                if not layout_restored:
                    for column in range(len(columns)):
                        header.moveSection(header.visualIndex(column), column)
            self._render_group_rows()
            if columns_changed:
                if not layout_restored:
                    self.group_table.resizeColumnsToContents()
                self._group_column_mode = group_by
        finally:
            self.group_table.blockSignals(was_blocked)
        self.show_selected_group_hands()

    def _group_row_key(self, row: dict) -> tuple:
        """Identify a group independently of its current sorted row number."""
        group_by = self.group_by_combo.currentData()
        if row is self._group_total:
            return (group_by, None)
        if group_by == "stakes":
            return (group_by, (row["sb_cents"], row["bb_cents"]))
        return (group_by, row["group"])

    def show_selected_group_hands(self):
        selected_rows = sorted(
            {
                index.row()
                for index
                in self.group_table
                .selectionModel()
                .selectedRows()
            }
        )
        groups = [
            self._group_display_rows[row]
            for row in selected_rows
            if 0 <= row < len(self._group_display_rows)
        ]
        self._selected_group_keys = {
            self._group_row_key(group)
            for group in groups
        }

        table = self.group_hand_table
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        try:
            limit = self.group_hand_limit_combo.currentData()
            total_selected = any(
                group is self._group_total
                for group in groups
            )

            if not groups:
                rows = []
                expected_hands = 0
            elif total_selected:
                rows = self.db.hands_for_group(
                    self.group_by_combo.currentData(),
                    None,
                    filters=self._group_filters,
                    limit=limit,
                )
                expected_hands = self._group_total["hands"]
            else:
                per_group_limit = limit if limit > 0 else -1
                hand_ids = list(
                    dict.fromkeys(
                        row["hand_id"]
                        for group in groups
                        for row in self.db.hands_for_group(
                            *self._group_row_key(group),
                            filters=self._group_filters,
                            limit=per_group_limit,
                        )
                    )
                )
                rows = self.db.hands_by_ids(
                    hand_ids,
                    limit=limit,
                )
                expected_hands = sum(
                    group["hands"]
                    for group in groups
                )

            self._populate_hand_table(table, rows)
            if not groups:
                self.group_hands_label.setText(
                    "Select one or more groups to view their hands"
                )
            elif total_selected:
                self.group_hands_label.setText(
                    "All filtered hands · "
                    + self._hand_count_text(
                        len(rows),
                        expected_hands,
                    )
                    + " · Double-click a hand to open the replayer"
                )
            elif len(groups) == 1:
                self.group_hands_label.setText(
                    f"{groups[0]['group']} · "
                    + self._hand_count_text(
                        len(rows),
                        expected_hands,
                    )
                    + " · Double-click a hand to open the replayer"
                )
            else:
                self.group_hands_label.setText(
                    f"Hands in {len(groups)} selected groups · "
                    + self._hand_count_text(
                        len(rows),
                        expected_hands,
                    )
                    + " · Double-click a hand to open the replayer"
                )
        except Exception as exc:
            table.setRowCount(0)
            self.group_hands_label.setText(
                "Could not load the selected groups' hands"
            )
            QMessageBox.warning(
                self,
                "Group hands",
                "The selected groups' hands could not be loaded.\n\n"
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            # Re-enabling sorting reapplies the user's current column/order.
            table.setSortingEnabled(True)
            table.setUpdatesEnabled(True)
        if table.rowCount():
            table.selectRow(0)

    def _sort_groups_by_column(self, column: int):
        group_by = self.group_by_combo.currentData()
        key = GROUP_BY_COLUMNS[group_by][column]
        old_key, old_order = self._group_sorts[group_by]
        if key == old_key:
            order = Qt.AscendingOrder if old_order == Qt.DescendingOrder else Qt.DescendingOrder
        elif key == "hand_type" or (key == "group" and group_by != "starting_hands"):
            order = Qt.AscendingOrder
        else:
            order = Qt.DescendingOrder
        self._group_sorts[group_by] = (key, order)
        self._render_group_rows()

    @staticmethod
    def _group_sort_value(row: dict, key: str, group_by: str):
        if key != "group":
            value = row[key]
            return value.casefold() if isinstance(value, str) else value
        if group_by == "stakes":
            return (row["bb_cents"], row["sb_cents"])
        if group_by == "starting_hands":
            return starting_hand_sort_key(row["group"])
        positions = (
            "EP1", "EP2", "EP3", "EP4", "EP5", "EP6", "UTG", "UTG+1", "UTG+2",
            "MP", "HJ", "CO", "BTN", "BTN/SB", "SB", "BB",
        )
        position = row["group"]
        return (positions.index(position) if position in positions else len(positions), position)

    def _render_group_rows(self):
        group_by = self.group_by_combo.currentData()
        columns = GROUP_BY_COLUMNS[group_by]
        key, order = self._group_sorts[group_by]
        rows = sorted(
            self._group_rows,
            key=lambda row: self._group_sort_value(row, key, group_by),
            reverse=order == Qt.DescendingOrder,
        )
        self._group_display_rows = [*rows, self._group_total]
        selected_keys = set(self._selected_group_keys)
        was_blocked = self.group_table.blockSignals(True)
        try:
            self.group_table.horizontalHeader().setSortIndicator(columns.index(key), order)
            self.group_table.setRowCount(0)
            self.group_table.setRowCount(len(self._group_display_rows))
            selected_rows = []
            for row_index, row in enumerate(self._group_display_rows):
                self._populate_group_summary_row(row_index, row, columns)
                if self._group_row_key(row) in selected_keys:
                    selected_rows.append(row_index)

            selection_model = self.group_table.selectionModel()
            selection_model.clearSelection()
            model = self.group_table.model()
            flags = (
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows
            )
            for row_index in selected_rows:
                selection_model.select(
                    model.index(row_index, 0),
                    flags,
                )

            self._selected_group_keys = {
                self._group_row_key(self._group_display_rows[row_index])
                for row_index in selected_rows
            }
            if selected_rows:
                selection_model.setCurrentIndex(
                    model.index(selected_rows[0], 0),
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )
        finally:
            self.group_table.blockSignals(was_blocked)

    def _populate_group_summary_row(self, row_index: int, row: dict, columns):
        is_total = row is self._group_total
        for column, column_key in enumerate(columns):
            value = row[column_key]
            kind = "text" if column_key == "group" else GROUP_COLUMN_DETAILS[column_key][1]
            if kind == "money":
                # Adjusted winnings may contain fractions of a cent.
                text = fmt_money(round(value))
            elif kind == "integer":
                text = f"{value:,}"
            elif kind == "percent":
                text = fmt_pct(value)
            elif kind == "number":
                text = f"{value:.2f}"
            else:
                text = str(value)
            item = QTableWidgetItem(text)
            item.setTextAlignment(
                (Qt.AlignLeft if kind == "text" else Qt.AlignRight) | Qt.AlignVCenter
            )
            if is_total:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setBackground(QColor("#1b2a46"))
                item.setToolTip(
                    "Combined results for all hands matching the current filters. "
                    "Rates use the combined hand and opportunity counts."
                )
            if column_key in {
                "net_cents", "net_bb", "bb100", "allin_adj_cents", "allin_adj_bb100",
            }:
                self._apply_result_color(item, value)
            self.group_table.setItem(row_index, column, item)
