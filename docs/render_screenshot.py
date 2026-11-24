"""Render a README screenshot with demo data."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from redmine_time_tracker.config import AppConfig
from redmine_time_tracker.database import Database
from redmine_time_tracker.gui.main_window import MainWindow
from redmine_time_tracker.models import Activity, Issue, LocalTrack, TimeEntry, TrackStatus


def entry(entry_id: int, issue_id: int, hours: float, days_ago: int, text: str) -> TimeEntry:
    spent = date.today() - timedelta(days=days_ago)
    return TimeEntry(
        id=entry_id,
        issue_id=issue_id,
        user_id=7,
        hours=hours,
        comments=text,
        spent_on=spent,
        activity_id=9,
        activity_name="Разработка",
        created_on=datetime.now(),
        updated_on=datetime.now(),
    )


class DemoClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url

    def get_current_user(self) -> dict:
        return {"id": 7, "firstname": "Анна", "lastname": "Смирнова"}

    def get_activities(self) -> list[Activity]:
        return [
            Activity(id=9, name="Разработка", is_default=True),
            Activity(id=10, name="Ревью"),
            Activity(id=11, name="Созвон"),
        ]

    def get_assigned_open_issues(self, user_id) -> list[Issue]:
        return [
            Issue(
                id=4127,
                subject="Экспорт отчёта в XLSX",
                estimated_hours=6.0,
                total_spent_hours=3.5,
            ),
            Issue(
                id=4102,
                subject="Пагинация в списке пациентов",
                estimated_hours=4.0,
                total_spent_hours=4.0,
            ),
            Issue(
                id=4088,
                subject="Починить таймаут при загрузке СЭМД",
                estimated_hours=None,
                total_spent_hours=1.25,
            ),
        ]

    def get_time_entries_for_issues(self, issue_ids, limit_per_issue=5):
        return {
            4127: [entry(9001, 4127, 1.5, 1, "Черновик выгрузки")],
            4102: [entry(9002, 4102, 2.0, 2, "Лимит и оффсет")],
            4088: [],
        }

    def get_time_entries(self, user_id, spent_on_from=None, spent_on_to=None):
        return [
            entry(9101, 4127, 3.0, 0, "Сегодня"),
            entry(9102, 4102, 2.5, 1, "Вчера"),
            entry(9103, 4088, 4.0, 3, "Ранее"),
            entry(9104, 4127, 2.0, 7, "Прошлая неделя"),
        ]

    def get_time_entry(self, entry_id):
        return None

    def create_time_entry(self, **kwargs):
        return {"time_entry": {"id": 9999}}

    def update_time_entry(self, **kwargs):
        return {}


def wait(app: QApplication, predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="rtt-shot-"))
    (base / "config.ini").write_text(
        "[redmine]\nurl = https://redmine.example.com\n\n[app]\nrefresh_on_start = true\n",
        encoding="utf-8",
    )
    (base / ".env").write_text("REDMINE_API_KEY=demo\n", encoding="utf-8")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    database = Database(base / "data.db")
    database.init()
    running = database.save(
        LocalTrack(
            id=None,
            issue_id=4127,
            issue_subject="Экспорт отчёта в XLSX",
            activity_id=9,
            activity_name="Разработка",
            description="Собрать выгрузку и проверить формулы",
            date=date.today(),
            status=TrackStatus.PAUSED,
            elapsed_seconds=0,
        )
    )
    database.save(
        LocalTrack(
            id=None,
            issue_id=4102,
            issue_subject="Пагинация в списке пациентов",
            activity_id=10,
            activity_name="Ревью",
            description="Посмотреть ветку feature/pagination",
            date=date.today(),
            status=TrackStatus.PAUSED,
            elapsed_seconds=1800,
        )
    )
    window = MainWindow(
        AppConfig(base, environ={}),
        database,
        client_factory=DemoClient,
        gui_settings=QSettings(str(base / "settings.ini"), QSettings.Format.IniFormat),
    )
    window.resize(1240, 860)
    window.show()
    assert wait(app, lambda: len(window.issues) == 3)

    if running.id is not None:
        database.start(running.id, datetime.now() - timedelta(minutes=37, seconds=12))
    window._sort_and_rebuild()
    app.processEvents()

    window.tabs.setCurrentIndex(1)
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()

    out = Path(__file__).resolve().parent.parent / "docs" / "screenshot.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(out))
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
