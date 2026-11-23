# Redmine Time Tracker

Desktop time tracker for Redmine. It keeps a local draft of your work, shows a
live timer per issue, rounds the tracked time and publishes it through the
Redmine REST API.

The tracker is deliberately offline-first: starting, pausing and editing a
draft never touches the network. Only publishing does.

## Features

- Loads open issues assigned to the current Redmine user, with estimate, spent
  time and progress percentage.
- Several local drafts per issue, with activity, description and spent-on date.
- Start, pause, resume, edit, publish and cancel a draft.
- Starting a draft automatically pauses the previously running one.
- Live timer that survives focus loss and interface rebuilds.
- Rounding up to 5 minutes on publish; a draft with zero tracked time is never
  published.
- "Continue" from an existing Redmine time entry. On publish you choose whether
  to create a new entry or update the original; an entry changed in Redmine
  since the draft was created triggers a confirmation.
- Local publication history: published drafts are kept in SQLite with the
  Redmine entry id instead of being deleted.
- Today / week / month metrics against a plan prorated by working days.
- Crash recovery: a running draft writes a heartbeat, and the next launch asks
  whether to keep the time up to the last heartbeat or include the downtime.
- Issues that disappeared from the open list but still have drafts stay visible.
- System tray with a single-instance lock.
- API key is stored with owner-only permissions and is never logged.

## Requirements

- Python 3.13 or newer
- A Redmine instance with the REST API enabled
- A Redmine API key (My account → API access key)

## Install

With `uv`:

```bash
git clone https://github.com/<you>/redmine-time-tracker.git
cd redmine-time-tracker
uv sync
uv run redmine-time-tracker
```

With `pipx`:

```bash
pipx install git+https://github.com/<you>/redmine-time-tracker.git
redmine-time-tracker
```

## First run

On the first launch the application asks for the Redmine URL and the API key.
Both are stored in the user configuration directory:

| Platform | Configuration | Database | Log |
| --- | --- | --- | --- |
| Linux | `~/.config/redmine-time-tracker/` | `~/.local/share/redmine-time-tracker/` | `~/.local/state/redmine-time-tracker/` |
| macOS | `~/Library/Application Support/redmine-time-tracker/` | same | `~/Library/Logs/redmine-time-tracker/` |
| Windows | `%APPDATA%\redmine-time-tracker\` | `%LOCALAPPDATA%\redmine-time-tracker\` | `%LOCALAPPDATA%\redmine-time-tracker\Logs\` |

`config.ini` holds the URL. `.env` holds the key in the form
`REDMINE_API_KEY=...` and is created with mode `0600`. The `REDMINE_API_KEY`
environment variable takes priority over the file.

Tests and portable installs can override the locations with `RTT_CONFIG_DIR`,
`RTT_DATA_DIR` and `RTT_LOG_DIR`.

## Publishing rules

Tracked time is rounded up to the nearest 5 minutes:

| Tracked | Published |
| --- | --- |
| 0 s | not published |
| 1 s – 5 min | 5 min |
| 5 min 1 s – 10 min | 10 min |
| 1 h 0 s – 1 h 5 min | 1 h 5 min |

The confirmation dialog always shows both the tracked and the rounded value.

## Time recovery

While a draft is running, the application writes a heartbeat every 30 seconds.
If the process is killed or the machine shuts down, the next launch finds a
running draft with an outdated heartbeat and asks what to do:

- keep the time up to the last heartbeat (default, ignores the downtime);
- include the whole period, downtime included.

In both cases the draft is paused afterwards.

## What is stored locally

SQLite database `data.db` with one table, `local_tracks`:

- issue id and subject, activity, description, spent-on date;
- status (`running`, `paused`, `published`, `cancelled`);
- accumulated seconds, start time and last heartbeat;
- source time entry id for continuations and the resulting Redmine entry id.

No credentials are stored in the database. Nothing is sent anywhere except to
the configured Redmine instance.

## Limitations

- Issues are not cached yet, so the issue list requires a working connection.
  Local drafts survive an outage and stay available through the recovery and
  history paths, but the full offline mode is not implemented.
- HTTP requests run in the GUI thread, so a slow server freezes the window
  during refresh.
- The interface is Russian-only.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

The test suite covers rounding, storage migrations, the partial unique index on
continuations, heartbeat and recovery logic, configuration and the API client
pagination. It runs without a Redmine server and without a display.

Layout:

```
src/redmine_time_tracker/
├── __main__.py          application entry point and single-instance lock
├── config.py            config.ini + .env
├── database.py          SQLite repository and schema migrations
├── models.py            dataclasses and rounding rules
├── paths.py             platform directories
├── redmine_client.py    REST client and error mapping
├── tracking.py          track lifecycle, heartbeat, crash recovery
└── gui/                 Qt widgets, dialogs and the main window
```

## License

MIT. See [LICENSE](LICENSE).
