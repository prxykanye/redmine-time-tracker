"""Application configuration stored in the user config directory.

The Redmine URL is persisted in ``config.ini``. The API key is read from the
``REDMINE_API_KEY`` environment variable first and from ``.env`` next to the
configuration file second. There is no built-in default URL: a fresh install
asks the user for it.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from configparser import ConfigParser
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from . import paths

CONFIG_FILENAME = "config.ini"
ENV_FILENAME = ".env"
API_KEY_VAR = "REDMINE_API_KEY"
KEYRING_SERVICE = "redmine-time-tracker"
KEYRING_USERNAME = "api-key"


def _import_keyring() -> Any | None:
    try:
        import keyring
    except Exception:
        return None
    return keyring


class ConfigError(ValueError):
    """Raised when a configuration value cannot be used."""


def normalize_url(value: str) -> str:
    """Validate and normalize a Redmine base URL."""
    url = value.strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        raise ConfigError("URL must start with http:// or https://")
    return url


class AppConfig:
    """Read and write the application configuration."""

    def __init__(
        self,
        config_dir: Path | None = None,
        environ: Mapping[str, str] | None = None,
        keyring_module: Any | None = None,
    ) -> None:
        self.dir = Path(config_dir) if config_dir else paths.config_dir()
        self.path = self.dir / CONFIG_FILENAME
        self.env_path = self.dir / ENV_FILENAME
        self._environ = environ if environ is not None else os.environ
        self._keyring = keyring_module if keyring_module is not None else _import_keyring()
        self._parser = ConfigParser()
        if self.path.exists():
            self._parser.read(self.path, encoding="utf-8")
        self._ensure_sections()
        self._file_env = self._read_env_file()

    # ------------------------------------------------------------------
    # Redmine connection
    # ------------------------------------------------------------------
    @property
    def redmine_url(self) -> str:
        return self._parser.get("redmine", "url", fallback="").rstrip("/")

    @redmine_url.setter
    def redmine_url(self, value: str) -> None:
        self._parser.set("redmine", "url", normalize_url(value))
        self.save()

    @property
    def redmine_api_key(self) -> str:
        from_environ = (self._environ.get(API_KEY_VAR) or "").strip()
        if from_environ:
            return from_environ
        from_keyring = self._read_keyring()
        if from_keyring:
            return from_keyring
        return (self._file_env.get(API_KEY_VAR) or "").strip()

    def set_redmine_api_key(self, value: str) -> None:
        """Store the key in the OS keyring when available, otherwise in ``.env``."""
        key = value.strip()
        if key and self._write_keyring(key):
            self._remove_env_key()
            self._file_env.pop(API_KEY_VAR, None)
            return
        self._write_env_key(key)

    def _read_keyring(self) -> str:
        if self._keyring is None:
            return ""
        try:
            value = self._keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception:
            return ""
        return (value or "").strip()

    def _write_keyring(self, key: str) -> bool:
        if self._keyring is None:
            return False
        try:
            self._keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key)
        except Exception:
            return False
        return True

    def _write_env_key(self, key: str) -> None:
        lines: list[str] = []
        if self.env_path.exists():
            lines = self.env_path.read_text(encoding="utf-8").splitlines()

        replaced = False
        for index, line in enumerate(lines):
            if line.strip().startswith(f"{API_KEY_VAR}="):
                lines[index] = f"{API_KEY_VAR}={key}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{API_KEY_VAR}={key}")

        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if os.name == "posix":
            self.env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        self._file_env[API_KEY_VAR] = key

    def _remove_env_key(self) -> None:
        if not self.env_path.exists():
            return
        lines = [
            line
            for line in self.env_path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith(f"{API_KEY_VAR}=")
        ]
        content = "\n".join(lines) + ("\n" if lines else "")
        self.env_path.write_text(content, encoding="utf-8")
        if os.name == "posix":
            self.env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    @property
    def is_configured(self) -> bool:
        return bool(self.redmine_url and self.redmine_api_key)

    # ------------------------------------------------------------------
    # Application behaviour
    # ------------------------------------------------------------------
    @property
    def refresh_on_start(self) -> bool:
        return self._parser.getboolean("app", "refresh_on_start", fallback=True)

    @refresh_on_start.setter
    def refresh_on_start(self, value: bool) -> None:
        self._parser.set("app", "refresh_on_start", "true" if value else "false")
        self.save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _ensure_sections(self) -> None:
        for section in ("redmine", "app"):
            if section not in self._parser:
                self._parser[section] = {}
        if "url" not in self._parser["redmine"]:
            self._parser["redmine"]["url"] = ""

    def _read_env_file(self) -> dict[str, str]:
        if not self.env_path.exists():
            return {}
        values = dotenv_values(self.env_path)
        return {key: value for key, value in values.items() if value is not None}

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            self._parser.write(handle)
