"""Dashboard loading split from the GUI so it can run in a worker thread."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from .models import Activity, Issue, TimeEntry


class DashboardClient(Protocol):
    def get_activities(self) -> list[Activity]: ...

    def get_assigned_open_issues(self, user_id: int | str) -> list[Issue]: ...

    def get_time_entries_for_issues(
        self, issue_ids: list[int], limit_per_issue: int = 5
    ) -> dict[int, list[TimeEntry]]: ...

    def get_time_entries(
        self,
        user_id: int | str,
        spent_on_from: date | None = None,
        spent_on_to: date | None = None,
    ) -> list[TimeEntry]: ...


@dataclass(frozen=True)
class DashboardData:
    activities: list[Activity]
    issues: list[Issue]
    period_entries: list[TimeEntry]
    fetched_at: datetime


def fetch_dashboard(
    client: DashboardClient,
    user_id: int | str,
    period_start: date,
    period_end: date,
) -> DashboardData:
    """Load issues, their recent entries and the period entries in one job.

    Time entries for all issues come from a single paginated request instead of
    one request per issue.
    """
    activities = client.get_activities()
    issues = client.get_assigned_open_issues(user_id)
    entries_by_issue = client.get_time_entries_for_issues(
        [issue.id for issue in issues],
        limit_per_issue=5,
    )
    for issue in issues:
        issue.time_entries = entries_by_issue.get(issue.id, [])[:5]

    period_entries = client.get_time_entries(
        user_id,
        spent_on_from=period_start,
        spent_on_to=period_end,
    )
    return DashboardData(
        activities=activities,
        issues=issues,
        period_entries=period_entries,
        fetched_at=datetime.now(),
    )
