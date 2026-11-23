"""Widgets used by the main window."""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import (
    Issue,
    LocalTrack,
    TimeEntry,
    TrackStatus,
    format_hm,
    round_up_minutes,
)
from .theme import muted_style, panel_style

GOLD = "#B8860B"
GREEN = "#28A745"
YELLOW = "#C77700"
RED = "#D0021B"


def progress_color(percent: float) -> str:
    if percent >= 100:
        return GOLD
    if percent >= 70:
        return GREEN
    if percent >= 40:
        return YELLOW
    return RED


class MetricsWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setSpacing(16)

        self.today = self._create_card("Сегодня")
        self.week = self._create_card("Неделя")
        self.month = self._create_card("Месяц")

        layout.addWidget(self.today)
        layout.addWidget(self.week)
        layout.addWidget(self.month)
        layout.addStretch()

    def _create_card(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        card_layout = QVBoxLayout(frame)
        card_layout.setContentsMargins(12, 8, 12, 8)

        title_label = QLabel(f"<b>{title}</b>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title_label)

        value_label = QLabel("—")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        value_label.setToolTip("Опубликованное время в Redmine за период")
        card_layout.addWidget(value_label)

        frame.value_label = value_label  # type: ignore[attr-defined]
        return frame

    def update_metric(self, frame: QFrame, spent: float, planned: float) -> None:
        percent = (spent / planned * 100) if planned else 0.0
        color = progress_color(percent)
        frame.value_label.setText(  # type: ignore[attr-defined]
            f"<span style='color:{color};'>{spent:.1f}h / {planned:.1f}h ({percent:.0f}%)</span>"
        )


class TrackWidget(QWidget):
    start_requested = Signal(int)
    pause_requested = Signal(int)
    edit_requested = Signal(int)
    publish_requested = Signal(int)
    cancel_requested = Signal(int)

    def __init__(self, track: LocalTrack, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.track_id = track.id or 0
        self._base_elapsed = 0
        self._mono_started = time.monotonic()
        self._running = False
        self._build_ui()
        self.refresh(track)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label, stretch=1)

        self.time_label = QLabel("00:00:00")
        self.time_label.setStyleSheet("font-family: monospace; font-size: 16px;")
        layout.addWidget(self.time_label)

        self.start_btn = QPushButton("▶ Старт")
        self.start_btn.clicked.connect(lambda: self.start_requested.emit(self.track_id))
        layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("⏸ Пауза")
        self.pause_btn.clicked.connect(lambda: self.pause_requested.emit(self.track_id))
        layout.addWidget(self.pause_btn)

        self.edit_btn = QPushButton("✎")
        self.edit_btn.setToolTip("Изменить параметры трека")
        self.edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.track_id))
        layout.addWidget(self.edit_btn)

        self.publish_btn = QPushButton("⬆ Опубликовать")
        self.publish_btn.clicked.connect(lambda: self.publish_requested.emit(self.track_id))
        layout.addWidget(self.publish_btn)

        self.cancel_btn = QPushButton("✕")
        self.cancel_btn.setToolTip("Отменить трек")
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self.track_id))
        layout.addWidget(self.cancel_btn)

    def refresh(self, track: LocalTrack) -> None:
        """Reset the running clock using the values stored in the database."""
        self.track_id = track.id or 0
        self._running = track.status is TrackStatus.RUNNING
        self._base_elapsed = max(0, int(track.elapsed_seconds))
        if self._running and track.started_at:
            # Time between the last heartbeat and building this widget.
            self._base_elapsed += max(0, int((datetime.now() - track.started_at).total_seconds()))
        self._mono_started = time.monotonic()

        continuation = ""
        if track.source_time_entry_id:
            continuation = (
                f" <span style='color:#17A2B8;'>(продолжение #{track.source_time_entry_id})</span>"
            )
        self.info_label.setText(
            f"<b>{track.activity_name}</b>{continuation} | "
            f"{track.date.strftime('%d.%m.%Y')}<br>"
            f"{track.description or '<i>без описания</i>'}"
        )
        self.start_btn.setEnabled(not self._running)
        self.pause_btn.setEnabled(self._running)
        self.update_display()

    def _current_seconds(self) -> int:
        total = self._base_elapsed
        if self._running:
            total += int(time.monotonic() - self._mono_started)
        return max(0, total)

    def update_display(self) -> None:
        total = self._current_seconds()
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        self.publish_btn.setToolTip(f"Будет опубликовано {format_hm(round_up_minutes(total))} ч")


class ExistingEntryWidget(QWidget):
    continue_requested = Signal(int)

    def __init__(self, entry: TimeEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.time_entry_id = entry.id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        info = QLabel(
            f"<b>{entry.activity_name}</b> | {entry.spent_on.strftime('%d.%m.%Y')} | "
            f"{entry.hours:.2f} ч<br>{entry.comments or '<i>без описания</i>'}"
        )
        info.setWordWrap(True)
        layout.addWidget(info, stretch=1)

        button = QPushButton("▶ Продолжить")
        button.setToolTip("Создать черновик на основе этой записи")
        button.clicked.connect(lambda: self.continue_requested.emit(self.time_entry_id))
        layout.addWidget(button)


class IssueWidget(QFrame):
    add_track_requested = Signal(int)
    continue_track_requested = Signal(int, int)
    continue_redmine_entry_requested = Signal(int, int)
    pause_track_requested = Signal(int)
    edit_track_requested = Signal(int)
    publish_track_requested = Signal(int)
    cancel_track_requested = Signal(int)

    def __init__(self, issue: Issue, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.issue_id = issue.id
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(panel_style(self, "IssueWidget"))

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        header.addWidget(self.title_label, stretch=1)

        self.local_label = QLabel()
        self.local_label.setStyleSheet(muted_style(self))
        header.addWidget(self.local_label)

        self.meta_label = QLabel()
        header.addWidget(self.meta_label)
        layout.addLayout(header)

        self.existing_layout = QVBoxLayout()
        self.existing_layout.setSpacing(4)
        layout.addLayout(self.existing_layout)

        self.tracks_layout = QVBoxLayout()
        self.tracks_layout.setSpacing(4)
        layout.addLayout(self.tracks_layout)

        add_button = QPushButton("+ Новый трек")
        add_button.clicked.connect(lambda: self.add_track_requested.emit(self.issue_id))
        layout.addWidget(add_button)

        self.update_issue(issue)

    def update_issue(self, issue: Issue) -> None:
        suffix = ""
        if issue.local_only:
            suffix = " <span style='color:#C77700;'>(нет в списке открытых задач)</span>"
        self.title_label.setText(f"<b>{issue.display_name}</b>{suffix}")

        percent = issue.progress_percent
        color = progress_color(percent)
        self.meta_label.setText(
            f"Затрачено: {issue.total_spent_hours:.1f}h / "
            f"{issue.estimated_hours or 0:.1f}h "
            f"(<span style='color:{color};'>{percent:.0f}%</span>)"
        )

    def set_existing_entries(self, entries: list[TimeEntry]) -> None:
        self._clear(self.existing_layout)
        if not entries:
            return
        self.existing_layout.addWidget(QLabel("<b>Существующие треки:</b>"))
        for entry in entries:
            widget = ExistingEntryWidget(entry)
            widget.continue_requested.connect(
                lambda entry_id, issue_id=self.issue_id: self.continue_redmine_entry_requested.emit(
                    issue_id, entry_id
                )
            )
            self.existing_layout.addWidget(widget)

    def set_tracks(self, tracks: list[LocalTrack]) -> None:
        self._clear(self.tracks_layout)
        pending_seconds = sum(track.current_elapsed_seconds() for track in tracks)
        self.local_label.setText(
            f"Локально: {format_hm(round_up_minutes(pending_seconds))}" if pending_seconds else ""
        )
        for track in tracks:
            widget = TrackWidget(track)
            widget.start_requested.connect(
                lambda track_id, issue_id=self.issue_id: self.continue_track_requested.emit(
                    issue_id, track_id
                )
            )
            widget.pause_requested.connect(self.pause_track_requested.emit)
            widget.edit_requested.connect(self.edit_track_requested.emit)
            widget.publish_requested.connect(self.publish_track_requested.emit)
            widget.cancel_requested.connect(self.cancel_track_requested.emit)
            self.tracks_layout.addWidget(widget)

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def track_widgets(self) -> list[TrackWidget]:
        widgets: list[TrackWidget] = []
        for index in range(self.tracks_layout.count()):
            item = self.tracks_layout.itemAt(index)
            if item is not None and isinstance(item.widget(), TrackWidget):
                widgets.append(item.widget())  # type: ignore[arg-type]
        return widgets
