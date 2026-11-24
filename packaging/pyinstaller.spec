# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the self-contained Linux directory."""

from pathlib import Path

project = Path(SPECPATH)
repo = project.parent
resources = repo / "src" / "redmine_time_tracker" / "resources"

a = Analysis(
    [str(project / "entrypoint.py")],
    pathex=[str(repo / "src")],
    binaries=[],
    datas=[(str(resources), "redmine_time_tracker/resources")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pytest",
        "mypy",
        "ruff",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="redmine-time-tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="redmine-time-tracker",
)
