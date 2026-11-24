"""Metric calculations kept out of the GUI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .models import TimeEntry

DAILY_WORK_HOURS = 8.0


@dataclass(frozen=True)
class MetricValues:
    spent_today: float
    spent_week: float
    spent_month: float
    planned_today: float
    planned_week: float
    planned_month: float


def workdays_in_range(start: date, end: date) -> int:
    """Count weekdays between two dates, inclusive."""
    if end < start:
        return 0
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def compute_metrics(
    entries: list[TimeEntry],
    today: date,
    daily_hours: float = DAILY_WORK_HOURS,
) -> MetricValues:
    """Compare published time with a plan prorated by elapsed working days."""
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    def spent_between(start: date, end: date) -> float:
        return sum(entry.hours for entry in entries if start <= entry.spent_on <= end)

    return MetricValues(
        spent_today=spent_between(today, today),
        spent_week=spent_between(week_start, today),
        spent_month=spent_between(month_start, today),
        planned_today=daily_hours,
        planned_week=max(1, workdays_in_range(week_start, today)) * daily_hours,
        planned_month=max(1, workdays_in_range(month_start, today)) * daily_hours,
    )
