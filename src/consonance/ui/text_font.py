"""Ordinary interface text only. Musical symbols never enter the font system."""

import os
from pathlib import Path

from PySide6.QtGui import QFontDatabase

_FILES = ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "segoeuii.ttf")


def ensure_text_font() -> None:
    """Load Segoe UI explicitly when Qt starts with an empty font database.

    The Windows offscreen Qt plugin, used for tests and headless renders, knows no fonts
    at all; a normal desktop session already has them and this does nothing.
    """
    if QFontDatabase.families():
        return
    folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in _FILES:
        path = folder / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
