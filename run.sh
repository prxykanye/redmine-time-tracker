#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
    exec uv run redmine-time-tracker "$@"
fi

PYTHONPATH=src exec python3 -m redmine_time_tracker "$@"
