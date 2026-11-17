import json
import random

import pytest

from consonance.core.builtin_scores import ALL_SCORES
from consonance.core.curriculum import ITEMS, StudyConfig
from consonance.core.engine import SCENES, Action, Command, GameConfig, PracticeEngine
from consonance.core.input_and_grading import ControlChange, NoteOff, NoteOn
from consonance.core.midi_output import MidiOutputLedger, Settings
from consonance.core.notation import Hand, MidiPitch
from consonance.core.song_session import SongConfig

TIMELINES = [score.compile() for score in ALL_SCORES]
STUDY = [item for item in ITEMS.values() if item.mode != "song"]
ACTIONS = [a for a in Action if a != Action.SWITCH_SCENE]
HANDS = (frozenset({Hand.RIGHT}), frozenset({Hand.LEFT}), frozenset(Hand))


def reconfigure(engine: PracticeEngine, rng: random.Random, now: float) -> None:
    """Switch the engine to a random mode, set, song, game, or settings."""
    choice = rng.randrange(5)
    if choice == 0:
        engine.command(Command(Action.SWITCH_SCENE, rng.choice(SCENES)), now)
    elif choice == 1:
        mode = rng.choice(("keys", "sight", "rhythm", "technique", "ear"))
        pool = [item for item in STUDY if item.mode == mode]
        engine.configure_study(StudyConfig(tuple(rng.sample(pool, k=rng.randint(1, 4)))))
    elif choice == 2:
        timeline = rng.choice(TIMELINES)
        first = rng.randint(1, timeline.measure_count)
        last = rng.randint(first, timeline.measure_count)
        engine.configure_song(
            SongConfig(
                timeline,
                rng.choice(("Wait", "Tempo")),
                rng.choice(HANDS),
                rng.choice((0.25, 0.7, 1.25)),
                first,
                last,
                rng.random() < 0.4,
                rng.random() < 0.4,
            )
        )
    elif choice == 3:
        engine.configure_game(
            GameConfig(rng.choice(("rush", "echo")), rng.randint(0, 2), rng.random() < 0.5)
        )
    else:
        engine.settings = Settings(
            tempo_bpm=rng.choice((30, 72, 200)),
            technique_self_paced=rng.random() < 0.5,
            midi_judge_offset_ms=rng.choice((-150, 0, 150)),
            auto_hint_misses=rng.choice((0, 1, 2)),
            show_names=rng.random() < 0.3,
            metronome=rng.choice(("Woodblock", "Piano", "Off")),
        )


def answer(engine: PracticeEngine, held: set[int], now: float) -> None:
    """Let go of everything, then play exactly what is being asked for."""
    for pitch in sorted(held):
        engine.process_midi(NoteOff(MidiPitch(pitch), now))
    held.clear()
    snapshot = engine.snapshot()
    wanted = sorted(snapshot.expected)
    if len(wanted) > 12:  # an any-octave prompt: one key per wanted note name
        wanted = sorted({p % 12: p for p in wanted if 55 <= p <= 78}.values())
    if not wanted and snapshot.scene == "rhythm":
        wanted = [60]
    for pitch in wanted:
        engine.process_midi(NoteOn(MidiPitch(pitch), 80, now))
    for pitch in wanted:
        engine.process_midi(NoteOff(MidiPitch(pitch), now + 0.05))


@pytest.mark.parametrize("seed", range(9))
def test_no_sequence_of_inputs_breaks_the_engine(seed: int) -> None:
    """Verify no sequence of inputs breaks the engine."""
    rng = random.Random(seed)
    engine = PracticeEngine(random.Random(seed) if seed % 2 else None)
    skill = (0.0, 0.6, 1.0)[seed % 3]
    ledger = MidiOutputLedger(lambda message: None)
    held: set[int] = set()
    outcomes: set[tuple[str, bool]] = set()
    now = 0.0
    for _ in range(900):
        now += rng.choice((0.0, 0.002, 0.02, 0.2, 0.7, 3.0))
        roll = rng.random()
        if roll < 0.10 - 0.06 * skill:
            reconfigure(engine, rng, now)
        elif roll < 0.25:
            value = rng.choice((0.0, 2.0, 7.5, 400.0))
            engine.command(Command(rng.choice(ACTIONS), value=value), now)
        elif roll < 0.25 + 0.5 * skill:
            answer(engine, held, now)
            now += 0.05
        elif roll < 0.75:
            pitch = rng.randint(21, 108)
            if pitch in held:
                held.discard(pitch)
                engine.process_midi(NoteOff(MidiPitch(pitch), now))
            else:
                held.add(pitch)
                engine.process_midi(NoteOn(MidiPitch(pitch), rng.randint(1, 127), now))
        elif roll < 0.80:
            pedal = rng.choice((64, 66, 67))
            engine.process_midi(ControlChange(pedal, rng.choice((0, 127)), now))
        else:
            engine.advance_to(now)
        snapshot = engine.snapshot()
        assert snapshot.scene in SCENES and snapshot.scene == engine.scene
        if snapshot.layout is not None and snapshot.playhead is not None:
            snapshot.layout.x_at(snapshot.playhead)
        if engine.release_requested:
            ledger.release_computer_notes()
            engine.release_requested = False
        for note in engine.output:
            ledger.schedule(note)  # raises for an invalid note or one on the player's channel
        engine.output.clear()
        ledger.advance_to(now)
        for result in engine.results:
            details = json.loads(result.details)
            assert result.mode in SCENES
            assert not (result.first_try and details.get("incomplete"))
            if details.get("incomplete") and result.mode in ("rhythm", "song"):
                assert details.get("blameless")  # an unfinished timed pass is never a miss
            if details.get("game"):
                assert result.item_id.split(":")[0] in ("rush", "echo")
            outcomes.add((result.mode, result.first_try))
        engine.results.clear()
    engine.abandon()
    assert outcomes  # the run really did produce attempts
