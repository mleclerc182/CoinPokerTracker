from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .handtable import SUIT_COLORS, SUIT_SYMBOLS
from .replay import ReplayFrame, ReplayHand, format_chips


class PokerTableWidget(QWidget):
    """Paint one immutable replay frame as a compact poker table."""

    def __init__(self, replay: ReplayHand, parent=None):
        super().__init__(parent)
        self.replay = replay
        self.frame = replay.frames[0]
        self.setMinimumSize(780, 410)

    def set_frame(self, frame: ReplayFrame) -> None:
        self.frame = frame
        self.update()

    @staticmethod
    def _card_parts(card: str) -> tuple[str, str] | None:
        token = (card or "").strip()
        if len(token) != 2:
            return None
        rank, suit = token[0].upper(), token[1].lower()
        if rank not in "23456789TJQKA" or suit not in SUIT_SYMBOLS:
            return None
        return rank, suit

    def _draw_card(
        self,
        painter: QPainter,
        rect: QRectF,
        card: str = "",
        *,
        hidden: bool = False,
    ) -> None:
        painter.save()
        painter.setPen(QPen(QColor("#dbe7f7"), 1))
        painter.setBrush(QColor("#f8fafc" if not hidden else "#173968"))
        painter.drawRoundedRect(rect, 4, 4)

        if hidden:
            inset = rect.adjusted(4, 4, -4, -4)
            painter.setPen(QPen(QColor("#69a9ff"), 1))
            painter.setBrush(QColor("#214d85"))
            painter.drawRoundedRect(inset, 3, 3)
        else:
            parts = self._card_parts(card)
            if parts:
                rank, suit = parts
                painter.setPen(
                    QColor(
                        "#111111" if suit == "s"
                        else "#0000FF" if suit == "d"
                        else "#FF0000" if suit == "h"
                        else "#008000"
                    )
                )
                font = painter.font()
                font.setBold(True)
                font.setPointSize(max(8, int(rect.height() * 0.28)))
                painter.setFont(font)
                painter.drawText(
                    rect,
                    Qt.AlignCenter,
                    rank + SUIT_SYMBOLS[suit],
                )
        painter.restore()

    def _draw_board(
        self,
        painter: QPainter,
        center_x: float,
        y: float,
        board: str,
        label: str,
    ) -> None:
        cards = board.split()
        card_w, card_h, gap = 48.0, 66.0, 7.0
        total_w = max(1, len(cards)) * card_w + max(0, len(cards) - 1) * gap
        start_x = center_x - total_w / 2

        painter.setPen(QColor("#b8d2c5"))
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(start_x - 76, y + 21, 66, 22),
            Qt.AlignRight | Qt.AlignVCenter,
            label,
        )
        for index, card in enumerate(cards):
            self._draw_card(
                painter,
                QRectF(start_x + index * (card_w + gap), y, card_w, card_h),
                card,
            )

    def _draw_seat(
        self,
        painter: QPainter,
        center: QPointF,
        table_center: QPointF,
        seat,
    ) -> None:
        width, height = 204.0, 94.0
        rect = QRectF(
            center.x() - width / 2,
            center.y() - height / 2,
            width,
            height,
        )
        is_active = seat.player == self.frame.active_player
        is_hero = seat.player == self.replay.hero_name
        is_folded = seat.player in self.frame.folded

        painter.save()
        if is_folded:
            painter.setOpacity(0.48)
        border = "#38bdf8" if is_active else ("#fbbf24" if is_hero else "#4b607e")
        painter.setPen(QPen(QColor(border), 2 if is_active or is_hero else 1))
        painter.setBrush(QColor("#13223a" if not is_active else "#19365a"))
        painter.drawRoundedRect(rect, 9, 9)

        cards_text = self.frame.cards.get(seat.player, "")
        card_tokens = cards_text.split()[:2]
        card_w, card_h = 31.0, 42.0
        card_y = rect.top() + 43
        card_x = rect.right() - 73
        for index in range(2):
            shown = index < len(card_tokens)
            self._draw_card(
                painter,
                QRectF(card_x + index * 35, card_y, card_w, card_h),
                card_tokens[index] if shown else "",
                hidden=not shown,
            )

        name_font = painter.font()
        name_font.setBold(True)
        name_font.setPointSize(11)
        painter.setFont(name_font)
        painter.setPen(QColor("#ffffff"))
        name_rect = QRectF(rect.left() + 11, rect.top() + 8, 146, 22)
        name = painter.fontMetrics().elidedText(
            seat.player,
            Qt.ElideRight,
            int(name_rect.width()),
        )
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, name)

        detail_font = painter.font()
        detail_font.setBold(False)
        detail_font.setPointSize(9)
        painter.setFont(detail_font)
        painter.setPen(QColor("#9eb4d2"))
        position = seat.position or f"Seat {seat.seat_no}"
        if seat.is_button:
            position += "  •  D"
        painter.drawText(
            QRectF(rect.left() + 11, rect.top() + 30, 138, 19),
            Qt.AlignLeft | Qt.AlignVCenter,
            position,
        )
        painter.setPen(QColor("#dcecff"))
        painter.drawText(
            QRectF(rect.left() + 11, rect.top() + 59, 101, 21),
            Qt.AlignLeft | Qt.AlignVCenter,
            format_chips(self.frame.stacks.get(seat.player, 0)),
        )
        painter.restore()

        bet = self.frame.street_bets.get(seat.player, 0)
        if bet > 0:
            bet_center = QPointF(
                center.x() * 0.69 + table_center.x() * 0.31,
                center.y() * 0.69 + table_center.y() * 0.31,
            )
            bet_rect = QRectF(bet_center.x() - 50, bet_center.y() - 15, 100, 30)
            painter.save()
            painter.setPen(QPen(QColor("#f6c85f"), 1))
            painter.setBrush(QColor("#59451c"))
            painter.drawRoundedRect(bet_rect, 11, 11)
            painter.setPen(QColor("#fff3c4"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(bet_rect, Qt.AlignCenter, format_chips(bet))
            painter.restore()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#08111f"))

        width = float(self.width())
        height = float(self.height())
        table_center = QPointF(width / 2, height / 2)
        table_rect = QRectF(
            125,
            52,
            max(350.0, width - 250),
            max(240.0, height - 104),
        )

        shadow = table_rect.translated(0, 7)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 80))
        painter.drawEllipse(shadow)
        painter.setPen(QPen(QColor("#557a68"), 5))
        painter.setBrush(QColor("#174a38"))
        painter.drawEllipse(table_rect)
        inner = table_rect.adjusted(12, 12, -12, -12)
        painter.setPen(QPen(QColor("#2c6a53"), 2))
        painter.setBrush(QColor("#123c2f"))
        painter.drawEllipse(inner)

        visible_boards = [
            (run_number, board)
            for run_number, board in enumerate(self.frame.boards, 1)
            if board
        ]
        if visible_boards:
            row_gap = 84
            total_height = (len(visible_boards) - 1) * row_gap
            first_y = table_center.y() - 48 - total_height / 2
            for index, (run_number, board) in enumerate(visible_boards):
                label = f"Run {run_number}" if len(self.frame.boards) > 1 else "Board"
                self._draw_board(
                    painter,
                    table_center.x(),
                    first_y + index * row_gap,
                    board,
                    label,
                )

        pot_rect = QRectF(table_center.x() - 100, table_center.y() + 65, 200, 38)
        painter.setPen(QPen(QColor("#65d6a4"), 1))
        painter.setBrush(QColor("#0c2a21"))
        painter.drawRoundedRect(pot_rect, 14, 14)
        painter.setPen(QColor("#d9fff0"))
        pot_font = painter.font()
        pot_font.setBold(True)
        pot_font.setPointSize(11)
        painter.setFont(pot_font)
        painter.drawText(
            pot_rect,
            Qt.AlignCenter,
            f"Pot  {format_chips(self.frame.pot_cents)}",
        )

        if self.replay.splash_cents:
            splash_rect = QRectF(
                pot_rect.left(),
                pot_rect.bottom() + 6,
                pot_rect.width(),
                32,
            )
            painter.setPen(QPen(QColor("#fbbf24"), 1))
            painter.setBrush(QColor("#6b3514"))
            painter.drawRoundedRect(splash_rect, 11, 11)
            painter.setPen(QColor("#fff3c4"))
            splash_font = painter.font()
            splash_font.setBold(True)
            splash_font.setPointSize(10)
            painter.setFont(splash_font)
            splash_name = (self.replay.splash_type or "SPLASH").upper()
            painter.drawText(
                splash_rect,
                Qt.AlignCenter,
                f"{splash_name}  {format_chips(self.replay.splash_cents)}",
            )

        seat_count = max(1, len(self.replay.seats))
        radius_x = max(120.0, width / 2 - 103)
        radius_y = max(94.0, height / 2 - 48)
        for index, seat in enumerate(self.replay.seats):
            angle = math.pi / 2 + (2 * math.pi * index / seat_count)
            center = QPointF(
                table_center.x() + radius_x * math.cos(angle),
                table_center.y() + radius_y * math.sin(angle),
            )
            self._draw_seat(painter, center, table_center, seat)


class HandReplayerDialog(QDialog):
    """Modal hand replayer with mouse, keyboard, timer, and slider controls."""

    def __init__(self, replay: ReplayHand, parent=None):
        super().__init__(parent)
        self.replay = replay
        self._index = 0
        self._playing = False

        self.setWindowTitle(f"Hand Replayer — #{replay.hand_id}")
        self.resize(1080, 720)
        self.setMinimumSize(900, 640)
        self.setStyleSheet(
            """
            QDialog { background: #08111f; color: #e8eefc; }
            QLabel { color: #e8eefc; }
            QFrame#replayPanel {
                background: #101b2e;
                border: 1px solid #2c3d59;
                border-radius: 9px;
            }
            QPushButton {
                min-width: 48px;
                padding: 9px 13px;
                border-radius: 6px;
                border: 1px solid #3b82f6;
                background: #1e3a5f;
                color: #f4f8ff;
                font-weight: 700;
            }
            QPushButton:hover { background: #285184; }
            QPushButton:disabled { color: #64748b; border-color: #31405a; background: #172033; }
            QComboBox {
                background: #111c30;
                color: #edf4ff;
                border: 1px solid #334766;
                border-radius: 5px;
                padding: 7px 10px;
                font-size: 10pt;
            }
            QSlider::groove:horizontal { height: 7px; background: #253650; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 2px; }
            QSlider::handle:horizontal {
                width: 19px; margin: -6px 0; border-radius: 9px;
                background: #dbeafe; border: 1px solid #60a5fa;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(f"Hand #{replay.hand_id}")
        title_font = QFont(title.font())
        title_font.setPointSize(title_font.pointSize() + 6)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch(1)
        stakes = QLabel(
            f"{replay.game}   {format_chips(replay.sb_cents)}/{format_chips(replay.bb_cents)}"
        )
        stakes.setStyleSheet("color: #9fc5f8; font-weight: 700;")
        stakes_font = QFont(stakes.font())
        stakes_font.setPointSize(stakes_font.pointSize() + 2)
        stakes.setFont(stakes_font)
        header.addWidget(stakes)
        root.addLayout(header)

        self.table = PokerTableWidget(replay)
        root.addWidget(self.table, 1)

        action_panel = QFrame()
        action_panel.setObjectName("replayPanel")
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(17, 11, 17, 11)
        action_layout.setSpacing(3)
        self.step_label = QLabel()
        self.step_label.setStyleSheet("color: #8fa9c9; font-size: 10pt;")
        self.action_label = QLabel()
        self.action_label.setWordWrap(True)
        action_font = QFont(self.action_label.font())
        action_font.setPointSize(action_font.pointSize() + 2)
        action_font.setBold(True)
        self.action_label.setFont(action_font)
        action_layout.addWidget(self.step_label)
        action_layout.addWidget(self.action_label)
        root.addWidget(action_panel)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, max(0, len(replay.frames) - 1))
        self.slider.valueChanged.connect(self._show_frame)
        root.addWidget(self.slider)

        controls = QHBoxLayout()
        self.first_button = QPushButton("|◀")
        self.previous_button = QPushButton("◀")
        self.play_button = QPushButton("Play")
        self.next_button = QPushButton("▶")
        self.last_button = QPushButton("▶|")
        self.first_button.setToolTip("First step (Home)")
        self.previous_button.setToolTip("Previous step (Left arrow)")
        self.play_button.setToolTip("Play/pause (Space)")
        self.next_button.setToolTip("Next step (Right arrow)")
        self.last_button.setToolTip("Last step (End)")
        self.first_button.clicked.connect(lambda: self._seek(0))
        self.previous_button.clicked.connect(lambda: self._seek(self._index - 1))
        self.play_button.clicked.connect(self.toggle_playback)
        self.next_button.clicked.connect(lambda: self._seek(self._index + 1))
        self.last_button.clicked.connect(lambda: self._seek(len(self.replay.frames) - 1))
        controls.addStretch(1)
        for button in (
            self.first_button,
            self.previous_button,
            self.play_button,
            self.next_button,
            self.last_button,
        ):
            controls.addWidget(button)
        controls.addSpacing(14)
        controls.addWidget(QLabel("Speed"))
        self.speed = QComboBox()
        self.speed.addItem("0.5×", 1800)
        self.speed.addItem("1×", 1000)
        self.speed.addItem("1.5×", 650)
        self.speed.addItem("2×", 400)
        self.speed.setCurrentIndex(1)
        self.speed.currentIndexChanged.connect(self._speed_changed)
        controls.addWidget(self.speed)
        controls.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        controls.addWidget(close_button)
        root.addLayout(controls)

        hint = QLabel("Double-click a hand to open • Left/Right step • Space plays or pauses")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color: #6f86a5; font-size: 9pt;")
        root.addWidget(hint)

        self.timer = QTimer(self)
        self.timer.setInterval(int(self.speed.currentData()))
        self.timer.timeout.connect(self._advance)

        self._shortcuts = [
            QShortcut("Left", self, lambda: self._seek(self._index - 1)),
            QShortcut("Right", self, lambda: self._seek(self._index + 1)),
            QShortcut("Home", self, lambda: self._seek(0)),
            QShortcut(
                "End",
                self,
                lambda: self._seek(len(self.replay.frames) - 1),
            ),
            QShortcut("Space", self, self.toggle_playback),
        ]
        self._show_frame(0)

    def _speed_changed(self) -> None:
        self.timer.setInterval(int(self.speed.currentData()))

    def _seek(self, index: int) -> None:
        self.slider.setValue(max(0, min(index, len(self.replay.frames) - 1)))

    def _show_frame(self, index: int) -> None:
        self._index = index
        frame = self.replay.frames[index]
        self.table.set_frame(frame)
        run = f" · Run {frame.run_index}" if len(frame.boards) > 1 else ""
        self.step_label.setText(
            f"Step {index + 1} of {len(self.replay.frames)} · {frame.street.title()}{run}"
        )
        self.action_label.setText(frame.action_text)
        self.first_button.setEnabled(index > 0)
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < len(self.replay.frames) - 1)
        self.last_button.setEnabled(index < len(self.replay.frames) - 1)
        if index >= len(self.replay.frames) - 1 and self._playing:
            self._set_playing(False)

    def _advance(self) -> None:
        if self._index >= len(self.replay.frames) - 1:
            self._set_playing(False)
            return
        self._seek(self._index + 1)

    def _set_playing(self, playing: bool) -> None:
        self._playing = playing
        self.play_button.setText("Pause" if playing else "Play")
        if playing:
            self.timer.start()
        else:
            self.timer.stop()

    def toggle_playback(self) -> None:
        if not self._playing and self._index >= len(self.replay.frames) - 1:
            self._seek(0)
        self._set_playing(not self._playing)

    def closeEvent(self, event) -> None:
        self._set_playing(False)
        super().closeEvent(event)
