import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import SimpleQueue
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from consonance.core.builtin_scores import score_by_id
from consonance.core.curriculum import ITEMS, UNITS, StudyConfig, items_for
from consonance.core.db import Attempt, AttemptLog
from consonance.core.engine import (
    SCENES,
    Action,
    Command,
    GameConfig,
    PracticeEngine,
    RenderSnapshot,
)
from consonance.core.midi_output import Settings
from consonance.core.notation import Hand
from consonance.core.song_session import SongConfig
from consonance.io.session_worker import ConnectPorts
from consonance.io.smf import MidiImport, export_midi
from consonance.ui.app import MainWindow
from consonance.ui.keyboard import KeyboardWidget, KeyGeometry, fit_range, key_fills
from consonance.ui.music_glyphs import GLYPHS
from consonance.ui.song_studio import SongStudioPanel, TrackAssignmentDialog

SYNTH = "Microsoft GS Wavetable Synth 0"


def drain(queue: "SimpleQueue[Any]") -> list[Any]:
    """Empty a worker queue and return what it held."""
    items = []
    while not queue.empty():
        items.append(queue.get())
    return items


@pytest.fixture
def window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MainWindow]:
    """Provide the main window on a private profile, without the realtime worker."""
    monkeypatch.setenv("CONSONANCE_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    main = MainWindow(start_worker=False)
    main.resize(1200, 950)
    main.show()
    app.processEvents()
    drain(main.worker.commands)
    yield main
    main.close()
    app.processEvents()


def key(code: Qt.Key, text: str, *, press: bool = True, repeat: bool = False) -> QKeyEvent:
    """Build a key event."""
    kind = QEvent.Type.KeyPress if press else QEvent.Type.KeyRelease
    return QKeyEvent(kind, code, Qt.KeyboardModifier.NoModifier, text, repeat)


def test_all_screens_render_without_hardware(window: MainWindow) -> None:
    """Verify all screens render without hardware."""
    app = QApplication.instance()
    assert app is not None
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        app.processEvents()
        assert not window.grab().isNull()
    window.tabs.setCurrentWidget(window.practice)
    engine = PracticeEngine()
    for scene in SCENES:
        engine.command(Command(Action.SWITCH_SCENE, scene), 0)
        for moment in (0.0, 1.0, 2.0):
            if moment == 1.0:
                engine.command(Command(Action.PLAY), 1)
            engine.advance_to(moment)
            window.worker.latest = engine.snapshot()
            window.render_snapshot()
            app.processEvents()
            assert not window.grab().isNull()
        assert window.practice.mode_buttons[scene].isChecked()
    for item in ITEMS.values():
        if item.mode != "song":
            engine.configure_study(StudyConfig((item,)))
            engine.command(Command(Action.PLAY), 10)
            window.worker.latest = engine.snapshot()
            window.render_snapshot()
            app.processEvents()
            assert window.practice.title.text() == item.title
    for view in ("Split", "Staff", "Falling notes"):
        window.practice.song_panel.view.setCurrentText(view)
        for score in ("scarborough", "coordination"):
            builtin = score_by_id(score)
            assert builtin is not None
            config = SongConfig(builtin.compile(), mode="Tempo", hands=frozenset(Hand))
            window.practice.open_song(config)
            engine.configure_song(config)
            engine.command(Command(Action.PLAY), 20)
            engine.advance_to(26)
            window.worker.latest = engine.snapshot()
            window.render_snapshot()
            app.processEvents()
            assert not window.grab().isNull()
            assert window.practice.staff.isHidden() == (view == "Falling notes")
            assert window.practice.roll.isHidden() == (view == "Staff")
    assert all(not glyph.isEmpty() for glyph in GLYPHS.values())
    imported = MidiImport(Path("songs/demo/landmark_waltz.mid"))
    dialog = TrackAssignmentDialog(imported)
    assert not dialog.grab().isNull()
    assert [c.currentText() for c in dialog.choices.values()] == ["Right", "Left"]
    assert dialog.assignment() == {1: Hand.RIGHT, 2: Hand.LEFT}
    dialog.close()
    window.keyPressEvent(key(Qt.Key.Key_A, "a", repeat=True))
    assert not window.key_pitches


def test_modes_sets_and_transport_send_the_right_requests(window: MainWindow) -> None:
    """Verify modes sets and transport send the right requests."""
    practice, commands = window.practice, window.worker.commands
    practice.choose_mode("sight")
    (request,) = drain(commands)
    assert isinstance(request, StudyConfig) and {i.mode for i in request.items} == {"sight"}
    assert {i.unit for i in request.items} == {1} and practice.guides.isChecked()
    labels = [practice.sets.itemText(i) for i in range(practice.sets.count())]
    assert labels[0].startswith("Unit 1") and labels[-1].startswith("Everything")
    practice.sets.setCurrentIndex(len(labels) - 1)
    practice.sets.activated.emit(len(labels) - 1)
    (request,) = drain(commands)
    assert isinstance(request, StudyConfig) and len(request.items) == len(items_for("sight"))
    for game, levels in (("rush", 3), ("echo", 3)):
        practice.choose_mode(game)
        (request,) = drain(commands)
        assert request == GameConfig(game, 1, True) and practice.sets.count() == levels
    practice.show_call.setChecked(False)
    assert drain(commands) == [GameConfig("echo", 1, False)]
    practice.choose_mode("song")
    (request,) = drain(commands)
    assert isinstance(request, SongConfig) and request.timeline.song_id == "hot_cross_buns"
    panel = practice.song_panel
    panel.mode.setCurrentText("Tempo")
    panel.hands.setCurrentText("Both")
    panel.scale.setValue(85)
    requests = drain(commands)
    assert len(requests) == 3 and requests[-1].mode == "Tempo"
    assert requests[-1].hands == frozenset(Hand) and requests[-1].tempo_scale == 0.85
    panel.songs.setCurrentIndex(panel.songs.findText("Scarborough Fair"))
    (request,) = drain(commands)
    assert request.timeline.song_id == "scarborough" and (panel.a.value(), panel.b.value()) == (
        1,
        16,
    )
    panel.a.setValue(9)
    panel.b.setValue(12)
    assert drain(commands)[-1].section == "9-12"
    practice.toggle_play()
    window.worker.latest = RenderSnapshot(scene="song", running=True)
    window.render_snapshot()
    assert practice.play_button.text() == "Pause"
    practice.toggle_play()
    assert drain(commands) == [Command(Action.PLAY), Command(Action.PAUSE)]


def test_typing_plays_silent_notes_and_drives_the_transport(window: MainWindow) -> None:
    """Verify typing plays silent notes and drives the transport."""
    notes, commands = window.worker.input, window.worker.commands
    window.keyPressEvent(key(Qt.Key.Key_A, "a"))
    window.keyPressEvent(key(Qt.Key.Key_Space, " "))
    assert notes.empty() and commands.empty()  # typing on the Home screen plays nothing
    window.tabs.setCurrentWidget(window.practice)
    window.keyPressEvent(key(Qt.Key.Key_A, "a"))
    window.keyPressEvent(key(Qt.Key.Key_A, "a", repeat=True))
    window.keyPressEvent(key(Qt.Key.Key_W, "w"))
    assert window.key_pitches == {"A": 60, "W": 61}
    window.keyReleaseEvent(key(Qt.Key.Key_A, "a", press=False))
    assert [raw for _, raw in drain(notes)] == [(0x90, 60, 80), (0x90, 61, 80), (0x80, 60, 0)]
    window.keyPressEvent(key(Qt.Key.Key_X, "x"))  # up an octave; held keys are let go first
    assert window.octave == 5 and not window.key_pitches
    assert [raw for _, raw in drain(notes)] == [(0x80, 61, 0)]
    window.keyPressEvent(key(Qt.Key.Key_L, "l"))
    assert [raw for _, raw in drain(notes)] == [(0x90, 86, 80)]
    window.tabs.setCurrentWidget(window.settings_panel)  # leaving releases whatever is held
    assert [raw for _, raw in drain(notes)] == [(0x80, 86, 0)]
    window.tabs.setCurrentWidget(window.practice)
    for code, text in (
        (Qt.Key.Key_Space, " "),
        (Qt.Key.Key_R, "r"),
        (Qt.Key.Key_N, "n"),
        (Qt.Key.Key_H, "h"),
    ):
        window.keyPressEvent(key(code, text))
    assert [c.action for c in drain(commands)] == [
        Action.PLAY,
        Action.REPLAY,
        Action.NEXT,
        Action.HINT,
    ]
    control = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "a"
    )
    window.keyPressEvent(control)
    window.keyPressEvent(key(Qt.Key.Key_1, "1"))
    assert notes.empty() and commands.empty()
    keyboard = window.practice.keyboard
    left, width = keyboard.geometry_now().span(60)
    spot = QPoint(round(left + width / 2), keyboard.height() - 8)
    QTest.mousePress(keyboard, Qt.MouseButton.LeftButton, pos=spot)
    QTest.mouseRelease(keyboard, Qt.MouseButton.LeftButton, pos=spot)
    assert [raw for _, raw in drain(notes)] == [(0x90, 60, 80), (0x80, 60, 0)]
    window._panic()
    assert drain(commands) == [Command(Action.PANIC)]


def test_home_offers_a_plan_and_opens_what_is_chosen(window: MainWindow) -> None:
    """Verify home offers a plan and opens what is chosen."""
    commands = window.worker.commands
    dashboard = window.dashboard
    assert not dashboard.welcome.isHidden() and "nothing due" in dashboard.plan_summary.text()
    step = dashboard.first_step()
    assert step is not None and step.mode == "keys"
    dashboard.open_step.emit(step)
    (request,) = drain(commands)
    assert isinstance(request, StudyConfig) and request.title.startswith("Today's plan")
    assert tuple(i.item_id for i in request.items) == step.item_ids
    assert window.tabs.currentWidget() is window.practice
    assert window.practice.sets.itemText(0) == request.title
    dashboard.open_item.emit("triad:treble:C_maj")
    (request,) = drain(commands)
    assert request.items[0].item_id == "triad:treble:C_maj" and len(request.items) == 6
    dashboard.open_item.emit("song:ode_to_joy:all:both")
    (request,) = drain(commands)
    assert isinstance(request, SongConfig) and request.hands == frozenset(Hand)
    assert window.practice.song_panel.songs.currentText() == "Ode to Joy"
    assert window.practice.song_panel.hands.currentText() == "Both"
    dashboard.open_item.emit("coord:ostinato:C")
    assert drain(commands)[0].timeline.song_id == "coordination"
    dashboard.open_game.emit("rush", -1)
    assert isinstance(drain(commands)[0], GameConfig)
    dashboard.units.setCurrentIndex(4)
    assert dashboard.free.count() == len(UNITS[4].items) and "new" in dashboard.free.item(0).text()


def test_home_reflects_practice_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify home reflects practice history."""
    monkeypatch.setenv("CONSONANCE_DATA_DIR", str(tmp_path))
    log = AttemptLog(tmp_path / "practice.sqlite3")
    session = log.start_session("sight", (datetime.now(UTC) - timedelta(days=2)).isoformat())
    log.end_session(session, 600)
    for i in range(10):
        when = (datetime.now(UTC) - timedelta(days=2, seconds=-i)).isoformat()
        log.append(
            Attempt(
                session, "sight", "note:treble:G4", (67,), (67,), True, 1, 800, timestamp_utc=when
            )
        )
    log.set_preference("best:rush:1", json.dumps(17))
    log.close()
    app = QApplication.instance() or QApplication([])
    main = MainWindow(start_worker=False)
    try:
        dashboard = main.dashboard
        assert dashboard.welcome.isHidden() and "1 due" in dashboard.plan_summary.text()
        assert dashboard.plan is not None and dashboard.plan.steps[0].kind == "review"
        assert "1 of 152 items mastered" in dashboard.mastered.text()
        assert "17" in dashboard.rush_best.text() and dashboard.echo_best.text() == "No score yet"
        assert "due now" in dashboard.free.item(10).text()
        assert dict(dashboard.week.days)  # the chart has its seven days
        main.practice.set_progress(dashboard.states)
        main.practice.choose_mode("sight")
        assert main.practice.sets.itemText(0) == "Due now • 1 to review"
    finally:
        main.close()
        app.processEvents()


def test_settings_apply_at_once_and_refuse_channel_clashes(window: MainWindow) -> None:
    """Verify settings apply at once and refuse channel clashes."""
    panel, commands = window.settings_panel, window.worker.commands
    panel.spins["tempo_bpm"].setValue(96)
    assert window.settings.tempo_bpm == 96 and drain(commands) == [window.settings]
    assert window.practice.tempo.value() == 96
    assert Settings.from_json(window.log.preference("settings")).tempo_bpm == 96
    panel.spins["user_channel"].setValue(2)  # the computer piano already plays on 2
    assert "distinct" in panel.error.text() and window.settings.user_channel == 0
    assert drain(commands) == []
    panel.spins["piano_channel"].setValue(3)
    assert panel.error.text() == "" and window.settings.user_channel == 1
    window.practice.names.setChecked(True)
    window.practice.tempo.setValue(60)
    assert window.settings.show_names and window.settings.tempo_bpm == 60
    assert panel.spins["tempo_bpm"].value() == 60 and window.settings.piano_channel == 2
    window.worker.latest = replace(RenderSnapshot(), channel_hint=5)
    window.render_snapshot()
    assert not window.banner.isHidden() and "channel 6" in window.banner_text.text()
    window.banner_button.click()
    assert window.settings.user_channel == 5 and len({*drain(commands)}) >= 1


class Names:
    """A stand-in for the port prober whose answer the test controls."""

    def __init__(self) -> None:
        """Start with no ports present."""
        self.inputs: list[str] = []
        self.outputs: list[str] = [SYNTH]

    def names(self) -> tuple[list[str], list[str]]:
        """Return the ports that are currently 'present'."""
        return list(self.inputs), list(self.outputs)

    def close(self) -> None:
        """Nothing to close."""


def test_the_piano_connects_on_sight_and_its_loss_is_noticed(window: MainWindow) -> None:
    """Verify the piano connects on sight and its loss is noticed."""
    commands = window.worker.commands
    prober = Names()
    window.ports = prober  # type: ignore[assignment]
    window.poll_ports()
    assert drain(commands) == [] and "No piano connected" in window.link_button.text()
    prober.inputs, prober.outputs = ["Roland Digital Piano 0"], [SYNTH, "Roland Digital Piano 1"]
    window.poll_ports()
    wanted = ConnectPorts("Roland Digital Piano 0", "Roland Digital Piano 1")
    assert drain(commands) == [wanted]
    assert window.settings_panel.inputs.currentText() == "Roland Digital Piano 0"
    window.poll_ports()
    assert drain(commands) == []  # one attempt per appearance, not one every two seconds
    window.worker.latest = replace(
        RenderSnapshot(), midi_in=wanted.input_name, midi_out=wanted.output_name
    )
    window.render_snapshot()
    assert window.link_button.text() == "Piano connected • Roland Digital Piano"
    assert window.log.preference_value("midi")["input"] == "Roland Digital Piano 0"
    prober.inputs, prober.outputs = [], [SYNTH]
    window.poll_ports()
    assert drain(commands) == [ConnectPorts("", "")]
    window.worker.latest = RenderSnapshot()
    window.render_snapshot()
    # Windows renumbers ports; the remembered piano is still recognised.
    prober.inputs, prober.outputs = ["Roland Digital Piano 3"], [SYNTH, "Roland Digital Piano 4"]
    window.poll_ports()
    assert drain(commands) == [ConnectPorts("Roland Digital Piano 3", "Roland Digital Piano 4")]
    window.settings_panel.connect_requested.emit("", "")
    drain(commands)
    window.poll_ports()
    assert drain(commands) == []  # an explicit disconnect is respected
    window.settings_panel.auto.setChecked(False)
    window.settings_panel.auto.setChecked(True)
    assert not window._user_disconnected


def test_imported_songs_are_restored_as_falling_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify imported songs are restored as falling notes."""
    monkeypatch.setenv("CONSONANCE_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    waltz = score_by_id("landmark_waltz")
    assert waltz is not None
    source = replace(waltz.compile(), song_id="x", title="x")
    stored = tmp_path / "songs" / "custom" / "0123456789ab_my_tune.mid"
    export_midi(source, stored)
    log = AttemptLog(tmp_path / "practice.sqlite3")
    digest = MidiImport(stored).digest
    log.set_preference(f"track_assignment:{digest}", json.dumps({"1": "Right", "2": "Left"}))
    panel = SongStudioPanel(log)
    assert panel.songs.itemText(panel.songs.count() - 1) == "my tune (imported)"
    sent: list[SongConfig] = []
    panel.configured.connect(sent.append)
    panel.songs.setCurrentIndex(panel.songs.count() - 1)
    assert sent[-1].timeline.song_id == digest and sent[-1].timeline.title == "my tune"
    assert not panel.has_staff() and panel.current_view() == "Falling notes"
    assert "falling notes" in panel.message.text()
    panel.a.setValue(5)
    panel.b.setValue(2)
    assert "A <= B" in panel.message.text()
    log.close()


def test_keyboard_geometry_and_key_colours() -> None:
    """Verify keyboard geometry and key colours."""
    keys = KeyGeometry(61, 70, 0.0, 700.0)
    assert (keys.low, keys.high) == (60, 71) and len(keys.whites) == 7
    assert keys.span(60) == (0.0, 100.0) and keys.span(71)[0] == 600.0
    left, width = keys.span(61)
    assert left + width / 2 == 100.0 and width < 100
    assert keys.lane(62)[0] > keys.span(62)[0] and keys.lane(61) == keys.span(61)
    assert keys.pitch_at(100.0, 10.0, 100.0) == 61 and keys.pitch_at(100.0, 90.0, 100.0) == 62
    assert keys.pitch_at(-5.0, 90.0, 100.0) is None and not keys.contains(72)
    assert fit_range([60, 64]) == (36, 84) and fit_range([22, 100]) == (21, 108)
    assert fit_range([58, 69], (55, 65)) == (48, 72)
    idle = key_fills(frozenset({60}), frozenset(), frozenset(), frozenset(), False)
    asked = key_fills(
        frozenset({60, 61, 48}), frozenset({60}), frozenset({48}), frozenset({72}), True
    )
    assert (
        idle[60] != asked[60] and len({asked[60].name(), asked[61].name(), asked[48].name()}) == 3
    )
    assert 72 in asked and 62 not in asked
    QApplication.instance() or QApplication([])
    widget = KeyboardWidget()
    widget.show_state(frozenset({100}), frozenset(), frozenset(), frozenset(), False, False)
    assert (widget.low, widget.high) == (36, 108)
    widget.reset_range()
    assert (widget.low, widget.high) == (36, 84)
