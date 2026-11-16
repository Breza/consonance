from consonance.core.engine import Action, Command, PracticeEngine
from consonance.core.input_and_grading import NoteOn
from consonance.core.notation import MidiPitch


def test_ear_replay_preserves_probe_history_and_releases_output() -> None:
    engine = PracticeEngine()
    engine.command(Command(Action.SWITCH_SCENE, "ear"), 0)
    engine.command(Command(Action.PLAY), 1)
    engine.process_midi(NoteOn(MidiPitch(62), 80, 2))
    engine.command(Command(Action.REPLAY), 3)
    assert engine.release_requested
    assert engine.evaluator is not None and len(engine.evaluator.played) == 1
    assert all(note.channel == 1 for note in engine.output)


def test_rhythm_misses_persist_without_input() -> None:
    engine = PracticeEngine()
    engine.command(Command(Action.SWITCH_SCENE, "rhythm"), 0)
    engine.command(Command(Action.PLAY), 1)
    engine.advance_to(30)
    assert len(engine.results) == 1
    assert not engine.results[0].first_try
