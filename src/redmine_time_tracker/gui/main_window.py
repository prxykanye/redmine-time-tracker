"""Main application window."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from ..database import Database
from ..models import Activity, Issue, LocalTrack, TrackStatus
from ..redmine_client import RedmineClient, RedmineError
from ..tracking import ORPHAN_THRESHOLD, RecoveryMode, TrackService
from .dialogs import (
    AddTrackDialog,
    ApiKeyDialog,
    ConfirmationDialog,
    HistoryDialog,
    PublishTrackDialog,
    RecoveryDialog,
    SettingsDialog,
)
from .widgets import IssueWidget, MetricsWidget

DAILY_WORK_HOURS = 8.0
HEARTBEAT_INTERVAL_MS = 30_000

logger = logging.getLogger(__name__)


def workdays_in_range(start: date, end: date) -> int:
    """Count weekdays between two dates, inclusive."""
    if end < start:
        return 0
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        database: Database,
        client_factory: type[RedmineClient] = RedmineClient,
    ) -> None:
        super().__init__()
        self.config = config
        self.database = database
        self.client_factory = client_factory
        self.service = TrackService(database)

        self.client: RedmineClient | None = None
        self.current_user_id: int | None = None
        self.issues: dict[int, Issue] = {}
        self.activities: list[Activity] = []
        self.issue_widgets: dict[int, IssueWidget] = {}
        self.tray_icon: QSystemTrayIcon | None = None
        self._tray_notice_shown = False

        self.setWindowTitle("Redmine Time Tracker")
        self.setMinimumSize(900, 600)

        self._build_ui()
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self._tray_available:
            self._build_tray()
        self._build_menu()
        self._setup_timers()

        QTimer.singleShot(0, self._startup)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Обновить задачи")
        self.refresh_btn.clicked.connect(self.refresh_issues)
        toolbar.addWidget(self.refresh_btn)

        self.history_btn = QPushButton("🕘 История")
        self.history_btn.setToolTip("Опубликованные треки")
        self.history_btn.clicked.connect(self._open_history)
        toolbar.addWidget(self.history_btn)

        self.settings_btn = QPushButton("⚙ Настройки")
        self.settings_btn.clicked.connect(self._show_settings)
        toolbar.addWidget(self.settings_btn)

        self.api_key_btn = QPushButton("🔑 API ключ")
        self.api_key_btn.clicked.connect(self._show_api_key_dialog)
        toolbar.addWidget(self.api_key_btn)

        toolbar.addStretch()
        self.status_label = QLabel("Готово")
        toolbar.addWidget(self.status_label)
        layout.addLayout(toolbar)

        self.metrics = MetricsWidget()
        layout.addWidget(self.metrics)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.issues_container = QWidget()
        self.issues_layout = QVBoxLayout(self.issues_container)
        self.issues_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.issues_layout.setSpacing(12)
        self.scroll_area.setWidget(self.issues_container)
        layout.addWidget(self.scroll_area)

    def _build_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(
            self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon)
        )
        self.tray_icon.setToolTip("Redmine Time Tracker")

        tray_menu = QMenu(self)
        show_action = QAction("Показать", self)
        show_action.triggered.connect(self.showNormal)
        tray_menu.addAction(show_action)

        refresh_action = QAction("Обновить задачи", self)
        refresh_action.triggered.connect(self.refresh_issues)
        tray_menu.addAction(refresh_action)

        tray_menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self._quit)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Файл")

        settings_action = QAction("Настройки", self)
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)

        api_key_action = QAction("API ключ", self)
        api_key_action.triggered.connect(self._show_api_key_dialog)
        file_menu.addAction(api_key_action)

        history_action = QAction("История публикаций", self)
        history_action.triggered.connect(self._open_history)
        file_menu.addAction(history_action)

        file_menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self._quit)
        file_menu.addAction(quit_action)

    def _setup_timers(self) -> None:
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._heartbeat)
        self.heartbeat_timer.start(HEARTBEAT_INTERVAL_MS)

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    def _startup(self) -> None:
        self._recover_orphan_track()
        self._bootstrap_connection()

    def _recover_orphan_track(self) -> None:
        try:
            orphan = self.service.find_orphan(ORPHAN_THRESHOLD)
        except sqlite3.Error:
            logger.exception("Failed to inspect running tracks")
            return
        if orphan is None or orphan.track.id is None:
            return

        dialog = RecoveryDialog(orphan, self)
        mode = RecoveryMode.UNTIL_HEARTBEAT
        if dialog.exec() == QDialog.DialogCode.Accepted:
            mode = dialog.mode()

        track = self.service.recover(orphan.track.id, mode)
        if track is not None:
            logger.info(
                "Recovered track %s after unclean shutdown (mode=%s, elapsed=%ss)",
                track.id,
                mode.value,
                track.elapsed_seconds,
            )

    def _bootstrap_connection(self) -> None:
        if not self.config.redmine_url and not self._show_settings(require_url=True):
            self.status_label.setText("Укажите URL Redmine в настройках")
            return
        if not self.config.redmine_api_key and not self._show_api_key_dialog():
            self.status_label.setText("Укажите API-ключ Redmine")
            return
        if not self._init_client():
            return
        if self.config.refresh_on_start:
            self.refresh_issues()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def _init_client(self) -> bool:
        if not self.config.redmine_url or not self.config.redmine_api_key:
            return False
        try:
            client = self.client_factory(
                self.config.redmine_url,
                self.config.redmine_api_key,
            )
            user = client.get_current_user()
        except RedmineError as exc:
            logger.warning("Cannot connect to Redmine: %s", exc)
            self.client = None
            self._show_error(str(exc))
            return False

        self.client = client
        self.current_user_id = user.get("id")
        name = f"{user.get('firstname', '')} {user.get('lastname', '')}".strip()
        title = "Redmine Time Tracker"
        if name:
            title = f"{title} — {name}"
        self.setWindowTitle(title)
        return True

    def _show_api_key_dialog(self) -> bool:
        dialog = ApiKeyDialog(self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.client = None
        if not self._init_client():
            return False
        if self.config.refresh_on_start:
            self.refresh_issues()
        return True

    def _show_settings(self, require_url: bool = False) -> bool:
        previous_url = self.config.redmine_url
        dialog = SettingsDialog(self.config, require_url=require_url, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if self.config.redmine_url != previous_url:
            self.client = None
            if self._init_client() and self.config.refresh_on_start:
                self.refresh_issues()
        return True

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self.status_label.setText(f"Ошибка: {message}")
        QMessageBox.critical(self, "Ошибка", message)

    def _show_info(self, message: str) -> None:
        QMessageBox.information(self, "Информация", message)

    # ------------------------------------------------------------------
    # Tray and window lifecycle
    # ------------------------------------------------------------------
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._tray_available or self.tray_icon is None:
            self._quit()
            return
        event.ignore()
        self.hide()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            self.tray_icon.showMessage(
                "Redmine Time Tracker",
                "Приложение свёрнуто в трей. "
                "Чтобы закрыть, используйте меню трея или Файл → Выход.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def _quit(self) -> None:
        for running in self.database.list_running():
            if running.id is not None:
                self.service.pause(running.id)
        if self.tray_icon is not None:
            self.tray_icon.hide()
        QApplication.quit()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def refresh_issues(self) -> None:
        if self.client is None and not self._init_client():
            return
        client = self.client
        if client is None:
            return

        self.status_label.setText("Загрузка задач...")
        self.refresh_btn.setEnabled(False)
        try:
            if self.current_user_id is None:
                raise RedmineError("Redmine не вернул текущего пользователя")
            self.activities = client.get_activities()
            issues = client.get_assigned_open_issues(self.current_user_id)
            for issue in issues:
                issue.time_entries = client.get_time_entries_for_issue(issue.id, limit=5)
        except RedmineError as exc:
            logger.warning("Refresh failed: %s", exc)
            self.status_label.setText("Ошибка загрузки задач")
            self._show_error(str(exc))
            return
        finally:
            self.refresh_btn.setEnabled(True)

        issues = self._merge_pending_issues(issues)
        self.issues = {issue.id: issue for issue in self._sort_issues(issues)}
        self._rebuild_issue_list()
        self._update_metrics()
        self.status_label.setText(f"Загружено задач: {len(self.issues)}")

    def _merge_pending_issues(self, issues: list[Issue]) -> list[Issue]:
        """Keep issues that disappeared from the open list but still have drafts."""
        known = {issue.id for issue in issues}
        for issue_id, subject in self.database.pending_issue_subjects().items():
            if issue_id not in known:
                issues.append(
                    Issue(
                        id=issue_id,
                        subject=subject,
                        estimated_hours=None,
                        total_spent_hours=0.0,
                        local_only=True,
                    )
                )
        return issues

    def _sort_issues(self, issues: list[Issue]) -> list[Issue]:
        pending = self.database.list_pending()
        running_ids: set[int] = set()
        paused_ids: set[int] = set()
        latest_update: dict[int, datetime] = {}

        for track in pending:
            if track.status is TrackStatus.RUNNING:
                running_ids.add(track.issue_id)
            else:
                paused_ids.add(track.issue_id)
            updated = track.updated_at or track.created_at or datetime.min
            if track.issue_id not in latest_update or updated > latest_update[track.issue_id]:
                latest_update[track.issue_id] = updated

        def sort_key(issue: Issue) -> tuple[int, float]:
            if issue.id in running_ids:
                group = 0
            elif issue.id in paused_ids:
                group = 1
            else:
                group = 2
            updated = latest_update.get(issue.id)
            timestamp = -(updated.timestamp()) if updated else float("-inf")
            return (group, timestamp)

        return sorted(issues, key=sort_key)

    def _rebuild_issue_list(self) -> None:
        stale = set(self.issue_widgets) - set(self.issues)
        for issue_id in stale:
            stale_widget = self.issue_widgets.pop(issue_id)
            stale_widget.deleteLater()

        if self.issues_layout.count():
            last = self.issues_layout.itemAt(self.issues_layout.count() - 1)
            if last is not None and last.spacerItem() is not None:
                self.issues_layout.takeAt(self.issues_layout.count() - 1)

        for issue_id, issue in self.issues.items():
            widget: IssueWidget | None = self.issue_widgets.get(issue_id)
            if widget is None:
                widget = IssueWidget(issue)
                widget.add_track_requested.connect(self._add_new_track)
                widget.continue_track_requested.connect(self._continue_track)
                widget.continue_redmine_entry_requested.connect(self._continue_redmine_entry)
                widget.pause_track_requested.connect(self._pause_track)
                widget.edit_track_requested.connect(self._edit_track)
                widget.publish_track_requested.connect(self._publish_track)
                widget.cancel_track_requested.connect(self._cancel_track)
                self.issue_widgets[issue_id] = widget
                self.issues_layout.addWidget(widget)
            widget.update_issue(issue)
            widget.set_existing_entries(issue.time_entries[-5:])
            widget.set_tracks(self.database.list_for_issue(issue_id))

        self.issues_layout.addStretch()

    def _sort_and_rebuild(self) -> None:
        sorted_issues = self._sort_issues(list(self.issues.values()))
        self.issues = {issue.id: issue for issue in sorted_issues}
        self._rebuild_issue_list()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def _update_metrics(self) -> None:
        if self.client is None or self.current_user_id is None:
            return
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        try:
            entries = self.client.get_time_entries(
                self.current_user_id,
                spent_on_from=month_start,
                spent_on_to=today,
            )
        except RedmineError as exc:
            logger.warning("Metrics failed: %s", exc)
            self.status_label.setText(f"Ошибка метрик: {exc}")
            return

        planned_today = DAILY_WORK_HOURS
        planned_week = max(1, workdays_in_range(week_start, today)) * DAILY_WORK_HOURS
        planned_month = max(1, workdays_in_range(month_start, today)) * DAILY_WORK_HOURS

        def spent_between(start: date, end: date) -> float:
            return sum(entry.hours for entry in entries if start <= entry.spent_on <= end)

        self.metrics.update_metric(self.metrics.today, spent_between(today, today), planned_today)
        self.metrics.update_metric(
            self.metrics.week, spent_between(week_start, today), planned_week
        )
        self.metrics.update_metric(
            self.metrics.month, spent_between(month_start, today), planned_month
        )

    # ------------------------------------------------------------------
    # Track actions
    # ------------------------------------------------------------------
    def _add_new_track(self, issue_id: int) -> None:
        issue = self.issues.get(issue_id)
        if issue is None:
            return
        if not self.activities:
            self._show_error("Виды деятельности ещё не загружены. Обновите задачи.")
            return

        dialog = AddTrackDialog(issue.display_name, self.activities, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        track = LocalTrack(
            id=None,
            issue_id=issue_id,
            issue_subject=issue.subject,
            activity_id=dialog.activity_id(),
            activity_name=dialog.activity_name(),
            description=dialog.description(),
            date=dialog.track_date(),
            status=TrackStatus.PAUSED,
            elapsed_seconds=0,
        )
        self.database.save(track)
        self._sort_and_rebuild()

    def _continue_track(self, issue_id: int, track_id: int) -> None:
        track = self.database.get(track_id)
        if track is None:
            return
        active = self.database.get_active()
        if active is not None and active.id != track_id:
            self._show_info(
                f"Трек для задачи #{active.issue_id} поставлен на паузу, "
                "так как запущен другой трек."
            )
        self.service.start(track_id)
        self._sort_and_rebuild()

    def _continue_redmine_entry(self, issue_id: int, time_entry_id: int) -> None:
        issue = self.issues.get(issue_id)
        if issue is None:
            return
        entry = next((item for item in issue.time_entries if item.id == time_entry_id), None)
        if entry is None:
            self._show_error("Запись не найдена.")
            return

        track = LocalTrack(
            id=None,
            issue_id=issue_id,
            issue_subject=issue.subject,
            activity_id=entry.activity_id,
            activity_name=entry.activity_name,
            description=entry.comments,
            date=entry.spent_on,
            status=TrackStatus.PAUSED,
            elapsed_seconds=int(entry.hours * 3600),
            source_time_entry_id=entry.id,
            source_updated_on=entry.updated_on,
        )
        try:
            track = self.database.save(track)
        except sqlite3.IntegrityError:
            self._show_error(
                f"По записи #{entry.id} уже есть черновик. "
                "Закончите или отмените его перед созданием нового."
            )
            return

        active = self.database.get_active()
        if active is not None and active.id != track.id:
            self._show_info(
                f"Трек для задачи #{active.issue_id} поставлен на паузу, "
                "так как запущен другой трек."
            )
        if track.id is not None:
            self.service.start(track.id)
        self._sort_and_rebuild()

    def _pause_track(self, track_id: int, notify: bool = True) -> LocalTrack | None:
        track = self.service.pause(track_id)
        if track is None:
            return None
        if notify:
            self._sort_and_rebuild()
        else:
            for issue_widget in self.issue_widgets.values():
                for track_widget in issue_widget.track_widgets():
                    if track_widget.track_id == track_id:
                        track_widget.refresh(track)
        return track

    def _edit_track(self, track_id: int) -> None:
        track = self.database.get(track_id)
        if track is None:
            return
        issue = self.issues.get(track.issue_id)
        display = issue.display_name if issue else f"#{track.issue_id} {track.issue_subject}"
        dialog = AddTrackDialog(
            display,
            self.activities,
            current_activity_id=track.activity_id,
            description=track.description,
            track_date=track.date,
            title="Изменить трек",
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        track.activity_id = dialog.activity_id()
        track.activity_name = dialog.activity_name()
        track.description = dialog.description()
        track.date = dialog.track_date()
        self.database.save(track)
        self._rebuild_issue_list()

    def _publish_track(self, track_id: int) -> None:
        track = self.database.get(track_id)
        if track is None:
            return
        if track.current_elapsed_seconds() <= 0:
            self._show_error("Нельзя опубликовать трек с нулевым временем.")
            return

        was_running = track.status is TrackStatus.RUNNING
        if was_running:
            track = self._pause_track(track_id, notify=False) or track

        dialog = PublishTrackDialog(
            track,
            allow_update=track.source_time_entry_id is not None,
            parent=self,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if not accepted:
            if was_running:
                self.service.start(track_id)
            self._sort_and_rebuild()
            return
        mode = dialog.mode()

        rounded_hours = track.rounded_hours
        if rounded_hours <= 0:
            self._show_error("Нельзя опубликовать трек с нулевым временем.")
            return

        if self.client is None and not self._init_client():
            return
        client = self.client
        if client is None:
            return

        try:
            entry_id: int | None
            if mode == PublishTrackDialog.UPDATE and track.source_time_entry_id:
                entry_id = self._confirm_overwrite(track)
                if entry_id is None:
                    return
                client.update_time_entry(
                    time_entry_id=entry_id,
                    hours=rounded_hours,
                    comments=track.description,
                    spent_on=track.date,
                    activity_id=track.activity_id,
                )
            else:
                response = client.create_time_entry(
                    issue_id=track.issue_id,
                    hours=rounded_hours,
                    comments=track.description,
                    spent_on=track.date,
                    activity_id=track.activity_id,
                )
                entry_id = int((response.get("time_entry") or {}).get("id") or 0) or None
        except RedmineError as exc:
            logger.warning("Publish failed for track %s: %s", track_id, exc)
            self._show_error(str(exc))
            return

        self.database.mark_published(track_id, entry_id)
        logger.info("Published track %s as entry %s (%s h)", track_id, entry_id, rounded_hours)
        self._show_info(f"Трек опубликован: {track.display_rounded} ч")
        self.refresh_issues()

    def _confirm_overwrite(self, track: LocalTrack) -> int | None:
        """Check the remote entry before overwriting it."""
        entry_id = track.source_time_entry_id
        if entry_id is None or self.client is None:
            return None

        try:
            remote = self.client.get_time_entry(entry_id)
        except RedmineError as exc:
            self._show_error(f"Не удалось проверить запись #{entry_id}: {exc}")
            return None

        if (
            remote is not None
            and track.source_updated_on is not None
            and remote.updated_on != track.source_updated_on
        ):
            dialog = ConfirmationDialog(
                "Запись изменилась",
                f"Запись #{entry_id} изменили в Redmine после того, как вы начали "
                "её продолжение.<br><br>"
                "Обновление перезапишет текущие значения часов, описания и вида "
                "деятельности.<br><br>Продолжить?",
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
        return entry_id

    def _cancel_track(self, track_id: int) -> None:
        track = self.database.get(track_id)
        if track is None:
            return

        dialog = ConfirmationDialog(
            "Отменить трек",
            f"Удалить локальный трек для задачи #{track.issue_id}?<br>"
            f"Накопленное время: {track.display_elapsed}",
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.database.delete(track_id)
        self._sort_and_rebuild()

    def _open_history(self) -> None:
        dialog = HistoryDialog(self.database, self.config.redmine_url, self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        for issue_widget in self.issue_widgets.values():
            for track_widget in issue_widget.track_widgets():
                track_widget.update_display()

    def _heartbeat(self) -> None:
        try:
            self.service.heartbeat_active()
        except sqlite3.Error:
            logger.exception("Heartbeat failed")
