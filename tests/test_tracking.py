from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest

from redmine_time_tracker.database import Database
from redmine_time_tracker.models import LocalTrack
from redmine_time_tracker.tracking import RecoveryMode, TrackService

TrackFactory = Callable[..., LocalTrack]


class FakeClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: int) -> None:
        self.moment += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 1, 5, 9, 0, 0))


@pytest.fixture
def service(db: Database, clock: FakeClock) -> TrackService:
    return TrackService(db, clock=clock)


def test_start_pauses_previous_track(
    db: Database, service: TrackService, make_track: TrackFactory
) -> None:
    first = db.save(make_track(issue_id=1))
    second = db.save(make_track(issue_id=2))
    assert first.id is not None
    assert second.id is not None

    service.start(first.id)
    service.start(second.id)

    assert db.get_active() is not None
    active = db.get_active()
    assert active is not None
    assert active.id == second.id
    paused = db.get(first.id)
    assert paused is not None
    assert paused.status.value == "paused"


def test_recent_running_track_is_not_orphan(
    db: Database, service: TrackService, clock: FakeClock, make_track: TrackFactory
) -> None:
    track = db.save(make_track())
    assert track.id is not None
    service.start(track.id)
    clock.advance(5)

    assert service.find_orphan() is None


def test_orphan_detection_after_long_gap(
    db: Database,
    service: TrackService,
    clock: FakeClock,
    make_track: TrackFactory,
) -> None:
    track = db.save(make_track())
    assert track.id is not None
    service.start(track.id)
    service.heartbeat_active()
    clock.advance(600)

    orphan = service.find_orphan()
    assert orphan is not None
    assert orphan.idle_seconds == pytest.approx(600, abs=1)
    assert orphan.recoverable_seconds == 0
    assert orphan.total_seconds == pytest.approx(600, abs=1)


def test_recover_until_heartbeat_drops_idle_time(
    db: Database,
    service: TrackService,
    clock: FakeClock,
    make_track: TrackFactory,
) -> None:
    track = db.save(make_track())
    assert track.id is not None
    service.start(track.id)
    clock.advance(30)
    service.heartbeat_active()
    clock.advance(570)

    recovered = service.recover(track.id, RecoveryMode.UNTIL_HEARTBEAT)
    assert recovered is not None
    assert recovered.status.value == "paused"
    assert recovered.elapsed_seconds == 30


def test_recover_until_now_keeps_idle_time(
    db: Database,
    service: TrackService,
    clock: FakeClock,
    make_track: TrackFactory,
) -> None:
    track = db.save(make_track())
    assert track.id is not None
    service.start(track.id)
    clock.advance(600)

    recovered = service.recover(track.id, RecoveryMode.UNTIL_NOW)
    assert recovered is not None
    assert recovered.elapsed_seconds == 600
