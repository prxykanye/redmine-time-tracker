"""Reusable dialogs for the application."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
)

from ..config import AppConfig, ConfigError, normalize_url
from ..models import Activity, LocalTrack, format_hm, format_hms, round_up_minutes
from ..tracking import OrphanTrack, RecoveryMode
from .theme import muted_style


class ApiKeyDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Redmine API Key")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Введите ваш Redmine API ключ:"))
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setText(config.redmine_api_key)
        layout.addWidget(self.key_input)

        hint = QLabel(
            "Ключ хранится в файле .env в каталоге настроек с правами доступа только для владельца."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(muted_style(self))
        layout.addWidget(hint)

        self.show_checkbox = QCheckBox("Показать ключ")
        self.show_checkbox.toggled.connect(self._toggle_visibility)
        layout.addWidget(self.show_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_visibility(self, checked: bool) -> None:
        self.key_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def _save(self) -> None:
        value = self.key_input.text().strip()
        if not value:
            QMessageBox.warning(self, "API ключ", "Ключ не может быть пустым.")
            return
        self.config.set_redmine_api_key(value)
        self.accept()

    def api_key(self) -> str:
        return self.key_input.text().strip()


class AddTrackDialog(QDialog):
    def __init__(
        self,
        issue_display: str,
        activities: list[Activity],
        current_activity_id: int | None = None,
        description: str = "",
        track_date: date | None = None,
        title: str = "Добавить трек",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"Задача: {issue_display}"))

        layout.addWidget(QLabel("Вид деятельности:"))
        self.activity_combo = QComboBox()
        default_index = 0
        for activity in activities:
            self.activity_combo.addItem(activity.name, activity.id)
            if activity.is_default:
                default_index = self.activity_combo.count() - 1
        self.activity_combo.setCurrentIndex(default_index)
        if current_activity_id is not None:
            for index in range(self.activity_combo.count()):
                if self.activity_combo.itemData(index) == current_activity_id:
                    self.activity_combo.setCurrentIndex(index)
                    break
        layout.addWidget(self.activity_combo)

        layout.addWidget(QLabel("Описание:"))
        self.description_input = QTextEdit()
        self.description_input.setPlainText(description)
        self.description_input.setMaximumHeight(80)
        layout.addWidget(self.description_input)

        layout.addWidget(QLabel("Дата:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        if track_date is not None:
            self.date_edit.setDate(QDate(track_date.year, track_date.month, track_date.day))
        else:
            self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        layout.addWidget(self.date_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def activity_id(self) -> int:
        return int(self.activity_combo.currentData())

    def activity_name(self) -> str:
        return self.activity_combo.currentText()

    def description(self) -> str:
        return self.description_input.toPlainText().strip()

    def track_date(self) -> date:
        value = self.date_edit.date()
        return date(value.year(), value.month(), value.day())


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, require_url: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.require_url = require_url
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(450)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Redmine URL:"))
        self.url_input = QLineEdit(config.redmine_url)
        self.url_input.setPlaceholderText("https://redmine.example.com")
        layout.addWidget(self.url_input)

        layout.addWidget(QLabel("API ключ хранится отдельно и меняется через пункт «API ключ»."))

        self.refresh_checkbox = QCheckBox("Обновлять задачи при запуске")
        self.refresh_checkbox.setChecked(config.refresh_on_start)
        layout.addWidget(self.refresh_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        try:
            url = normalize_url(self.url_input.text())
        except ConfigError as exc:
            QMessageBox.warning(self, "Настройки", str(exc))
            return
        if not url and self.require_url:
            QMessageBox.warning(self, "Настройки", "Укажите URL сервера Redmine.")
            return
        self.config.redmine_url = url
        self.config.refresh_on_start = self.refresh_checkbox.isChecked()
        self.accept()


class ConfirmationDialog(QDialog):
    def __init__(self, title: str, message: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)

        label = QLabel(message)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Подтвердить")
        buttons.button(QDialogButtonBox.StandardButton.No).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PublishTrackDialog(QDialog):
    CREATE = "create"
    UPDATE = "update"

    def __init__(
        self,
        track: LocalTrack,
        allow_update: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Опубликовать трек")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        summary = QLabel(
            f"<b>Задача #{track.issue_id}</b><br>"
            f"Дата: {track.date.strftime('%d.%m.%Y')}<br>"
            f"Вид деятельности: {track.activity_name}<br>"
            f"Описание: {track.description or '—'}<br>"
            f"Зафиксировано: {format_hms(track.current_elapsed_seconds())}<br>"
            f"Будет опубликовано: <b>{format_hm(round_up_minutes(track.current_elapsed_seconds()))} ч</b>"
            " (округление вверх до 5 минут)"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        self._group: QButtonGroup | None = None
        self.create_radio: QRadioButton | None = None
        self.update_radio: QRadioButton | None = None
        if allow_update and track.source_time_entry_id:
            layout.addWidget(QLabel("<b>Что сделать с записью в Redmine:</b>"))
            self._group = QButtonGroup(self)
            self.create_radio = QRadioButton("Создать новую запись")
            self.create_radio.setChecked(True)
            self.update_radio = QRadioButton(
                f"Обновить существующую запись #{track.source_time_entry_id}"
            )
            self._group.addButton(self.create_radio)
            self._group.addButton(self.update_radio)
            layout.addWidget(self.create_radio)
            layout.addWidget(self.update_radio)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Опубликовать")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mode(self) -> str:
        if self.update_radio is not None and self.update_radio.isChecked():
            return self.UPDATE
        return self.CREATE


class RecoveryDialog(QDialog):
    def __init__(self, orphan: OrphanTrack, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Незакрытый трек")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        track = orphan.track
        message = QLabel(
            f"Трек по задаче <b>#{track.issue_id}</b> остался запущенным после "
            "закрытия приложения.<br><br>"
            f"Учтённое время: {format_hms(track.elapsed_seconds)}<br>"
            f"Простой без приложения: {format_hms(orphan.idle_seconds)}"
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        layout.addWidget(QLabel("Что сделать с этим треком:"))
        self.until_heartbeat = QRadioButton(
            f"Учесть время до последней отметки: {format_hms(orphan.recoverable_seconds)}"
        )
        self.until_heartbeat.setChecked(True)
        self.until_now = QRadioButton(
            f"Учесть всё время, включая простой: {format_hms(orphan.total_seconds)}"
        )
        layout.addWidget(self.until_heartbeat)
        layout.addWidget(self.until_now)

        hint = QLabel("В обоих случаях трек будет поставлен на паузу.")
        hint.setStyleSheet(muted_style(self))
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Оставить как есть")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mode(self) -> RecoveryMode:
        if self.until_now.isChecked():
            return RecoveryMode.UNTIL_NOW
        return RecoveryMode.UNTIL_HEARTBEAT
