import json
import random

from consonance.core.drills.games import ECHO_LEVELS, RUSH_LEVELS, EchoDrill, RushDrill, rush_pool
from consonance.core.engine import Action, Command, GameConfig, PracticeEngine
from consonance.core.input_and_grading import NoteOff, NoteOn
from consonance.core.notation import MidiPitch


def tap(engine: PracticeEngine, pitch: int, at: float) -> None:
    """Press and release one key."""
    engine.process_midi(NoteOn(MidiPitch(pitch), 80, at))
    engine.process_midi(NoteOff(MidiPitch(pitch), at + 0.1))


def test_rush_levels_draw_from_growing_pools() -> None:
    """Verify rush levels draw from growing pools."""
    sizes = [len(rush_pool(level)) for level in range(len(RUSH_LEVELS))]
    assert sizes == [4, 11, 28]
    assert all(item.kind == "note" and item.mode == "sight" for item in rush_pool(2))
    assert set(rush_pool(0)) < set(rush_pool(1)) < set(rush_pool(2))


def test_note_rush_scores_clean_notes_until_the_clock_runs_out() -> None:
    """Verify note rush scores clean notes until the clock runs out."""
    engine = PracticeEngine(random.Random(5))
    engine.configure_game(GameConfig("rush", 1))
    assert isinstance(engine.drill, RushDrill) and not engine.running
    idle = engine.snapshot()
    assert idle.game is not None and idle.game.time_left == 60 and idle.progress == 1.0
    engine.command(Command(Action.PLAY), 100)
    for i in range(10):
        target = int(engine.prompt.atoms[0].pitches[0].midi)
        if i == 4:
            tap(engine, target + 1, 101 + i)  # one slip
        tap(engine, target, 101.2 + i)
    engine.advance_to(130)
    midway = engine.snapshot()
    assert midway.game is not None and midway.game.score == 9 and midway.game.time_left == 30
    assert midway.progress == 0.5 and "score 9" in midway.chips
    engine.advance_to(160.01)
    assert (
        not engine.running and "9 notes" in engine.status and "new personal best" in engine.status
    )
    notes = [r for r in engine.results if r.item_id.startswith("note:")]
    assert len(notes) == 10 and sum(r.first_try for r in notes) == 9
    assert all(r.mode == "rush" for r in engine.results)
    summary = engine.results[-1]
    assert summary.item_id == "rush:1" and json.loads(summary.details)["score"] == 9
    assert engine.bests["rush:1"] == 9 and engine.new_bests == {"rush:1": 9}
    over = engine.snapshot()
    assert over.game is not None and over.game.over and over.game.best == 9
    engine.command(Command(Action.PLAY), 200)
    engine.advance_to(261)
    assert "your best is 9" in engine.status and engine.bests["rush:1"] == 9


def test_stopping_note_rush_early_keeps_no_score() -> None:
    """Verify stopping note rush early keeps no score."""
    engine = PracticeEngine()
    engine.configure_game(GameConfig("rush", 0))
    engine.command(Command(Action.PLAY), 0)
    tap(engine, int(engine.prompt.atoms[0].pitches[0].midi), 1)
    engine.command(Command(Action.PAUSE), 2)
    assert not engine.running and not engine.bests
    assert [r.item_id.split(":")[0] for r in engine.results] == ["note"]


def test_melody_echo_grows_costs_lives_and_keeps_a_best() -> None:
    """Verify melody echo grows costs lives and keeps a best."""
    engine = PracticeEngine(random.Random(9))
    engine.configure_game(GameConfig("echo", 1))
    drill = engine.drill
    assert isinstance(drill, EchoDrill) and len(drill.pool) == len(ECHO_LEVELS[1][1])
    engine.command(Command(Action.PLAY), 0)
    assert [note.pitch for note in engine.output] == drill.sequence and len(drill.sequence) == 1
    assert all(note.channel == engine.settings.piano_channel for note in engine.output)
    engine.advance_to(0.4)
    calling = engine.snapshot()
    assert calling.prompt_text == "Listen…" and calling.lit == frozenset({drill.sequence[0]})
    assert calling.expected == frozenset()
    tap(engine, drill.sequence[0], 0.45)  # too early: the piano is still playing
    assert drill.position == 0
    now = 1.0
    for length in (1, 2, 3):
        engine.advance_to(now)
        assert engine.snapshot().prompt_text == f"Your turn • 0 of {length}"
        for pitch in list(drill.sequence):
            tap(engine, pitch, now)
            now += 0.2
        assert drill.longest == length and len(drill.sequence) == length + 1
        now += 1.0
        engine.advance_to(now)  # the piano starts the longer melody
        now += 0.6 * (length + 1) + 0.1
    engine.advance_to(now)
    wrong = next(p for p in drill.pool if p != drill.sequence[0])
    for expected_lives in (2, 1):
        tap(engine, wrong, now)
        assert drill.lives == expected_lives and engine.running
        now += 1.0
        engine.advance_to(now)
        now += 0.6 * 4 + 0.1
        engine.advance_to(now)
    tap(engine, wrong, now)
    assert not engine.running and "echoed 3 notes" in engine.status
    result = engine.results[-1]
    assert result.item_id == "echo:1" and json.loads(result.details) == {"game": True, "length": 3}
    assert engine.bests == {"echo:1": 3} and engine.snapshot().game is not None


def test_echo_can_hide_the_call_and_replays_for_free() -> None:
    """Verify echo can hide the call and replays for free."""
    engine = PracticeEngine()
    engine.configure_game(GameConfig("echo", 0, show_call=False))
    engine.command(Command(Action.PLAY), 0)
    engine.advance_to(0.4)
    assert engine.snapshot().lit == frozenset()
    engine.advance_to(2.0)
    engine.output.clear()
    engine.command(Command(Action.REPLAY), 2.0)
    drill = engine.drill
    assert isinstance(drill, EchoDrill)
    assert [note.pitch for note in engine.output] == drill.sequence and drill.lives == 3
    engine.command(Command(Action.PAUSE), 3.0)
    assert not engine.running and not engine.bests and not engine.results
