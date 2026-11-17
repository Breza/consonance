import ast
import json
from fractions import Fraction
from pathlib import Path

import pytest

from consonance.core.curriculum import ITEMS, UNITS, StudyConfig
from consonance.core.engine import Action, Command, PracticeEngine
from consonance.core.input_and_grading import NoteOff, NoteOn, PianoStateTracker
from consonance.core.midi_output import MidiOutputLedger, Settings
from consonance.core.notation import Clef, Hand, MidiPitch, natural
from consonance.core.notation_layout import layout_staff, pitch_y
from consonance.core.song import SongNote, SongTimeline
from consonance.core.song_session import SongConfig, SongSession
from consonance.core.transport import TempoMap, TempoPoint


def test_core_has_no_hardware_or_qt_imports() -> None:
    """Verify core has no hardware or qt imports."""
    for path in Path("src/consonance/core").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(n.name.startswith(("PySide6", "rtmidi", "mido")) for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("PySide6", "rtmidi", "mido"))


def test_scene_switch_does_not_count_as_an_attempt() -> None:
    """Verify scene switch does not count as an attempt."""
    engine = PracticeEngine()
    engine.command(Command(Action.SWITCH_SCENE, "ear"), 0)
    assert engine.completed == 0


def test_fast_rhythm_with_positive_judge_offset_finishes_all_windows() -> None:
    """Verify fast rhythm with positive judge offset finishes all windows."""
    engine = PracticeEngine()
    engine.settings = Settings(tempo_bpm=200, midi_judge_offset_ms=150)
    engine.configure_study(StudyConfig((ITEMS["rhythm:4/4:syncopation"],)))
    engine.command(Command(Action.PLAY), 0)
    engine.advance_to(5)
    assert len(engine.results) == 1
    assert not engine.results[0].first_try


def test_sight_items_stay_within_two_ledger_lines() -> None:
    """Verify sight items stay within two ledger lines."""
    for item in ITEMS.values():
        if item.mode != "sight":
            continue
        for variation in range(8):
            for atom in item.atoms(variation):
                for pitch in atom.pitches:
                    y = pitch_y(pitch, item.clef)
                    top = 0 if item.clef == Clef.TREBLE else 10
                    assert top - 2.5 <= y <= top + 6.5, item.item_id


def test_second_intervals_use_displaced_noteheads() -> None:
    """Verify second intervals use displaced noteheads."""
    from consonance.core.notation import NotatedAtom

    layout = layout_staff((NotatedAtom((natural("C4"), natural("D4"))),))
    assert layout.heads[0].x != layout.heads[1].x


def test_technique_iois_are_strikes_even_when_keys_overlap() -> None:
    """Verify technique iois are strikes even when keys overlap."""
    engine = PracticeEngine()
    engine.configure_study(StudyConfig((ITEMS["tech:rh:C_pentascale"],)))
    engine.command(Command(Action.PLAY), 0)
    pitches = (60, 62, 64, 65, 67, 65, 64, 62, 60)
    for i, p in enumerate(pitches):
        timestamp = 1 + i * 0.5
        engine.process_midi(NoteOn(MidiPitch(p), 80, timestamp))
        if i:
            engine.process_midi(NoteOff(MidiPitch(pitches[i - 1]), timestamp + 0.1))
    details = json.loads(engine.results[0].details)
    assert details["ioi_sd_ms"] == pytest.approx(0)
    assert details["velocity_sd"] == 0


def test_mistake_requeues_after_three_intervening_prompts() -> None:
    """Verify mistake requeues after three intervening prompts."""
    items = tuple(i for i in UNITS[0].items if i.mode == "sight")
    engine = PracticeEngine()
    engine.configure_study(StudyConfig(items))
    engine.command(Command(Action.PLAY), 0)
    original = engine.prompt.item_id
    engine.process_midi(NoteOn(MidiPitch(61), 80, 0.1))
    engine.process_midi(NoteOff(MidiPitch(61), 0.2))
    for i in range(4):
        target = engine.prompt.atoms[0].pitches[0].midi
        engine.process_midi(NoteOn(target, 80, i + 1))
        engine.process_midi(NoteOff(target, i + 1.1))
        if i < 3:
            assert engine.prompt.item_id != original
    assert engine.prompt.item_id == original


def test_tempo_run_and_loop_ramp_are_connected() -> None:
    """Verify tempo run and loop ramp are connected."""
    timeline = SongTimeline(
        "t",
        "test",
        (
            SongNote(MidiPitch(60), Fraction(0), Fraction(1), Hand.RIGHT),
            SongNote(MidiPitch(48), Fraction(0), Fraction(4), Hand.LEFT),
        ),
        TempoMap((TempoPoint(0, 60),)),
    )
    piano = PianoStateTracker()
    session = SongSession(
        SongConfig(timeline, mode="Tempo", tempo_scale=0.7, loop=True, auto_ramp=True),
        Settings(),
        piano,
    )
    now = 0.0
    session.restart(now, count_in=False)
    for _ in range(3):
        session.advance_to(now)
        event = NoteOn(MidiPitch(60), 80, now)
        piano.process(event)
        session.process_midi(event)
        now += 4 / session.transport.tempo_scale + 0.001
        session.advance_to(now)
    assert session.transport.tempo_scale == 0.75
    assert "Three clean passes" in session.status
    assert session.release_requested


@pytest.mark.parametrize("action", [Action.PAUSE, Action.REPLAY, Action.SWITCH_SCENE])
def test_worker_transition_protocol_never_sends_user_cleanup(action: Action) -> None:
    """Verify worker transition protocol never sends user cleanup."""
    engine = PracticeEngine()
    engine.command(Command(Action.SWITCH_SCENE, "ear"), 0)
    engine.command(Command(Action.PLAY), 1)
    messages: list[tuple[int, ...]] = []
    ledger = MidiOutputLedger(messages.append)
    for note in engine.output:
        ledger.schedule(note)
    engine.output.clear()
    engine.release_requested = False
    ledger.advance_to(1)
    engine.command(Command(action), 1.1)
    if engine.release_requested:
        ledger.release_computer_notes()
    assert (0x81, 60, 0) in messages
    assert all(m[0] & 15 != 0 and m[0] & 0xF0 != 0xB0 for m in messages)
