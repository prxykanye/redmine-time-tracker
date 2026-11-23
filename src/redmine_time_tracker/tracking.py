"""Track lifecycle rules kept out of the GUI.

Starting a track pauses every other running track. A running track writes a
heartbeat while the application is alive, so after a crash the next launch can
tell how much time is trustworthy and how much is an artifact of the shutdown.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .database import Database
from .models import LocalTrack

ORPHAN_THRESHOLD = timedelta(seconds=90)


class RecoveryMode(StrEnum):
    UNTIL_HEARTBEAT = "until_heartbeat"
    UNTIL_NOW = "until_now"


@dataclass
class OrphanTrack:
    track: LocalTrack
    idle_seconds: int
    recoverable_seconds: int
    total_seconds: int


class TrackService:
    def __init__(
        self,
        database: Database,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.database = database
        self.clock = clock

    def start(self, track_id: int) -> LocalTrack | None:
        """Start a track, pausing the previously running one."""
        for running in self.database.list_running():
            if running.id is not None and running.id != track_id:
                self.database.pause(running.id, self.clock())
        return self.database.start(track_id, self.clock())

    def pause(self, track_id: int) -> LocalTrack | None:
        return self.database.pause(track_id, self.clock())

    def heartbeat_active(self) -> LocalTrack | None:
        active = self.database.get_active()
        if active is None or active.id is None:
            return None
        return self.database.heartbeat(active.id, self.clock())

    def find_orphan(self, threshold: timedelta = ORPHAN_THRESHOLD) -> OrphanTrack | None:
        """Return a running track that clearly survived an unclean shutdown."""
        active = self.database.get_active()
        if active is None:
            return None
        now = self.clock()
        marker = active.last_heartbeat_at or active.started_at
        if marker is None:
            return None
        if now - marker < threshold:
            return None

        recoverable = active.elapsed_seconds
        if active.started_at and active.last_heartbeat_at:
            recoverable += max(
                0, int((active.last_heartbeat_at - active.started_at).total_seconds())
            )
        return OrphanTrack(
            track=active,
            idle_seconds=max(0, int((now - marker).total_seconds())),
            recoverable_seconds=recoverable,
            total_seconds=active.current_elapsed_seconds(now),
        )

    def recover(self, track_id: int, mode: RecoveryMode) -> LocalTrack | None:
        track = self.database.get(track_id)
        if track is None:
            return None
        if mode is RecoveryMode.UNTIL_NOW:
            return self.database.pause(track_id, self.clock())
        return self.database.pause(track_id, self.clock(), cap_at_heartbeat=True)
