# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-11-23

### Changed

- Project moved to a `src/` package layout with a `pyproject.toml` entry point.
- Configuration, database and logs moved to platform user directories.
- Rounding now always goes up to the next 5 minutes; zero stays zero.
- Continuing a Redmine entry asks whether to create a new entry or update the
  original, and warns when the original changed remotely.
- Publishing drafts are kept in the local history instead of being deleted.
- Metrics plan is prorated by the working days elapsed in the period.
- Window closing falls back to a normal quit when no system tray is available.
- The issue list, drafts and timers stay usable while a request is in flight.

### Added

- Heartbeat-based crash recovery with a dialog on the next launch.
- Single-instance lock.
- Partial unique index preventing two pending drafts for the same entry.
- Schema migrations through `PRAGMA user_version`.
- Local publication history dialog.
- Logging to a rotating file and an unhandled exception hook.
- Typed API errors for auth, connection and response failures.
- Pagination guard for misbehaving servers.
- Offline cache of the issue list in SQLite with a banner in the window.
- Background worker for connection, refresh and publishing.
- One paginated request for the recent entries of all issues.
- Unpublished draft total next to the period metrics.
- Test suite, ruff, mypy, pre-commit and GitHub Actions.

### Fixed

- `TimeEntry` was referenced without an import in `gui/widgets.py`, which broke
  the application on Python 3.13.
- A draft with zero tracked seconds could be published as 5 minutes.
- A cancelled publish dialog paused the running draft.
- Issues with drafts disappeared when they left the open issue list.
- Progress and spent time labels were never refreshed after the first render.
- Timeout and non-JSON responses escaped the `RedmineError` handler.
- Infinite pagination loop when a server returned an empty page with a
  non-zero total count.
- Hard-coded company URL and personal paths removed from the repository.

## [0.1.0]

Initial prototype: issue list, local drafts, rounded publishing, tray icon.
