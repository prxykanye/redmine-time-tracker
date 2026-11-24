from __future__ import annotations

import os
import stat

import pytest

from redmine_time_tracker.config import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    AppConfig,
    ConfigError,
    normalize_url,
)


class FailingKeyring:
    """Simulates a system without a usable secret service."""

    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("no keyring backend")

    def set_password(self, service: str, username: str, value: str) -> None:
        raise RuntimeError("no keyring backend")


class FakeKeyring:
    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, value: str) -> None:
        self.passwords[(service, username)] = value


def make_config(tmp_path, **kwargs) -> AppConfig:
    return AppConfig(tmp_path, environ={}, keyring_module=FailingKeyring(), **kwargs)


def test_defaults_are_empty(tmp_path) -> None:
    config = make_config(tmp_path)
    assert config.redmine_url == ""
    assert config.redmine_api_key == ""
    assert config.is_configured is False


def test_url_is_persisted_and_normalized(tmp_path) -> None:
    config = make_config(tmp_path)
    config.redmine_url = "https://redmine.example.com/"

    reloaded = make_config(tmp_path)
    assert reloaded.redmine_url == "https://redmine.example.com"


def test_invalid_url_is_rejected(tmp_path) -> None:
    config = make_config(tmp_path)
    with pytest.raises(ConfigError):
        config.redmine_url = "redmine.example.com"


def test_normalize_url_keeps_trailing_slash_off() -> None:
    assert normalize_url("  https://example.com/  ") == "https://example.com"
    assert normalize_url("") == ""


def test_api_key_is_stored_in_env_file(tmp_path) -> None:
    config = make_config(tmp_path)
    config.set_redmine_api_key("secret-key")

    env_file = tmp_path / ".env"
    assert env_file.read_text(encoding="utf-8").strip() == "REDMINE_API_KEY=secret-key"
    assert make_config(tmp_path).redmine_api_key == "secret-key"

    if os.name == "posix":
        mode = stat.S_IMODE(env_file.stat().st_mode)
        assert mode == 0o600


def test_environment_variable_wins_over_env_file(tmp_path) -> None:
    config = make_config(tmp_path)
    config.set_redmine_api_key("from-file")
    config = AppConfig(
        tmp_path,
        environ={"REDMINE_API_KEY": "from-environ"},
        keyring_module=FailingKeyring(),
    )
    assert config.redmine_api_key == "from-environ"


def test_refresh_on_start_is_persisted(tmp_path) -> None:
    config = make_config(tmp_path)
    config.refresh_on_start = False
    assert make_config(tmp_path).refresh_on_start is False


def test_keyring_stores_the_key_without_a_plaintext_file(tmp_path) -> None:
    keyring = FakeKeyring()
    config = AppConfig(tmp_path, environ={}, keyring_module=keyring)
    config.set_redmine_api_key("from-keyring")

    assert keyring.passwords[(KEYRING_SERVICE, KEYRING_USERNAME)] == "from-keyring"
    assert not (tmp_path / ".env").exists()

    reloaded = AppConfig(tmp_path, environ={}, keyring_module=keyring)
    assert reloaded.redmine_api_key == "from-keyring"


def test_keyring_is_preferred_over_the_env_file(tmp_path) -> None:
    make_config(tmp_path).set_redmine_api_key("from-file")

    keyring = FakeKeyring()
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, "from-keyring")
    config = AppConfig(tmp_path, environ={}, keyring_module=keyring)

    assert config.redmine_api_key == "from-keyring"


def test_moving_a_key_to_the_keyring_removes_the_plaintext_copy(tmp_path) -> None:
    make_config(tmp_path).set_redmine_api_key("from-file")
    assert "REDMINE_API_KEY=from-file" in (tmp_path / ".env").read_text(encoding="utf-8")

    keyring = FakeKeyring()
    config = AppConfig(tmp_path, environ={}, keyring_module=keyring)
    config.set_redmine_api_key("from-keyring")

    env_content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "REDMINE_API_KEY" not in env_content
    assert config.redmine_api_key == "from-keyring"
