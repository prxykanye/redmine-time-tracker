"""Local publication history."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..database import Database
from ..models import LocalTrack, format_hm, round_up_minutes
from .theme import muted_style


class HistoryWidget(QWidget):
    HEADERS = ("Дата", "Задача", "Вид деятельности", "Часы", "Запись", "Описание")

    def __init__(
        self,
        database: Database,
        base_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.base_url = base_url
        self._tracks: list[LocalTrack] = []

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Период:"))
        self.period_combo = QComboBox()
        self.period_combo.addItem("Текущий месяц", "month")
        self.period_combo.addItem("Последние 500 записей", "all")
        self.period_combo.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.period_combo)

        self.refresh_btn = QPushButton("🔄 Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)

        controls.addStretch()
        self.total_label = QLabel("")
        controls.addWidget(self.total_label)
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(list(self.HEADERS))
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 300)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 70)
        self.table.setColumnWidth(4, 80)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._open_entry)
        layout.addWidget(self.table)

        hint = QLabel("Двойной клик по строке открывает запись времени в Redmine.")
        hint.setStyleSheet(muted_style(self))
        layout.addWidget(hint)

        self.refresh()

    def refresh(self) -> None:
        mode = self.period_combo.currentData()
        if mode == "month":
            today = date.today()
            self._tracks = self.database.list_published_between(today.replace(day=1), today)
        else:
            self._tracks = self.database.list_published(limit=500)
        self._fill()

    def _fill(self) -> None:
        self.table.setRowCount(len(self._tracks))
        total_minutes = 0
        for row, track in enumerate(self._tracks):
            minutes = round_up_minutes(track.elapsed_seconds)
            total_minutes += minutes
            values = (
                track.date.strftime("%d.%m.%Y"),
                f"#{track.issue_id} {track.issue_subject}",
                track.activity_name,
                format_hm(minutes),
                f"#{track.redmine_entry_id}" if track.redmine_entry_id else "—",
                track.description,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setData(Qt.ItemDataRole.UserRole, track.redmine_entry_id)
                self.table.setItem(row, column, item)

        if self._tracks:
            self.total_label.setText(
                f"Итого: {format_hm(total_minutes)} ч · записей: {len(self._tracks)}"
            )
        else:
            self.total_label.setText("Нет опубликованных треков за период")

    def _open_entry(self, row: int, _column: int) -> None:
        item = self.table.item(row, 4)
        if item is None:
            return
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        if not entry_id or not self.base_url:
            return
        QDesktopServices.openUrl(QUrl(f"{self.base_url}/time_entries/{entry_id}/edit"))
