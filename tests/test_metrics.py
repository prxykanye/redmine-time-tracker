from __future__ import annotations

from datetime import date, datetime

from redmine_time_tracker.metrics import compute_metrics, workdays_in_range
from redmine_time_tracker.models import TimeEntry


def entry_on(spent_on: date, hours: float) -> TimeEntry:
    return TimeEntry(
        id=1,
        issue_id=1,
        user_id=7,
        hours=hours,
        comments="",
        spent_on=spent_on,
        activity_id=9,
        activity_name="Development",
        created_on=datetime.combine(spent_on, datetime.min.time()),
        updated_on=datetime.combine(spent_on, datetime.min.time()),
    )


def test_workdays_in_range() -> None:
    assert workdays_in_range(date(2026, 1, 5), date(2026, 1, 11)) == 5
    assert workdays_in_range(date(2026, 1, 10), date(2026, 1, 11)) == 0
    assert workdays_in_range(date(2026, 1, 7), date(2026, 1, 5)) == 0


def test_metrics_are_prorated_by_elapsed_workdays() -> None:
    today = date(2026, 1, 7)  # Wednesday
    entries = [
        entry_on(date(2026, 1, 7), 2.0),
        entry_on(date(2026, 1, 6), 1.0),
        entry_on(date(2025, 12, 31), 5.0),
    ]

    values = compute_metrics(entries, today)

    assert values.spent_today == 2.0
    assert values.spent_week == 3.0
    assert values.spent_month == 3.0
    assert values.planned_today == 8.0
    assert values.planned_week == 24.0
    assert values.planned_month == 40.0


def test_metrics_on_first_working_day_of_month() -> None:
    today = date(2026, 2, 2)  # Monday, the first working day of February
    values = compute_metrics([entry_on(today, 4.0)], today)
    assert values.spent_month == 4.0
    assert values.planned_month == 8.0
    assert values.planned_week == 8.0
