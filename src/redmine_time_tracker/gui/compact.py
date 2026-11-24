"""Small always-on-top window for the running track."""

from __future__ import annotations

import time
from datetime import datetime
from html import escape

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import LocalTrack, TrackStatus, format_hm, round_up_minutes
from .theme import muted_style, panel_style


class CompactWindow(QWidget):
    pause_requested = Signal(int)
    publish_requested = Signal(int)
    restore_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.track_id = 0
        self._base_elapsed = 0
        self._mono_started = time.monotonic()
        self._running = False
        self._drag_offset: QPoint | None = None

        self.setFixedWidth(340)
        self.setStyleSheet(panel_style(self, "CompactWindow"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.title_label = QLabel("Нет активного трека")
        self.title_label.setToolTip("Перетащите окно мышью")
        top.addWidget(self.title_label, stretch=1)

        self.restore_btn = QPushButton("Развернуть")
        self.restore_btn.setToolTip("Вернуться в основное окно (Esc)")
        self.restore_btn.clicked.connect(self.restore_requested.emit)
        top.addWidget(self.restore_btn)
        layout.addLayout(top)

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet(muted_style(self))
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.time_label = QLabel("00:00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet("font-family: monospace; font-size: 34px; font-weight: bold;")
        layout.addWidget(self.time_label)

        buttons = QHBoxLayout()
        self.pause_btn = QPushButton("Пауза")
        self.pause_btn.clicked.connect(lambda: self.pause_requested.emit(self.track_id))
        buttons.addWidget(self.pause_btn)

        self.publish_btn = QPushButton("Опубликовать")
        self.publish_btn.clicked.connect(lambda: self.publish_requested.emit(self.track_id))
        buttons.addWidget(self.publish_btn)
        layout.addLayout(buttons)

        self._set_idle()

    def set_track(self, track: LocalTrack | None) -> None:
        """Update the content without showing or hiding the window."""
        if track is None or track.status is not TrackStatus.RUNNING:
            self._set_idle()
            return

        self.track_id = track.id or 0
        self._running = True
        self._base_elapsed = max(0, int(track.elapsed_seconds))
        if track.started_at:
            self._base_elapsed += max(0, int((datetime.now() - track.started_at).total_seconds()))
        self._mono_started = time.monotonic()

        self.title_label.setText(f"#{track.issue_id} {escape(track.issue_subject)}")
        description = escape(track.description) if track.description else "без описания"
        self.detail_label.setText(f"{escape(track.activity_name)} · {description}")
        self.pause_btn.setEnabled(True)
        self.publish_btn.setEnabled(True)
        self.update_display()

    def _set_idle(self) -> None:
        self._running = False
        self.track_id = 0
        self.title_label.setText("Нет активного трека")
        self.detail_label.setText("Запустите трек в основном окне")
        self.time_label.setText("00:00:00")
        self.pause_btn.setEnabled(False)
        self.publish_btn.setEnabled(False)

    def current_seconds(self) -> int:
        total = self._base_elapsed
        if self._running:
            total += int(time.monotonic() - self._mono_started)
        return max(0, total)

    def update_display(self) -> None:
        total = self.current_seconds()
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        if self._running:
            self.publish_btn.setToolTip(
                f"Будет опубликовано {format_hm(round_up_minutes(total))} ч"
            )

    def restore_position(self, position: object) -> None:
        if isinstance(position, QPoint):
            self.move(position)

    # ------------------------------------------------------------------
    # Frameless dragging and Esc to restore
    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.restore_requested.emit()
            return
        super().keyPressEvent(event)
