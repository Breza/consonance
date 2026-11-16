from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from consonance.core.curriculum import ITEMS, StudyConfig
from consonance.core.engine import Action, Command, PracticeEngine
from consonance.io.smf import MidiImport
from consonance.ui.app import MainWindow
from consonance.ui.music_glyphs import GLYPHS
from consonance.ui.song_studio import TrackAssignmentDialog


def test_all_screens_render_without_hardware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONSONANCE_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(start_worker=False)
    window.resize(1200, 950)
    window.show()
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        app.processEvents()
        assert not window.grab().isNull()
    engine = PracticeEngine()
    for scene in ("sight", "rhythm", "technique", "ear", "song"):
        engine.command(Command(Action.SWITCH_SCENE, scene), 0)
        engine.command(Command(Action.PLAY), 1)
        engine.advance_to(2)
        window.worker.latest = engine.snapshot()
        window.tabs.setCurrentWidget(window.practice)
        window.render_snapshot()
        app.processEvents()
        assert not window.grab().isNull()
    for item in ITEMS.values():
        if item.mode != "song":
            engine.configure_study(StudyConfig((item,)))
            engine.command(Command(Action.PLAY), 10)
            window.worker.latest = engine.snapshot()
            window.render_snapshot()
            app.processEvents()
    assert all(not glyph.isEmpty() for glyph in GLYPHS.values())
    imported = MidiImport(Path("songs/demo/landmark_waltz.mid"))
    dialog = TrackAssignmentDialog(imported)
    assert not dialog.grab().isNull()
    dialog.close()
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a", True)
    window.keyPressEvent(event)
    assert not window.key_pitches
    window.close()
    app.processEvents()
