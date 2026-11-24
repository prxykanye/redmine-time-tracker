from __future__ import annotations

from datetime import date, datetime

from redmine_time_tracker.models import Activity, Issue, TimeEntry
from redmine_time_tracker.sync import fetch_dashboard


def make_entry(entry_id: int, issue_id: int) -> TimeEntry:
    return TimeEntry(
        id=entry_id,
        issue_id=issue_id,
        user_id=7,
        hours=1.0,
        comments="",
        spent_on=date(2026, 1, 5),
        activity_id=9,
        activity_name="Development",
        created_on=datetime(2026, 1, 5, 10, 0, 0),
        updated_on=datetime(2026, 1, 5, 10, 0, 0),
    )


class FakeDashboardClient:
    def __init__(self) -> None:
        self.entry_calls: list[tuple[list[int], int]] = []
        self.period_calls: list[tuple[date | None, date | None]] = []

    def get_activities(self) -> list[Activity]:
        return [Activity(id=9, name="Development", is_default=True)]

    def get_assigned_open_issues(self, user_id) -> list[Issue]:
        return [
            Issue(id=1, subject="One", estimated_hours=4.0, total_spent_hours=0.0),
            Issue(id=2, subject="Two", estimated_hours=None, total_spent_hours=0.0),
        ]

    def get_time_entries_for_issues(
        self, issue_ids: list[int], limit_per_issue: int = 5
    ) -> dict[int, list[TimeEntry]]:
        self.entry_calls.append((issue_ids, limit_per_issue))
        return {1: [make_entry(10, 1)], 2: []}

    def get_time_entries(
        self,
        user_id,
        spent_on_from: date | None = None,
        spent_on_to: date | None = None,
    ) -> list[TimeEntry]:
        self.period_calls.append((spent_on_from, spent_on_to))
        return [make_entry(11, 1)]


def test_fetch_dashboard_uses_one_entries_request() -> None:
    client = FakeDashboardClient()
    data = fetch_dashboard(client, 7, date(2026, 1, 1), date(2026, 1, 31))

    assert client.entry_calls == [([1, 2], 5)]
    assert [issue.id for issue in data.issues] == [1, 2]
    assert [entry.id for entry in data.issues[0].time_entries] == [10]
    assert data.issues[1].time_entries == []
    assert [entry.id for entry in data.period_entries] == [11]
    assert client.period_calls == [(date(2026, 1, 1), date(2026, 1, 31))]
    assert isinstance(data.fetched_at, datetime)
