"""Application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__, paths
from .config import AppConfig
from .database import Database
from .gui.main_window import MainWindow
from .logging_setup import configure_logging, install_excepthook

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    log_file = configure_logging()
    install_excepthook()

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Redmine Time Tracker")
    app.setApplicationDisplayName("Redmine Time Tracker")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("redmine-time-tracker")
    app.setDesktopFileName("redmine-time-tracker")
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

    logger.info("Started version %s, log file: %s", __version__, log_file)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
