"""Data models shared by the API client, storage and GUI."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

ROUNDING_STEP_MINUTES = 5


class TrackStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    PUBLISHED = "published"
    CANCELLED = "cancelled"

    @property
    def is_pending(self) -> bool:
        return self in (TrackStatus.RUNNING, TrackStatus.PAUSED)


def round_up_minutes(elapsed_seconds: int) -> int:
    """Round tracked time up to the nearest step.

    Zero and negative values stay zero: a track that never ran must not turn
    into five minutes of billable time.
    """
    if elapsed_seconds <= 0:
        return 0
    minutes = elapsed_seconds / 60
    return math.ceil(minutes / ROUNDING_STEP_MINUTES) * ROUNDING_STEP_MINUTES


@dataclass
class TimeEntry:
    id: int
    issue_id: int
    user_id: int
    hours: float
    comments: str
    spent_on: date
    activity_id: int
    activity_name: str
    created_on: datetime
    updated_on: datetime


@dataclass
class Issue:
    id: int
    subject: str
    estimated_hours: float | None
    total_spent_hours: float
    time_entries: list[TimeEntry] = field(default_factory=list)
    local_only: bool = False

    @property
    def display_name(self) -> str:
        return f"#{self.id} {self.subject}"

    @property
    def progress_percent(self) -> float:
        if not self.estimated_hours:
            return 0.0
        return min((self.total_spent_hours / self.estimated_hours) * 100, 999.9)


@dataclass
class Activity:
    id: int
    name: str
    is_default: bool = False


@dataclass
class LocalTrack:
    id: int | None
    issue_id: int
    issue_subject: str
    activity_id: int
    activity_name: str
    description: str
    date: date
    status: TrackStatus
    elapsed_seconds: int
    source_time_entry_id: int | None = None
    source_updated_on: datetime | None = None
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    redmine_entry_id: int | None = None
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def current_elapsed_seconds(self, now: datetime | None = None) -> int:
        """Elapsed seconds, including the current run when the track is running."""
        if self.status is TrackStatus.RUNNING and self.started_at:
            current = now or datetime.now()
            extra = (current - self.started_at).total_seconds()
            return int(self.elapsed_seconds + max(0.0, extra))
        return max(0, self.elapsed_seconds)

    @property
    def elapsed_hours(self) -> float:
        return self.current_elapsed_seconds() / 3600.0

    @staticmethod
    def rounded_hours_from_seconds(elapsed_seconds: int) -> float:
        return round_up_minutes(elapsed_seconds) / 60.0

    @property
    def rounded_hours(self) -> float:
        return self.rounded_hours_from_seconds(self.current_elapsed_seconds())

    @property
    def rounded_minutes(self) -> int:
        return round_up_minutes(self.current_elapsed_seconds())

    @property
    def display_elapsed(self) -> str:
        return format_hms(self.current_elapsed_seconds())

    @property
    def display_rounded(self) -> str:
        return format_hm(self.rounded_minutes)


def format_hms(total_seconds: int) -> str:
    hours, remainder = divmod(max(0, total_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_hm(total_minutes: int) -> str:
    hours, minutes = divmod(max(0, total_minutes), 60)
    return f"{hours}:{minutes:02d}"
