from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from redmine_time_tracker.database import Database
from redmine_time_tracker.models import LocalTrack, TrackStatus

TrackFactory = Callable[..., LocalTrack]


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "data.db")
    database.init()
    return database


@pytest.fixture
def make_track() -> TrackFactory:
    def factory(**overrides: object) -> LocalTrack:
        values: dict[str, object] = {
            "id": None,
            "issue_id": 1,
            "issue_subject": "Test issue",
            "activity_id": 9,
            "activity_name": "Development",
            "description": "work",
            "date": date(2026, 1, 5),
            "status": TrackStatus.PAUSED,
            "elapsed_seconds": 0,
        }
        values.update(overrides)
        return LocalTrack(**values)  # type: ignore[arg-type]

    return factory
