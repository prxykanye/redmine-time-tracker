"""Render PNG icon sizes from the SVG source.

Run from the repository root:

    uv run python packaging/render_icons.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    source = root / "src" / "redmine_time_tracker" / "resources" / "appicon.svg"
    target_dir = source.parent / "icons"
    target_dir.mkdir(parents=True, exist_ok=True)

    app = QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        print(f"invalid SVG: {source}", file=sys.stderr)
        return 1

    for size in SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        output = target_dir / f"appicon-{size}.png"
        if not image.save(str(output)):
            print(f"failed to write {output}", file=sys.stderr)
            return 1
        print(output.relative_to(root))

    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
