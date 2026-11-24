"""SQLite storage for local tracks.

The schema is versioned with ``PRAGMA user_version``. Version 1 replaces the
ad-hoc ``ALTER TABLE`` calls of the original prototype: published tracks are
kept for the local audit trail instead of being deleted, and running tracks
carry a heartbeat so an unclean shutdown can be detected.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from .models import Activity, Issue, LocalTrack, TimeEntry, TrackStatus

SCHEMA_VERSION = 2

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS local_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    issue_subject TEXT NOT NULL,
    activity_id INTEGER NOT NULL,
    activity_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    track_date TEXT NOT NULL,
    status TEXT NOT NULL,
    elapsed_seconds INTEGER NOT NULL DEFAULT 0,
    source_time_entry_id INTEGER,
    source_updated_on TEXT,
    started_at TEXT,
    last_heartbeat_at TEXT,
    redmine_entry_id INTEGER,
    published_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_INDEXES_SQL = (
    """
    CREATE INDEX IF NOT EXISTS idx_local_tracks_issue
    ON local_tracks(issue_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_local_tracks_status
    ON local_tracks(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_local_tracks_date
    ON local_tracks(track_date)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_local_tracks_source_active
    ON local_tracks(source_time_entry_id)
    WHERE source_time_entry_id IS NOT NULL AND status IN ('running', 'paused')
    """,
)

_EXTRA_COLUMNS = {
    "source_updated_on": "TEXT",
    "last_heartbeat_at": "TEXT",
    "redmine_entry_id": "INTEGER",
    "published_at": "TEXT",
    "source_time_entry_id": "INTEGER",
    "started_at": "TEXT",
}

_CACHE_SQL = (
    """
    CREATE TABLE IF NOT EXISTS cached_issues (
        id INTEGER PRIMARY KEY,
        subject TEXT NOT NULL,
        estimated_hours REAL,
        total_spent_hours REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cached_activities (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cached_time_entries (
        id INTEGER PRIMARY KEY,
        issue_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL DEFAULT 0,
        hours REAL NOT NULL,
        comments TEXT NOT NULL DEFAULT '',
        spent_on TEXT NOT NULL,
        activity_id INTEGER NOT NULL DEFAULT 0,
        activity_name TEXT NOT NULL DEFAULT '',
        created_on TEXT NOT NULL,
        updated_on TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cached_time_entries_issue
    ON cached_time_entries(issue_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS app_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Database:
    """Thin repository over a single SQLite file."""

    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self.path = Path(path)
        self.timeout = timeout

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
        try:
            yield connection
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def init(self) -> None:
        with self.connect() as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                self._apply_schema(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _apply_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(_TABLE_SQL)
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(local_tracks)")}
        for column, column_type in _EXTRA_COLUMNS.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE local_tracks ADD COLUMN {column} {column_type}")
        for statement in _INDEXES_SQL:
            connection.execute(statement)
        for statement in _CACHE_SQL:
            connection.execute(statement)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def _row_to_track(self, row: sqlite3.Row) -> LocalTrack:
        return LocalTrack(
            id=row["id"],
            issue_id=row["issue_id"],
            issue_subject=row["issue_subject"],
            activity_id=row["activity_id"],
            activity_name=row["activity_name"],
            description=row["description"],
            date=date.fromisoformat(row["track_date"]),
            status=TrackStatus(row["status"]),
            elapsed_seconds=row["elapsed_seconds"],
            source_time_entry_id=row["source_time_entry_id"],
            source_updated_on=_parse(row["source_updated_on"]),
            started_at=_parse(row["started_at"]),
            last_heartbeat_at=_parse(row["last_heartbeat_at"]),
            redmine_entry_id=row["redmine_entry_id"],
            published_at=_parse(row["published_at"]),
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
        )

    def get(self, track_id: int) -> LocalTrack | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM local_tracks WHERE id = ?", (track_id,)
            ).fetchone()
        return self._row_to_track(row) if row else None

    def get_active(self) -> LocalTrack | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM local_tracks
                WHERE status = ?
                ORDER BY started_at IS NULL, started_at DESC
                LIMIT 1
                """,
                (TrackStatus.RUNNING.value,),
            ).fetchone()
        return self._row_to_track(row) if row else None

    def list_running(self) -> list[LocalTrack]:
        return self._list("status = ?", (TrackStatus.RUNNING.value,))

    def list_pending(self) -> list[LocalTrack]:
        return self._list(
            "status IN (?, ?) ORDER BY updated_at DESC",
            (TrackStatus.RUNNING.value, TrackStatus.PAUSED.value),
        )

    def list_for_issue(self, issue_id: int, include_cancelled: bool = False) -> list[LocalTrack]:
        if include_cancelled:
            return self._list("issue_id = ? ORDER BY created_at DESC", (issue_id,))
        return self._list(
            "issue_id = ? AND status != ? ORDER BY created_at DESC",
            (issue_id, TrackStatus.CANCELLED.value),
        )

    def tracks_by_issue(
        self,
        issue_ids: list[int],
        include_cancelled: bool = False,
    ) -> dict[int, list[LocalTrack]]:
        """Return tracks for many issues in a single query."""
        unique = list(dict.fromkeys(issue_ids))
        if not unique:
            return {}

        placeholders = ",".join("?" for _ in unique)
        params: list[object] = list(unique)
        where = f"issue_id IN ({placeholders})"
        if not include_cancelled:
            where += " AND status != ?"
            params.append(TrackStatus.CANCELLED.value)

        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM local_tracks WHERE {where} ORDER BY created_at DESC",
                tuple(params),
            ).fetchall()

        grouped: dict[int, list[LocalTrack]] = {}
        for row in rows:
            track = self._row_to_track(row)
            grouped.setdefault(track.issue_id, []).append(track)
        return grouped

    def list_published(self, limit: int = 200) -> list[LocalTrack]:
        return self._list(
            "status = ? ORDER BY published_at DESC LIMIT ?",
            (
                TrackStatus.PUBLISHED.value,
                limit,
            ),
        )

    def list_published_between(self, start: date, end: date) -> list[LocalTrack]:
        return self._list(
            """
            status = ? AND track_date BETWEEN ? AND ?
            ORDER BY track_date DESC, id DESC
            """,
            (TrackStatus.PUBLISHED.value, start.isoformat(), end.isoformat()),
        )

    def _list(self, where: str, params: tuple[object, ...]) -> list[LocalTrack]:
        query = f"SELECT * FROM local_tracks WHERE {where}"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_track(row) for row in rows]

    def pending_issue_subjects(self) -> dict[int, str]:
        """Issue ids that still have an unpublished track, with a display subject."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT issue_id, issue_subject, MAX(updated_at) AS last_update
                FROM local_tracks
                WHERE status IN (?, ?)
                GROUP BY issue_id
                ORDER BY last_update DESC
                """,
                (TrackStatus.RUNNING.value, TrackStatus.PAUSED.value),
            ).fetchall()
        return {row["issue_id"]: row["issue_subject"] for row in rows}

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def save(self, track: LocalTrack) -> LocalTrack:
        now = datetime.now()
        values = (
            track.issue_id,
            track.issue_subject,
            track.activity_id,
            track.activity_name,
            track.description,
            track.date.isoformat(),
            track.status.value,
            int(track.elapsed_seconds),
            track.source_time_entry_id,
            _iso(track.source_updated_on),
            _iso(track.started_at),
            _iso(track.last_heartbeat_at),
            track.redmine_entry_id,
            _iso(track.published_at),
        )
        with self.connect() as connection, connection:
            if track.id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO local_tracks (
                        issue_id, issue_subject, activity_id, activity_name, description,
                        track_date, status, elapsed_seconds, source_time_entry_id,
                        source_updated_on, started_at, last_heartbeat_at,
                        redmine_entry_id, published_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*values, now.isoformat(), now.isoformat()),
                )
                track.id = int(cursor.lastrowid or 0)
            else:
                connection.execute(
                    """
                    UPDATE local_tracks SET
                        issue_id = ?, issue_subject = ?, activity_id = ?, activity_name = ?,
                        description = ?, track_date = ?, status = ?, elapsed_seconds = ?,
                        source_time_entry_id = ?, source_updated_on = ?, started_at = ?,
                        last_heartbeat_at = ?, redmine_entry_id = ?, published_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (*values, now.isoformat(), track.id),
                )
        track.created_at = track.created_at or now
        track.updated_at = now
        return track

    def start(self, track_id: int, at: datetime | None = None) -> LocalTrack | None:
        moment = at or datetime.now()
        with self.connect() as connection, connection:
            connection.execute(
                """
                UPDATE local_tracks
                SET status = ?, started_at = ?, last_heartbeat_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TrackStatus.RUNNING.value,
                    moment.isoformat(),
                    moment.isoformat(),
                    moment.isoformat(),
                    track_id,
                ),
            )
        return self.get(track_id)

    def pause(
        self,
        track_id: int,
        at: datetime | None = None,
        *,
        cap_at_heartbeat: bool = False,
    ) -> LocalTrack | None:
        """Pause a running track and accumulate the current run.

        ``cap_at_heartbeat`` ignores time after the last heartbeat, which is
        what the recovery dialog uses after an unclean shutdown.
        """
        track = self.get(track_id)
        if track is None:
            return None
        end = None
        if cap_at_heartbeat and track.status is TrackStatus.RUNNING and track.started_at:
            # Without a heartbeat there is no trustworthy end; do not invent time.
            end = track.last_heartbeat_at or track.started_at
        end = end or at or datetime.now()
        extra = 0
        if track.status is TrackStatus.RUNNING and track.started_at:
            extra = max(0, int((end - track.started_at).total_seconds()))
        track.elapsed_seconds += extra
        track.status = TrackStatus.PAUSED
        track.started_at = None
        track.last_heartbeat_at = None
        return self.save(track)

    def heartbeat(self, track_id: int, at: datetime | None = None) -> LocalTrack | None:
        """Persist elapsed time of a running track and restart its window."""
        moment = at or datetime.now()
        track = self.get(track_id)
        if track is None or track.status is not TrackStatus.RUNNING or not track.started_at:
            return track
        track.elapsed_seconds += max(0, int((moment - track.started_at).total_seconds()))
        track.started_at = moment
        track.last_heartbeat_at = moment
        return self.save(track)

    def mark_published(
        self,
        track_id: int,
        redmine_entry_id: int | None,
        at: datetime | None = None,
    ) -> LocalTrack | None:
        moment = at or datetime.now()
        track = self.get(track_id)
        if track is None:
            return None
        track.status = TrackStatus.PUBLISHED
        track.redmine_entry_id = redmine_entry_id
        track.published_at = moment
        track.started_at = None
        track.last_heartbeat_at = None
        return self.save(track)

    def set_elapsed(self, track_id: int, elapsed_seconds: int) -> LocalTrack | None:
        track = self.get(track_id)
        if track is None:
            return None
        track.elapsed_seconds = max(0, elapsed_seconds)
        return self.save(track)

    def delete(self, track_id: int) -> None:
        with self.connect() as connection, connection:
            connection.execute("DELETE FROM local_tracks WHERE id = ?", (track_id,))

    # ------------------------------------------------------------------
    # Offline cache
    # ------------------------------------------------------------------
    def replace_cache(
        self,
        issues: list[Issue],
        activities: list[Activity],
        fetched_at: datetime,
    ) -> None:
        """Replace the cached issue list with a fresh snapshot."""
        issue_rows = [
            (issue.id, issue.subject, issue.estimated_hours, issue.total_spent_hours)
            for issue in issues
        ]
        activity_rows = [
            (activity.id, activity.name, int(activity.is_default)) for activity in activities
        ]
        entry_rows = [
            (
                entry.id,
                entry.issue_id,
                entry.user_id,
                entry.hours,
                entry.comments,
                entry.spent_on.isoformat(),
                entry.activity_id,
                entry.activity_name,
                entry.created_on.isoformat(),
                entry.updated_on.isoformat(),
            )
            for issue in issues
            for entry in issue.time_entries
        ]
        with self.connect() as connection, connection:
            connection.execute("DELETE FROM cached_issues")
            connection.execute("DELETE FROM cached_activities")
            connection.execute("DELETE FROM cached_time_entries")
            if issue_rows:
                connection.executemany(
                    "INSERT INTO cached_issues "
                    "(id, subject, estimated_hours, total_spent_hours) VALUES (?, ?, ?, ?)",
                    issue_rows,
                )
            if activity_rows:
                connection.executemany(
                    "INSERT INTO cached_activities (id, name, is_default) VALUES (?, ?, ?)",
                    activity_rows,
                )
            if entry_rows:
                connection.executemany(
                    "INSERT INTO cached_time_entries "
                    "(id, issue_id, user_id, hours, comments, spent_on, activity_id, "
                    "activity_name, created_on, updated_on) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    entry_rows,
                )
            connection.execute(
                "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                ("last_sync", fetched_at.isoformat()),
            )

    def load_cached(
        self,
    ) -> tuple[list[Issue], list[Activity], datetime | None]:
        """Return the last snapshot, or empty structures when nothing is cached."""
        with self.connect() as connection:
            issue_rows = connection.execute("SELECT * FROM cached_issues ORDER BY id").fetchall()
            activity_rows = connection.execute(
                "SELECT * FROM cached_activities ORDER BY id"
            ).fetchall()
            entry_rows = connection.execute(
                "SELECT * FROM cached_time_entries ORDER BY updated_on DESC"
            ).fetchall()
            state_row = connection.execute(
                "SELECT value FROM app_state WHERE key = ?", ("last_sync",)
            ).fetchone()

        entries_by_issue: dict[int, list[TimeEntry]] = {}
        for row in entry_rows:
            entries_by_issue.setdefault(row["issue_id"], []).append(
                TimeEntry(
                    id=row["id"],
                    issue_id=row["issue_id"],
                    user_id=row["user_id"],
                    hours=row["hours"],
                    comments=row["comments"],
                    spent_on=date.fromisoformat(row["spent_on"]),
                    activity_id=row["activity_id"],
                    activity_name=row["activity_name"],
                    created_on=datetime.fromisoformat(row["created_on"]),
                    updated_on=datetime.fromisoformat(row["updated_on"]),
                )
            )

        issues = [
            Issue(
                id=row["id"],
                subject=row["subject"],
                estimated_hours=row["estimated_hours"],
                total_spent_hours=row["total_spent_hours"],
                time_entries=entries_by_issue.get(row["id"], [])[:5],
            )
            for row in issue_rows
        ]
        activities = [
            Activity(
                id=row["id"],
                name=row["name"],
                is_default=bool(row["is_default"]),
            )
            for row in activity_rows
        ]
        last_sync = datetime.fromisoformat(state_row["value"]) if state_row else None
        return issues, activities, last_sync

    def clear_cache(self) -> None:
        with self.connect() as connection, connection:
            connection.execute("DELETE FROM cached_issues")
            connection.execute("DELETE FROM cached_activities")
            connection.execute("DELETE FROM cached_time_entries")
            connection.execute("DELETE FROM app_state WHERE key = ?", ("last_sync",))
