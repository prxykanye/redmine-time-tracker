"""Small helpers for palette-aware styling.

Qt style sheets do not understand ``palette(mid)``, so colours are resolved from
the widget palette and interpolated as hex values. This keeps the hard-coded
widgets readable in both light and dark themes.
"""

from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget


def muted_color(widget: QWidget) -> str:
    return widget.palette().color(QPalette.ColorRole.PlaceholderText).name()


def panel_style(widget: QWidget, selector: str = "QFrame") -> str:
    palette = widget.palette()
    background = palette.color(QPalette.ColorRole.AlternateBase).name()
    border = palette.color(QPalette.ColorRole.Mid).name()
    return (
        f"{selector} {{ background-color: {background}; border-radius: 6px; "
        f"border: 1px solid {border}; }}"
    )


def muted_style(widget: QWidget) -> str:
    return f"color: {muted_color(widget)};"
