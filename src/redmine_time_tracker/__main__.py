"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from importlib.resources import files

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__, paths
from .config import AppConfig
from .database import Database
from .gui.main_window import MainWindow
from .logging_setup import configure_logging, install_excepthook

logger = logging.getLogger(__name__)


def app_icon() -> QIcon:
    path = files("redmine_time_tracker").joinpath("resources", "icons", "appicon-256.png")
    return QIcon(str(path))


def parse_arguments(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="redmine-time-tracker",
        description="Desktop time tracker for Redmine.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="start hidden in the system tray",
    )
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args, qt_args = parse_arguments(raw_args)

    log_file = configure_logging()
    install_excepthook()

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("Redmine Time Tracker")
    app.setApplicationDisplayName("Redmine Time Tracker")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("redmine-time-tracker")
    app.setDesktopFileName("redmine-time-tracker")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(str(paths.lock_path()))
    if not lock.tryLock(100):
        QMessageBox.warning(
            None,
            "Redmine Time Tracker",
            "Приложение уже запущено. Закройте второй экземпляр и попробуйте снова.",
        )
        return 1
    # Keep the lock alive for the whole process lifetime.
    app.instance_lock = lock  # type: ignore[attr-defined]

    database = Database(paths.database_path())
    database.init()

    config = AppConfig()
    window = MainWindow(config, database)
    window.show()
    if args.minimized and window.tray_available:
        window.hide()

    logger.info("Started version %s, log file: %s", __version__, log_file)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
