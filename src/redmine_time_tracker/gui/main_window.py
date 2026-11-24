"""Main application window."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from PySide6.QtCore import QSettings, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from ..database import Database
from ..metrics import compute_metrics
from ..models import Activity, Issue, LocalTrack, TimeEntry, TrackStatus, round_up_minutes
from ..redmine_client import RedmineClient, RedmineConnectionError, RedmineError
from ..sync import DashboardData, fetch_dashboard
from ..tracking import ORPHAN_THRESHOLD, RecoveryMode, TrackService
from .compact import CompactWindow
from .dialogs import (
    AddTrackDialog,
    ApiKeyDialog,
    ConfirmationDialog,
    PublishTrackDialog,
    RecoveryDialog,
    SettingsDialog,
)
from .history import HistoryWidget
from .theme import muted_style
from .widgets import ActiveTrackPanel, IssueWidget, MetricsWidget
from .workers import Worker

HEARTBEAT_INTERVAL_MS = 30_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishPlan:
    track_id: int
    mode: str
    rounded_hours: float
    display: str
    was_running: bool
    entry_id: int | None


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        database: Database,
        client_factory: Callable[[str, str], RedmineClient] = RedmineClient,
        gui_settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.database = database
        self.client_factory = client_factory
        self.service = TrackService(database)
        self.pool = QThreadPool.globalInstance()

        self.client: RedmineClient | None = None
        self.current_user_id: int | None = None
        self.issues: dict[int, Issue] = {}
        self.activities: list[Activity] = []
        self.pending_widgets: dict[int, IssueWidget] = {}
        self.all_widgets: dict[int, IssueWidget] = {}
        self.tray_icon: QSystemTrayIcon | None = None

        self._workers: set[Worker] = set()
        self._connecting = False
        self._refreshing = False
        self._publishing = False
        self._tray_notice_shown = False

        self.setWindowTitle("Redmine Time Tracker")
        self.setMinimumSize(900, 600)

        self.gui_settings = gui_settings or QSettings(
            "redmine-time-tracker", "redmine-time-tracker"
        )
        geometry = self.gui_settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        self._build_ui()
        self.compact_window = CompactWindow()
        self.compact_window.pause_requested.connect(self._pause_track)
        self.compact_window.publish_requested.connect(self._publish_track)
        self.compact_window.restore_requested.connect(lambda: self._toggle_compact(False))
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self._tray_available:
            self._build_tray()
        self._build_menu()
        self._build_shortcuts()
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
        self.refresh_btn = QPushButton("Обновить задачи")
        self.refresh_btn.setToolTip("Обновить список задач (Ctrl+R)")
        self.refresh_btn.clicked.connect(self.refresh_issues)
        toolbar.addWidget(self.refresh_btn)

        self.history_btn = QPushButton("История")
        self.history_btn.setToolTip("Опубликованные треки")
        self.history_btn.clicked.connect(self._open_history)
        toolbar.addWidget(self.history_btn)

        self.settings_btn = QPushButton("Настройки")
        self.settings_btn.clicked.connect(self._show_settings)
        toolbar.addWidget(self.settings_btn)

        self.api_key_btn = QPushButton("API ключ")
        self.api_key_btn.clicked.connect(self._show_api_key_dialog)
        toolbar.addWidget(self.api_key_btn)

        toolbar.addStretch()
        self.status_label = QLabel("Готово")
        toolbar.addWidget(self.status_label)
        layout.addLayout(toolbar)

        self.offline_label = QLabel("")
        self.offline_label.setWordWrap(True)
        self.offline_label.hide()
        layout.addWidget(self.offline_label)

        self.metrics = MetricsWidget()
        layout.addWidget(self.metrics)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по номеру или теме задачи (Ctrl+F)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self._rebuild_issue_lists)

        self.active_panel = ActiveTrackPanel()
        self.active_panel.pause_requested.connect(self._pause_track)
        self.active_panel.publish_requested.connect(self._publish_track)
        layout.addWidget(self.active_panel)

        self.tabs = QTabWidget()
        self.pending_page, self.pending_layout = self._make_issue_page()
        self.all_page, self.all_layout = self._make_issue_page()
        self.history_widget = HistoryWidget(self.database, self.config.redmine_url)
        self.tabs.addTab(self.pending_page, "Сейчас")
        self.tabs.addTab(self.all_page, "Задачи")
        self.tabs.addTab(self.history_widget, "История")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

    def _make_issue_page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        container_layout.setSpacing(12)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        return page, container_layout

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

        compact_action = QAction("Компактный режим", self)
        compact_action.triggered.connect(lambda: self._toggle_compact(True))
        tray_menu.addAction(compact_action)

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

        view_menu = menubar.addMenu("Вид")
        self.compact_action = QAction("Компактный режим", self)
        self.compact_action.setCheckable(True)
        self.compact_action.setShortcut("Ctrl+M")
        self.compact_action.toggled.connect(self._toggle_compact)
        view_menu.addAction(self.compact_action)

    def _build_shortcuts(self) -> None:
        refresh = QAction(self)
        refresh.setShortcut("Ctrl+R")
        refresh.triggered.connect(self.refresh_issues)
        self.addAction(refresh)

        find = QAction(self)
        find.setShortcut("Ctrl+F")
        find.triggered.connect(self._focus_search)
        self.addAction(find)

        toggle = QAction(self)
        toggle.setShortcut("Ctrl+Space")
        toggle.triggered.connect(self._toggle_active)
        self.addAction(toggle)

        publish = QAction(self)
        publish.setShortcut("Ctrl+P")
        publish.triggered.connect(self._publish_active)
        self.addAction(publish)

    def _setup_timers(self) -> None:
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._heartbeat)
        self.heartbeat_timer.start(HEARTBEAT_INTERVAL_MS)

    def _run(
        self,
        fn: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[BaseException], None],
    ) -> None:
        worker = Worker(fn)
        self._workers.add(worker)

        def release(*_args: object) -> None:
            self._workers.discard(worker)

        worker.signals.succeeded.connect(on_success)
        worker.signals.failed.connect(on_failure)
        worker.signals.succeeded.connect(release)
        worker.signals.failed.connect(release)
        self.pool.start(worker)

    # ------------------------------------------------------------------
    # Startup and connection
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
        if self.client is None and not self._connecting:
            after = self.refresh_issues if self.config.refresh_on_start else None
            self._connect_async(after)

    def _connect_async(self, after: Callable[[], None] | None = None) -> None:
        if self._connecting:
            return
        url = self.config.redmine_url
        key = self.config.redmine_api_key
        if not url or not key:
            return

        self._connecting = True
        self.status_label.setText("Подключение к Redmine...")
        factory = self.client_factory

        def job() -> tuple[Any, dict[str, Any]]:
            client = factory(url, key)
            return client, client.get_current_user()

        self._run(
            job,
            lambda result: self._on_connected(result, after),
            self._on_connect_failed,
        )

    def _on_connected(
        self,
        result: tuple[Any, dict[str, Any]],
        after: Callable[[], None] | None,
    ) -> None:
        client, user = result
        self.client = client
        self.current_user_id = user.get("id")
        self._connecting = False

        name = f"{user.get('firstname', '')} {user.get('lastname', '')}".strip()
        title = "Redmine Time Tracker"
        if name:
            title = f"{title} — {name}"
        self.setWindowTitle(title)
        self.status_label.setText("Готово")
        if after is not None:
            after()

    def _on_connect_failed(self, exc: BaseException) -> None:
        self._connecting = False
        self.client = None
        self.current_user_id = None
        logger.warning("Cannot connect to Redmine: %s", exc)
        self.status_label.setText("Нет подключения к Redmine")
        self._show_error(str(exc))

    def _show_api_key_dialog(self) -> bool:
        dialog = ApiKeyDialog(self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.client = None
        self.current_user_id = None
        after = self.refresh_issues if self.config.refresh_on_start else None
        self._connect_async(after)
        return True

    def _show_settings(self, require_url: bool = False) -> bool:
        previous_url = self.config.redmine_url
        dialog = SettingsDialog(self.config, require_url=require_url, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if self.config.redmine_url != previous_url:
            self.client = None
            self.current_user_id = None
            self.history_widget.base_url = self.config.redmine_url
            after = self.refresh_issues if self.config.refresh_on_start else None
            self._connect_async(after)
        return True

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self.status_label.setText(f"Ошибка: {message}")
        QMessageBox.critical(self, "Ошибка", message)

    def _show_info(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def _show_offline_banner(self, text: str) -> None:
        palette = self.palette()
        background = palette.color(QPalette.ColorRole.ToolTipBase).name()
        foreground = palette.color(QPalette.ColorRole.ToolTipText).name()
        self.offline_label.setStyleSheet(
            f"background-color: {background}; color: {foreground}; "
            "padding: 6px; border-radius: 4px;"
        )
        self.offline_label.setText(text)
        self.offline_label.show()

    def _hide_offline_banner(self) -> None:
        self.offline_label.hide()

    # ------------------------------------------------------------------
    # Tray and window lifecycle
    # ------------------------------------------------------------------
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.gui_settings.setValue("window/geometry", self.saveGeometry())
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
        self.gui_settings.setValue("compact/position", self.compact_window.pos())
        self.compact_window.hide()
        if self.tray_icon is not None:
            self.tray_icon.hide()
        QApplication.quit()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def refresh_issues(self) -> None:
        if self._refreshing:
            return
        if self.client is None:
            self._connect_async(self.refresh_issues)
            return
        user_id = self.current_user_id
        if user_id is None:
            self.status_label.setText("Redmine не вернул текущего пользователя")
            return

        client = self.client
        today = date.today()
        month_start = today.replace(day=1)

        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("Загрузка задач...")
        self._run(
            lambda: fetch_dashboard(client, user_id, month_start, today),
            self._on_dashboard_loaded,
            self._on_refresh_failed,
        )

    def _on_dashboard_loaded(self, data: Any) -> None:
        dashboard: DashboardData = data
        self._refreshing = False
        self.refresh_btn.setEnabled(True)
        self.activities = dashboard.activities

        try:
            self.database.replace_cache(
                dashboard.issues,
                dashboard.activities,
                dashboard.fetched_at,
            )
        except sqlite3.Error:
            logger.exception("Failed to cache the issue list")

        self._apply_issues(dashboard.issues)
        self._update_metrics(dashboard.period_entries)
        self._hide_offline_banner()
        self.status_label.setText(f"Загружено задач: {len(self.issues)}")

    def _on_refresh_failed(self, exc: BaseException) -> None:
        self._refreshing = False
        self.refresh_btn.setEnabled(True)
        logger.warning("Refresh failed: %s", exc)
        if isinstance(exc, RedmineConnectionError):
            self._load_from_cache(str(exc))
            return
        self.status_label.setText("Ошибка загрузки задач")
        if isinstance(exc, RedmineError):
            self._show_error(str(exc))
        else:
            self._show_error(f"Неожиданная ошибка: {exc}")

    def _load_from_cache(self, reason: str) -> None:
        issues, activities, last_sync = self.database.load_cached()
        if not issues:
            self.status_label.setText("Нет связи с Redmine")
            self._show_error(f"{reason}\n\nКеш пуст, показать нечего.")
            return
        if activities:
            self.activities = activities
        self._apply_issues(issues)
        self.metrics.set_unavailable()
        when = last_sync.strftime("%d.%m.%Y %H:%M") if last_sync else "неизвестно"
        self._show_offline_banner(
            f"Нет связи с Redmine. Показан кеш от {when}. Публикация недоступна."
        )
        self.status_label.setText("Офлайн-режим")

    def _apply_issues(self, api_issues: list[Issue]) -> None:
        merged = self._merge_pending_issues(list(api_issues))
        self.issues = {issue.id: issue for issue in self._sort_issues(merged)}
        self._rebuild_issue_lists()

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

    def _rebuild_issue_lists(self) -> None:
        pending_ids = set(self.database.pending_issue_subjects())
        query = self.search_input.text().strip().lower()

        all_issues = [issue for issue in self.issues.values() if self._matches(issue, query)]
        pending_issues = [issue for issue in all_issues if issue.id in pending_ids]
        tracks = self.database.tracks_by_issue(list(self.issues))

        self._fill_issues(
            self.all_layout,
            self.all_widgets,
            all_issues,
            tracks,
            "Ничего не найдено" if query else "Задачи не загружены",
        )
        self._fill_issues(
            self.pending_layout,
            self.pending_widgets,
            pending_issues,
            tracks,
            "Ничего не найдено" if query else "Нет задач с черновиками",
        )
        self.tabs.setTabText(0, f"Сейчас ({len(pending_issues)})")
        self.tabs.setTabText(1, f"Задачи ({len(all_issues)})")

        self._update_active_panel()
        self._update_draft_metric()

    @staticmethod
    def _matches(issue: Issue, query: str) -> bool:
        if not query:
            return True
        return query in f"#{issue.id} {issue.subject}".lower()

    def _create_issue_widget(self, issue: Issue) -> IssueWidget:
        widget = IssueWidget(issue, base_url=self.config.redmine_url)
        widget.add_track_requested.connect(self._add_new_track)
        widget.continue_track_requested.connect(self._continue_track)
        widget.continue_redmine_entry_requested.connect(self._continue_redmine_entry)
        widget.pause_track_requested.connect(self._pause_track)
        widget.edit_track_requested.connect(self._edit_track)
        widget.publish_track_requested.connect(self._publish_track)
        widget.cancel_track_requested.connect(self._cancel_track)
        return widget

    def _fill_issues(
        self,
        layout: QVBoxLayout,
        registry: dict[int, IssueWidget],
        issues: list[Issue],
        tracks: dict[int, list[LocalTrack]],
        empty_text: str,
    ) -> None:
        wanted = {issue.id for issue in issues}
        for issue_id in set(registry) - wanted:
            stale = registry.pop(issue_id)
            stale.setParent(None)
            stale.deleteLater()

        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None and widget not in registry.values():
                widget.deleteLater()

        for issue in issues:
            widget = registry.get(issue.id)
            if widget is None:
                widget = self._create_issue_widget(issue)
                registry[issue.id] = widget
            widget.base_url = self.config.redmine_url
            widget.update_issue(issue)
            widget.set_existing_entries(issue.time_entries[-5:])
            widget.set_tracks(tracks.get(issue.id, []))
            layout.addWidget(widget)

        if not issues:
            placeholder = QLabel(empty_text)
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(muted_style(self))
            layout.addWidget(placeholder)

        layout.addStretch()

    def _on_search_changed(self, _text: str) -> None:
        self.search_timer.start()

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.history_widget:
            self.history_widget.refresh()

    def _update_active_panel(self) -> None:
        active = self.database.get_active()
        self.active_panel.set_track(active)
        self.compact_window.set_track(active)

    def _toggle_compact(self, enabled: bool) -> None:
        if enabled:
            self.compact_window.set_track(self.database.get_active())
            self.compact_window.restore_position(self.gui_settings.value("compact/position"))
            self.compact_window.show()
            self.hide()
        else:
            self.gui_settings.setValue("compact/position", self.compact_window.pos())
            self.compact_window.hide()
            self.showNormal()
            self.activateWindow()

        if self.compact_action.isChecked() != enabled:
            self.compact_action.blockSignals(True)
            self.compact_action.setChecked(enabled)
            self.compact_action.blockSignals(False)

    def _sort_and_rebuild(self) -> None:
        sorted_issues = self._sort_issues(list(self.issues.values()))
        self.issues = {issue.id: issue for issue in sorted_issues}
        self._rebuild_issue_lists()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def _update_metrics(self, entries: list[TimeEntry]) -> None:
        values = compute_metrics(entries, date.today())
        self.metrics.update_metric(self.metrics.today, values.spent_today, values.planned_today)
        self.metrics.update_metric(self.metrics.week, values.spent_week, values.planned_week)
        self.metrics.update_metric(self.metrics.month, values.spent_month, values.planned_month)

    def _update_draft_metric(self) -> None:
        pending = self.database.list_pending()
        seconds = sum(track.current_elapsed_seconds() for track in pending)
        self.metrics.set_drafts(round_up_minutes(seconds), len(pending))

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
            for registry in (self.pending_widgets, self.all_widgets):
                for issue_widget in registry.values():
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
        self._rebuild_issue_lists()

    def _publish_track(self, track_id: int) -> None:
        if self._publishing:
            return
        if self.client is None:
            self._show_error("Нет подключения к Redmine. Обновите задачи.")
            return

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
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._resume_after_cancel(track_id, was_running)
            return

        rounded_hours = track.rounded_hours
        if rounded_hours <= 0:
            self._show_error("Нельзя опубликовать трек с нулевым временем.")
            self._resume_after_cancel(track_id, was_running)
            return

        plan = PublishPlan(
            track_id=track_id,
            mode=dialog.mode(),
            rounded_hours=rounded_hours,
            display=track.display_rounded,
            was_running=was_running,
            entry_id=track.source_time_entry_id,
        )

        if plan.mode == PublishTrackDialog.UPDATE and plan.entry_id is not None:
            client = self.client
            entry_id = plan.entry_id
            self._publishing = True
            self.status_label.setText("Проверка записи...")
            self._run(
                lambda: client.get_time_entry(entry_id),
                lambda remote: self._on_remote_checked(plan, remote),
                self._on_publish_failed,
            )
        else:
            self._execute_publish(plan, None)

    def _on_remote_checked(self, plan: PublishPlan, remote: Any) -> None:
        track = self.database.get(plan.track_id)
        conflict = (
            remote is not None
            and track is not None
            and track.source_updated_on is not None
            and remote.updated_on != track.source_updated_on
        )
        if conflict:
            dialog = ConfirmationDialog(
                "Запись изменилась",
                f"Запись #{plan.entry_id} изменили в Redmine после того, как вы начали "
                "её продолжение.<br><br>"
                "Обновление перезапишет текущие значения часов, описания и вида "
                "деятельности.<br><br>Продолжить?",
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._publishing = False
                self._resume_after_cancel(plan.track_id, plan.was_running)
                return
        self._execute_publish(plan, plan.entry_id)

    def _execute_publish(self, plan: PublishPlan, entry_id: int | None) -> None:
        client = self.client
        track = self.database.get(plan.track_id)
        if client is None or track is None:
            self._publishing = False
            return

        self._publishing = True
        self.status_label.setText("Публикация...")

        def job() -> int | None:
            if plan.mode == PublishTrackDialog.UPDATE and entry_id is not None:
                client.update_time_entry(
                    time_entry_id=entry_id,
                    hours=plan.rounded_hours,
                    comments=track.description,
                    spent_on=track.date,
                    activity_id=track.activity_id,
                )
                return entry_id
            response = client.create_time_entry(
                issue_id=track.issue_id,
                hours=plan.rounded_hours,
                comments=track.description,
                spent_on=track.date,
                activity_id=track.activity_id,
            )
            payload = response.get("time_entry") or {}
            return int(payload.get("id") or 0) or None

        self._run(
            job,
            lambda new_id: self._on_published(plan, new_id),
            self._on_publish_failed,
        )

    def _on_published(self, plan: PublishPlan, entry_id: int | None) -> None:
        self._publishing = False
        self.database.mark_published(plan.track_id, entry_id)
        logger.info(
            "Published track %s as entry %s (%s h)",
            plan.track_id,
            entry_id,
            plan.rounded_hours,
        )
        self.status_label.setText("Опубликовано")
        self._show_info(f"Трек опубликован: {plan.display} ч")
        self._sort_and_rebuild()
        self.refresh_issues()

    def _on_publish_failed(self, exc: BaseException) -> None:
        self._publishing = False
        logger.warning("Publish failed: %s", exc)
        self.status_label.setText("Ошибка публикации")
        if isinstance(exc, RedmineConnectionError):
            self._show_offline_banner(
                "Нет связи с Redmine. Публикация не выполнена, черновик сохранён."
            )
        self._show_error(str(exc))

    def _resume_after_cancel(self, track_id: int, was_running: bool) -> None:
        if was_running:
            self.service.start(track_id)
        self._sort_and_rebuild()

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
        self.history_widget.refresh()
        self.tabs.setCurrentWidget(self.history_widget)

    def _focus_search(self) -> None:
        self.tabs.setCurrentWidget(self.all_page)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _toggle_active(self) -> None:
        active = self.database.get_active()
        if active is not None and active.id is not None:
            self._pause_track(active.id)
            return
        pending = self.database.list_pending()
        if pending:
            track = pending[0]
            if track.id is not None:
                self._continue_track(track.issue_id, track.id)

    def _publish_active(self) -> None:
        active = self.database.get_active()
        if active is not None and active.id is not None:
            self._publish_track(active.id)

    def _update_tray_tooltip(self) -> None:
        if self.tray_icon is None:
            return
        active = self.database.get_active()
        if active is None:
            self.tray_icon.setToolTip("Redmine Time Tracker")
            return
        self.tray_icon.setToolTip(
            "Redmine Time Tracker\n"
            f"#{active.issue_id} {active.issue_subject}\n"
            f"{active.display_elapsed}"
        )

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self.active_panel.update_display()
        self.compact_window.update_display()
        for registry in (self.pending_widgets, self.all_widgets):
            for issue_widget in registry.values():
                for track_widget in issue_widget.track_widgets():
                    track_widget.update_display()

    def _heartbeat(self) -> None:
        try:
            self.service.heartbeat_active()
        except sqlite3.Error:
            logger.exception("Heartbeat failed")
        self._update_tray_tooltip()
