from __future__ import annotations

import tomllib
from pathlib import Path

from redmine_time_tracker import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_version_matches_package() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_pkgbuild_version_matches_package() -> None:
    pkgbuild = (ROOT / "packaging" / "arch" / "PKGBUILD").read_text(encoding="utf-8")
    pkgver = next(
        line.split("=", 1)[1].strip()
        for line in pkgbuild.splitlines()
        if line.startswith("pkgver=")
    )
    assert pkgver == __version__
