import pytest

from consonance.core.input_and_grading import NoteOff, NoteOn, PianoStateTracker, UntimedEvaluator
from consonance.core.notation import MidiPitch


def test_rolled_chord_and_wrong_key() -> None:
    piano = PianoStateTracker()
    evaluator = UntimedEvaluator(frozenset(map(MidiPitch, (60, 64, 67))), 0)
    for p, t in ((60, 0.1), (64, 0.18), (67, 0.26)):
        event = NoteOn(MidiPitch(p), 80, t)
        piano.process(event)
        evaluator.process(event, piano)
    assert evaluator.completed_at == 0.26
    assert evaluator.chord_spread_ms == pytest.approx(160)
    assert evaluator.is_first_try_correct


def test_fresh_strikes_and_allowed_held() -> None:
    piano = PianoStateTracker()
    piano.process(NoteOn(MidiPitch(48), 80, 0))
    evaluator = UntimedEvaluator(frozenset({MidiPitch(60)}), 1, frozenset({MidiPitch(48)}))
    wrong = NoteOn(MidiPitch(61), 80, 1.1)
    piano.process(wrong)
    assert not evaluator.process(wrong, piano)
    right = NoteOn(MidiPitch(60), 80, 1.2)
    piano.process(right)
    assert not evaluator.process(right, piano)
    off = NoteOff(MidiPitch(61), 1.3)
    piano.process(off)
    assert evaluator.process(off, piano)
    assert evaluator.wrong_pitch_count == 1
    assert not evaluator.is_first_try_correct
