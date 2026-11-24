from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta

import pytest

from redmine_time_tracker.database import Database
from redmine_time_tracker.models import LocalTrack, TrackStatus

TrackFactory = Callable[..., LocalTrack]


def test_save_and_read(db: Database, make_track: TrackFactory) -> None:
    track = db.save(make_track())
    assert track.id is not None

    loaded = db.get(track.id)
    assert loaded is not None
    assert loaded.issue_id == 1
    assert loaded.status is TrackStatus.PAUSED
    assert loaded.created_at is not None


def test_start_and_pause_accumulates(db: Database, make_track: TrackFactory) -> None:
    track = db.save(make_track())
    assert track.id is not None
    start = datetime(2026, 1, 5, 9, 0, 0)
    db.start(track.id, start)

    active = db.get_active()
    assert active is not None
    assert active.id == track.id
    assert active.started_at == start

    paused = db.pause(track.id, start + timedelta(seconds=120))
    assert paused is not None
    assert paused.status is TrackStatus.PAUSED
    assert paused.elapsed_seconds == 120
    assert paused.started_at is None


def test_heartbeat_restarts_window(db: Database, make_track: TrackFactory) -> None:
    track = db.save(make_track())
    assert track.id is not None
    start = datetime(2026, 1, 5, 9, 0, 0)
    db.start(track.id, start)
    db.heartbeat(track.id, start + timedelta(seconds=30))

    active = db.get(track.id)
    assert active is not None
    assert active.elapsed_seconds == 30
    assert active.started_at == start + timedelta(seconds=30)
    assert active.last_heartbeat_at == start + timedelta(seconds=30)

    paused = db.pause(track.id, start + timedelta(seconds=50))
    assert paused is not None
    assert paused.elapsed_seconds == 50


def test_pause_without_heartbeat_does_not_invent_time(
    db: Database, make_track: TrackFactory
) -> None:
    track = db.save(make_track())
    assert track.id is not None
    start = datetime(2026, 1, 5, 9, 0, 0)
    db.start(track.id, start)
    # Simulate a legacy row: running, started_at set, heartbeat column empty.
    with db.connect() as connection, connection:
        connection.execute(
            "UPDATE local_tracks SET last_heartbeat_at = NULL WHERE id = ?", (track.id,)
        )

    paused = db.pause(track.id, start + timedelta(hours=2), cap_at_heartbeat=True)
    assert paused is not None
    assert paused.elapsed_seconds == 0


def test_pause_on_paused_track_is_noop(db: Database, make_track: TrackFactory) -> None:
    track = db.save(make_track(elapsed_seconds=90))
    assert track.id is not None
    paused = db.pause(track.id)
    assert paused is not None
    assert paused.elapsed_seconds == 90


def test_published_track_is_kept_for_history(db: Database, make_track: TrackFactory) -> None:
    track = db.save(make_track(elapsed_seconds=3600))
    assert track.id is not None
    db.mark_published(track.id, redmine_entry_id=777)

    loaded = db.get(track.id)
    assert loaded is not None
    assert loaded.status is TrackStatus.PUBLISHED
    assert loaded.redmine_entry_id == 777
    assert loaded.published_at is not None
    assert db.list_pending() == []

    history = db.list_published_between(date(2026, 1, 1), date(2026, 1, 31))
    assert [item.id for item in history] == [track.id]


def test_published_track_outside_range_is_excluded(db: Database, make_track: TrackFactory) -> None:
    track = db.save(make_track(date=date(2025, 12, 1)))
    assert track.id is not None
    db.mark_published(track.id, 1)
    assert db.list_published_between(date(2026, 1, 1), date(2026, 1, 31)) == []


def test_two_pending_drafts_for_one_entry_are_rejected(
    db: Database, make_track: TrackFactory
) -> None:
    db.save(make_track(source_time_entry_id=42))
    with pytest.raises(sqlite3.IntegrityError):
        db.save(make_track(source_time_entry_id=42))


def test_published_does_not_block_new_draft(db: Database, make_track: TrackFactory) -> None:
    first = db.save(make_track(source_time_entry_id=42))
    assert first.id is not None
    db.mark_published(first.id, 42)

    second = db.save(make_track(source_time_entry_id=42))
    assert second.id is not None


def test_pending_issue_subjects(db: Database, make_track: TrackFactory) -> None:
    db.save(make_track(issue_id=10, issue_subject="First"))
    db.save(make_track(issue_id=20, issue_subject="Second"))
    published = db.save(make_track(issue_id=30, issue_subject="Third"))
    assert published.id is not None
    db.mark_published(published.id, 1)

    assert db.pending_issue_subjects() == {10: "First", 20: "Second"}


def test_tracks_by_issue_groups_and_filters(db: Database, make_track: TrackFactory) -> None:
    first = db.save(make_track(issue_id=10, issue_subject="First"))
    second = db.save(make_track(issue_id=20, issue_subject="Second"))
    third = db.save(make_track(issue_id=10, issue_subject="First", description="another"))
    cancelled = db.save(
        make_track(issue_id=10, issue_subject="First", status=TrackStatus.CANCELLED)
    )

    grouped = db.tracks_by_issue([10, 20])
    assert {track.id for track in grouped[10]} == {first.id, third.id}
    assert [track.id for track in grouped[20]] == [second.id]

    with_cancelled = db.tracks_by_issue([10], include_cancelled=True)
    assert {track.id for track in with_cancelled[10]} == {first.id, third.id, cancelled.id}
    assert db.tracks_by_issue([]) == {}


def test_migration_from_legacy_schema(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE local_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            issue_subject TEXT NOT NULL,
            activity_id INTEGER NOT NULL,
            activity_name TEXT NOT NULL,
            description TEXT NOT NULL,
            track_date TEXT NOT NULL,
            status TEXT NOT NULL,
            elapsed_seconds INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO local_tracks (
            issue_id, issue_subject, activity_id, activity_name, description,
            track_date, status, elapsed_seconds, created_at, updated_at
        ) VALUES (5, 'Legacy', 9, 'Dev', 'old row', '2026-01-01', 'paused', 0,
                  '2026-01-01T10:00:00', '2026-01-01T10:00:00')
        """
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.init()

    migrated = database.get(1)
    assert migrated is not None
    assert migrated.issue_subject == "Legacy"
    assert migrated.source_time_entry_id is None
    assert migrated.redmine_entry_id is None

    with database.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == 2
