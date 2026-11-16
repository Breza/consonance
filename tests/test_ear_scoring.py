from consonance.core.input_and_grading import NoteOff, NoteOn, PianoStateTracker, UntimedEvaluator
from consonance.core.notation import MidiPitch


def test_ear_probes_do_not_earn_first_try_mastery() -> None:
    piano = PianoStateTracker()
    evaluator = UntimedEvaluator(frozenset({MidiPitch(60)}), 0)
    for e in (
        NoteOn(MidiPitch(62), 80, 0.1),
        NoteOff(MidiPitch(62), 0.2),
        NoteOn(MidiPitch(60), 80, 1),
    ):
        piano.process(e)
        evaluator.process(e, piano)
    assert evaluator.completed_at == 1
    assert len(evaluator.played) == 2
    assert not evaluator.is_first_try_correct
