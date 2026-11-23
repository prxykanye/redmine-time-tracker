"""Filesystem locations used by the application.

Everything lives under the platform-specific user directories so the package
can be installed read-only (for example with ``pipx``). Tests override the
locations with ``RTT_CONFIG_DIR``, ``RTT_DATA_DIR`` and ``RTT_LOG_DIR``.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

APP_NAME = "redmine-time-tracker"


def _resolve(env_var: str, default: str) -> Path:
    override = os.environ.get(env_var)
    path = Path(override) if override else Path(default)
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    return _resolve("RTT_CONFIG_DIR", platformdirs.user_config_dir(APP_NAME))


def data_dir() -> Path:
    return _resolve("RTT_DATA_DIR", platformdirs.user_data_dir(APP_NAME))


def log_dir() -> Path:
    return _resolve("RTT_LOG_DIR", platformdirs.user_log_dir(APP_NAME))


def database_path() -> Path:
    return data_dir() / "data.db"


def lock_path() -> Path:
    return data_dir() / "instance.lock"


def log_path() -> Path:
    return log_dir() / "app.log"
