from fractions import Fraction
from pathlib import Path

import pytest

from consonance.core.input_and_grading import NoteOn, PianoStateTracker
from consonance.core.midi_output import MidiOutputLedger, Settings
from consonance.core.notation import Hand, MidiPitch
from consonance.core.song import SongNote, SongTimeline, checkpoints
from consonance.core.song_session import SongConfig, SongSession
from consonance.core.transport import SongTransport, TempoMap, TempoPoint, TransportState
from consonance.io.smf import MidiImport, export_midi


def test_piecewise_tempo_and_freeze() -> None:
    tempo = TempoMap((TempoPoint(0, 60), TempoPoint(4, 120)))
    assert tempo.seconds_at(6) == 5
    assert tempo.beat_at(5) == 6
    transport = SongTransport(tempo)
    transport.play(10)
    assert transport.advance_to(15) == 6
    transport.pause(15, wait=True, checkpoint=5)
    assert transport.beat_at(100) == 5
    transport.play(100)
    transport.set_scale(0.5, 100)
    assert transport.beat_at(101) == 6


def test_wait_halts_future_accompaniment_and_wall_expiry() -> None:
    timeline = SongTimeline(
        "t",
        "test",
        (
            SongNote(MidiPitch(60), Fraction(0), Fraction(1), Hand.RIGHT),
            SongNote(MidiPitch(48), Fraction(0), Fraction(2), Hand.LEFT),
            SongNote(MidiPitch(50), Fraction(1), Fraction(1), Hand.LEFT),
        ),
        TempoMap((TempoPoint(0, 60),)),
    )
    piano = PianoStateTracker()
    session = SongSession(SongConfig(timeline, tempo_scale=1), Settings(), piano)
    session.restart(0, count_in=False)
    session.advance_to(0)
    assert session.transport.state == TransportState.PAUSED_WAIT
    messages: list[tuple[int, ...]] = []
    ledger = MidiOutputLedger(messages.append)
    for note in session.output:
        ledger.schedule(note)
    session.output.clear()
    ledger.advance_to(0)
    session.advance_to(10)
    assert not session.output
    assert (0x91, 48, 80) in messages
    assert not any(m[1] == 50 for m in messages)
    ledger.advance_to(2)
    assert (0x81, 48, 0) in messages


def test_held_lh_whole_note_is_allowed_at_rh_second_beat() -> None:
    notes = (
        SongNote(MidiPitch(48), Fraction(0), Fraction(4), Hand.LEFT),
        SongNote(MidiPitch(60), Fraction(0), Fraction(1), Hand.RIGHT),
        SongNote(MidiPitch(62), Fraction(1), Fraction(1), Hand.RIGHT),
    )
    steps = checkpoints(notes, frozenset(Hand))
    assert steps[1].allowed_held == frozenset({48})
    from consonance.core.input_and_grading import NoteOff, UntimedEvaluator

    piano = PianoStateTracker()
    piano.process(NoteOn(MidiPitch(48), 80, 0))
    piano.process(NoteOff(MidiPitch(60), 0.9))
    evaluator = UntimedEvaluator(steps[1].must_strike, 1, steps[1].allowed_held)
    event = NoteOn(MidiPitch(62), 80, 1.1)
    piano.process(event)
    assert evaluator.process(event, piano)


@pytest.mark.parametrize("ppqn", [96, 960])
def test_beat_clustering_is_resolution_invariant(tmp_path: Path, ppqn: int) -> None:
    notes = tuple(
        SongNote(MidiPitch(p), Fraction(t), Fraction(1), Hand.RIGHT)
        for p, t in ((60, 0), (64, Fraction(1, 8)), (67, Fraction(1, 4)))
    )
    timeline = SongTimeline("t", "test", notes, TempoMap())
    path = tmp_path / f"{ppqn}.mid"
    export_midi(timeline, path, ppqn)
    imported = MidiImport(path)
    loaded = imported.timeline({t.index: Hand.RIGHT for t in imported.tracks})
    groups = checkpoints(loaded.notes, frozenset({Hand.RIGHT}))
    assert groups[0].must_strike == frozenset({60, 64})
    assert len(groups) == 2
