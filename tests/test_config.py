from __future__ import annotations

import os
import stat

import pytest

from redmine_time_tracker.config import AppConfig, ConfigError, normalize_url


def test_defaults_are_empty(tmp_path) -> None:
    config = AppConfig(tmp_path, environ={})
    assert config.redmine_url == ""
    assert config.redmine_api_key == ""
    assert config.is_configured is False


def test_url_is_persisted_and_normalized(tmp_path) -> None:
    config = AppConfig(tmp_path, environ={})
    config.redmine_url = "https://redmine.example.com/"

    reloaded = AppConfig(tmp_path, environ={})
    assert reloaded.redmine_url == "https://redmine.example.com"


def test_invalid_url_is_rejected(tmp_path) -> None:
    config = AppConfig(tmp_path, environ={})
    with pytest.raises(ConfigError):
        config.redmine_url = "redmine.example.com"


def test_normalize_url_keeps_trailing_slash_off() -> None:
    assert normalize_url("  https://example.com/  ") == "https://example.com"
    assert normalize_url("") == ""


def test_api_key_is_stored_in_env_file(tmp_path) -> None:
    config = AppConfig(tmp_path, environ={})
    config.set_redmine_api_key("secret-key")

    env_file = tmp_path / ".env"
    assert env_file.read_text(encoding="utf-8").strip() == "REDMINE_API_KEY=secret-key"
    assert AppConfig(tmp_path, environ={}).redmine_api_key == "secret-key"

    if os.name == "posix":
        mode = stat.S_IMODE(env_file.stat().st_mode)
        assert mode == 0o600


def test_environment_variable_wins_over_env_file(tmp_path) -> None:
    config = AppConfig(tmp_path, environ={})
    config.set_redmine_api_key("from-file")
    config = AppConfig(tmp_path, environ={"REDMINE_API_KEY": "from-environ"})
    assert config.redmine_api_key == "from-environ"


def test_refresh_on_start_is_persisted(tmp_path) -> None:
    config = AppConfig(tmp_path, environ={})
    config.refresh_on_start = False
    assert AppConfig(tmp_path, environ={}).refresh_on_start is False
