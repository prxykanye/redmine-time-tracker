"""Run blocking calls outside the GUI thread."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


class Worker(QRunnable):
    """Execute a callable in a thread pool and report the outcome by signal."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:
            self.signals.failed.emit(exc)
        else:
            self.signals.succeeded.emit(result)
