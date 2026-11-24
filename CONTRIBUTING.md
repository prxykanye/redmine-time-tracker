# Contributing

## Development setup

```bash
git clone https://github.com/prxykanye/redmine-time-tracker.git
cd redmine-time-tracker
uv sync
pre-commit install
```

## Before opening a pull request

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

All four commands must pass. The CI runs the same set on Python 3.13 and 3.14.

## Guidelines

- Keep network and database access out of Qt signal handlers where possible.
  The GUI layer should stay thin; lifecycle rules belong in `tracking.py`.
- Every change to rounding, storage or recovery needs a test. Those rules
  decide how much time ends up in someone's timesheet.
- Do not hard-code a Redmine URL, a company name or a personal path.
- Write commit messages in the imperative mood: `Add heartbeat recovery`,
  not `Added` or `Adds`.
- Localise user-facing strings in Russian to match the existing interface.

## Reporting bugs

Include the Python version, the operating system, the Redmine version, and the
relevant tail of the log file. Remove your API key before pasting logs.
