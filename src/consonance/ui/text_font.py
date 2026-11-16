"""Ordinary interface text only. Musical symbols never enter the font system."""

import os
from pathlib import Path

from PySide6.QtGui import QFontDatabase


def ensure_text_font() -> None:
    # The Windows offscreen Qt plugin starts with an empty font database.
    # Load the installed Windows UI typeface explicitly for readable QA renders.
    if not QFontDatabase.families():
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        QFontDatabase.addApplicationFont(str(path))
