"""Headless GUI test: wiring, tabs, search, compact mode and history."""

from __future__ import annotations

import time
from datetime import date, datetime

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from redmine_time_tracker.config import AppConfig
from redmine_time_tracker.database import Database
from redmine_time_tracker.gui.main_window import MainWindow
from redmine_time_tracker.models import (
    Activity,
    Issue,
    LocalTrack,
    TimeEntry,
    TrackStatus,
)


def make_entry(entry_id: int, issue_id: int) -> TimeEntry:
    return TimeEntry(
        id=entry_id,
        issue_id=issue_id,
        user_id=7,
        hours=1.0,
        comments="previous work",
        spent_on=date.today(),
        activity_id=9,
        activity_name="Development",
        created_on=datetime.now(),
        updated_on=datetime.now(),
    )


class FakeClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url

    def get_current_user(self) -> dict:
        return {"id": 7, "firstname": "Test", "lastname": "User"}

    def get_activities(self) -> list[Activity]:
        return [Activity(id=9, name="Development", is_default=True)]

    def get_assigned_open_issues(self, user_id) -> list[Issue]:
        return [
            Issue(id=101, subject="Fix parser", estimated_hours=4.0, total_spent_hours=1.0),
            Issue(
                id=102,
                subject="Write tests <b>now</b>",
                estimated_hours=None,
                total_spent_hours=0.0,
            ),
        ]

    def get_time_entries_for_issues(
        self, issue_ids: list[int], limit_per_issue: int = 5
    ) -> dict[int, list[TimeEntry]]:
        return {101: [make_entry(555, 101)]}

    def get_time_entries(self, user_id, spent_on_from=None, spent_on_to=None):
        return [make_entry(556, 101)]

    def get_time_entry(self, entry_id: int) -> TimeEntry | None:
        return None

    def create_time_entry(self, **kwargs) -> dict:
        return {"time_entry": {"id": 900}}

    def update_time_entry(self, **kwargs) -> dict:
        return {}


def wait_until(app: QApplication, predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.ini").write_text(
        "[redmine]\nurl = https://redmine.example.com\n\n[app]\nrefresh_on_start = true\n",
        encoding="utf-8",
    )
    (config_dir / ".env").write_text("REDMINE_API_KEY=test-key\n", encoding="utf-8")

    database = Database(tmp_path / "data.db")
    database.init()
    database.save(
        LocalTrack(
            id=None,
            issue_id=101,
            issue_subject="Fix parser",
            activity_id=9,
            activity_name="Development",
            description="draft",
            date=date.today(),
            status=TrackStatus.PAUSED,
            elapsed_seconds=120,
        )
    )

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(
        AppConfig(config_dir, environ={}),
        database,
        client_factory=FakeClient,
        gui_settings=settings,
    )
    window.show()
    yield window

    window.timer.stop()
    window.heartbeat_timer.stop()
    window.compact_window.hide()
    window.compact_window.deleteLater()
    window.hide()
    window.deleteLater()
    qapp.processEvents()


def test_dashboard_loads_and_search_filters(qapp, window) -> None:
    assert wait_until(qapp, lambda: len(window.issues) == 2)
    assert window.current_user_id == 7
    assert window.tabs.count() == 3
    assert set(window.all_widgets) == {101, 102}
    assert 101 in window.pending_widgets
    assert window.metrics.drafts_label.text()

    cached_issues, cached_activities, last_sync = window.database.load_cached()
    assert last_sync is not None
    assert len(cached_issues) == 2
    assert cached_activities

    title = window.all_widgets[102].title_label.text()
    assert "&lt;b&gt;now&lt;/b&gt;" in title
    assert "<b>now</b>" not in title
    assert "https://redmine.example.com/issues/101" in (window.all_widgets[101].title_label.text())

    window.search_input.setText("parser")
    assert wait_until(qapp, lambda: set(window.all_widgets) == {101})
    assert window.tabs.tabText(0) == "Сейчас (1)"

    window.search_input.setText("nothing-matches")
    assert wait_until(qapp, lambda: window.all_widgets == {})
    assert window.tabs.tabText(1) == "Задачи (0)"

    window.search_input.clear()
    assert wait_until(qapp, lambda: len(window.all_widgets) == 2)


def test_track_lifecycle_and_compact_mode(qapp, window) -> None:
    assert wait_until(qapp, lambda: len(window.issues) == 2)

    track = window.database.list_for_issue(101)[0]
    assert track.id is not None

    window.service.start(track.id)
    window._sort_and_rebuild()
    qapp.processEvents()
    assert window.active_panel.isVisibleTo(window)
    assert window.compact_window.title_label.text().startswith("#101")

    window._toggle_compact(True)
    qapp.processEvents()
    assert window.compact_window.isVisible()
    assert window.compact_window.pause_btn.isEnabled()

    window._tick()
    assert window.compact_window.current_seconds() >= 0

    window.compact_window.restore_requested.emit()
    qapp.processEvents()
    assert not window.compact_window.isVisible()
    assert window.isVisible()

    window.service.pause(track.id)
    window._sort_and_rebuild()
    assert not window.active_panel.isVisibleTo(window)
    assert not window.compact_window.pause_btn.isEnabled()


def test_history_shows_published_tracks(qapp, window) -> None:
    assert wait_until(qapp, lambda: len(window.issues) == 2)

    published = window.database.save(
        LocalTrack(
            id=None,
            issue_id=101,
            issue_subject="Fix parser",
            activity_id=9,
            activity_name="Development",
            description="done",
            date=date.today(),
            status=TrackStatus.PAUSED,
            elapsed_seconds=1800,
        )
    )
    assert published.id is not None
    window.database.mark_published(published.id, 900)

    window.history_widget.refresh()
    assert window.history_widget.table.rowCount() == 1
    assert window.history_widget.table.item(0, 4).text() == "#900"
    assert "0:30" in window.history_widget.total_label.text()
