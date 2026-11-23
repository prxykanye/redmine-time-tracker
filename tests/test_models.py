from __future__ import annotations

from datetime import date

import pytest

from redmine_time_tracker.models import (
    Issue,
    LocalTrack,
    TrackStatus,
    round_up_minutes,
)


def make_track(seconds: int = 0) -> LocalTrack:
    return LocalTrack(
        id=1,
        issue_id=1,
        issue_subject="Test",
        activity_id=1,
        activity_name="Dev",
        description="",
        date=date(2026, 1, 5),
        status=TrackStatus.PAUSED,
        elapsed_seconds=seconds,
    )


@pytest.mark.parametrize(
    ("seconds", "expected_minutes"),
    [
        (-10, 0),
        (0, 0),
        (1, 5),
        (60, 5),
        (299, 5),
        (300, 5),
        (301, 10),
        (600, 10),
        (601, 15),
        (720, 15),
        (750, 15),
        (751, 15),
        (900, 15),
        (3600, 60),
        (3601, 65),
    ],
)
def test_round_up_minutes(seconds: int, expected_minutes: int) -> None:
    assert round_up_minutes(seconds) == expected_minutes


def test_zero_track_stays_zero() -> None:
    track = make_track(0)
    assert track.rounded_minutes == 0
    assert track.rounded_hours == 0.0
    assert track.display_rounded == "0:00"


def test_short_track_rounds_to_five_minutes() -> None:
    track = make_track(1)
    assert track.rounded_minutes == 5
    assert track.rounded_hours == pytest.approx(5 / 60)


def test_negative_elapsed_is_clamped() -> None:
    track = make_track(-100)
    assert track.current_elapsed_seconds() == 0
    assert track.display_elapsed == "00:00:00"


def test_progress_percent_is_capped() -> None:
    issue = Issue(id=1, subject="Test", estimated_hours=2.0, total_spent_hours=100.0)
    assert issue.progress_percent == 999.9


def test_progress_percent_without_estimate() -> None:
    issue = Issue(id=1, subject="Test", estimated_hours=None, total_spent_hours=5.0)
    assert issue.progress_percent == 0.0
