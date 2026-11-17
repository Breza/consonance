import json
import random

from consonance.core.curriculum import ITEMS, StudyConfig, items_for
from consonance.core.engine import Action, Command, PracticeEngine
from consonance.core.input_and_grading import ControlChange, NoteOff, NoteOn
from consonance.core.midi_output import Settings
from consonance.core.notation import MidiPitch


def study(*item_ids: str, rng: random.Random | None = None) -> PracticeEngine:
    """Create an engine practising the given curriculum items."""
    engine = PracticeEngine(rng)
    engine.configure_study(StudyConfig(tuple(ITEMS[i] for i in item_ids)))
    return engine


def tap(engine: PracticeEngine, pitch: int, at: float, hold: float = 0.1) -> None:
    """Press and release one key."""
    engine.process_midi(NoteOn(MidiPitch(pitch), 80, at))
    engine.process_midi(NoteOff(MidiPitch(pitch), at + hold))


def test_ear_replay_preserves_probe_history_and_releases_output() -> None:
    """Verify ear replay preserves probe history and releases output."""
    engine = PracticeEngine()
    engine.command(Command(Action.SWITCH_SCENE, "ear"), 0)
    engine.command(Command(Action.PLAY), 1)
    engine.process_midi(NoteOn(MidiPitch(62), 80, 2))
    engine.command(Command(Action.REPLAY), 3)
    assert engine.release_requested
    assert engine.evaluator is not None and len(engine.evaluator.played) == 1
    assert all(note.channel == 1 for note in engine.output)


def test_rhythm_misses_persist_without_input() -> None:
    """Verify rhythm misses persist without input."""
    engine = PracticeEngine()
    engine.command(Command(Action.SWITCH_SCENE, "rhythm"), 0)
    engine.command(Command(Action.PLAY), 1)
    engine.advance_to(30)
    assert len(engine.results) == 1
    assert not engine.results[0].first_try


def test_keys_by_name_accept_any_octave_but_landmarks_do_not() -> None:
    """Verify keys by name accept any octave but landmarks do not."""
    engine = study("key:C")
    engine.command(Command(Action.PLAY), 0)
    assert engine.snapshot().prompt_text == "Play any C" and engine.snapshot().layout is None
    assert {24, 60, 108} <= engine.snapshot().expected and 62 not in engine.snapshot().expected
    tap(engine, 36, 1)
    assert engine.results[0].first_try and engine.results[0].mode == "keys"
    engine = study("key:middle_C")
    engine.command(Command(Action.PLAY), 0)
    tap(engine, 72, 1)
    assert not engine.results
    tap(engine, 60, 2)
    assert len(engine.results) == 1 and not engine.results[0].first_try
    engine = study("chord:C_major")
    engine.command(Command(Action.PLAY), 0)
    for pitch in (52, 67, 72):  # E3, G4, C5: an open-position C major
        engine.process_midi(NoteOn(MidiPitch(pitch), 80, 1))
    assert engine.results[0].first_try and "C - E - G" in engine.status


def test_the_answer_lights_up_after_repeated_misses_or_on_request() -> None:
    """Verify the answer lights up after repeated misses or on request."""
    engine = study("note:treble:G4")
    engine.command(Command(Action.PLAY), 0)
    tap(engine, 60, 1)
    assert not engine.snapshot().reveal
    tap(engine, 62, 2)
    assert engine.snapshot().reveal and engine.snapshot().feedback == "bad"
    tap(engine, 67, 3)
    assert not engine.results[0].first_try
    engine.command(Command(Action.HINT), 4)
    assert engine.snapshot().reveal
    tap(engine, 67, 5)
    assert not engine.results[1].first_try and json.loads(engine.results[1].details)["hint"]
    engine = study("note:treble:G4")
    engine.settings = Settings(auto_hint_misses=0)
    engine.command(Command(Action.PLAY), 0)
    for i in range(5):
        tap(engine, 60, 1 + i)
    assert not engine.snapshot().reveal


def test_answers_given_with_aids_showing_are_marked_assisted() -> None:
    """Verify answers given with aids showing are marked assisted."""
    engine = study("note:treble:G4")
    engine.settings = Settings(show_names=True)
    engine.command(Command(Action.PLAY), 0)
    assert engine.snapshot().assisted
    tap(engine, 67, 1)
    assert json.loads(engine.results[0].details)["assisted"]
    engine.settings = Settings(key_hints=True)
    assert engine.snapshot().reveal and engine.snapshot().expected == frozenset({67})
    technique = study("tech:rh:C_pentascale")
    technique.settings = Settings(show_names=True)
    assert not technique.snapshot().assisted


def test_leaving_mid_prompt_is_blameless_unless_a_wrong_key_was_played() -> None:
    """Verify leaving mid prompt is blameless unless a wrong key was played."""
    engine = study("phrase:treble:C:steps")
    engine.command(Command(Action.PLAY), 0)
    tap(engine, engine.prompt.atoms[0].pitches[0].midi, 1)
    engine.command(Command(Action.PAUSE), 2)
    assert json.loads(engine.results[0].details) == {
        "incomplete": True,
        "wrong_pitch_count": 0,
        "blameless": True,
    }
    engine.command(Command(Action.PLAY), 3)
    tap(engine, 30, 4)
    engine.command(Command(Action.SWITCH_SCENE, "ear"), 5)
    assert "blameless" not in json.loads(engine.results[1].details)
    assert engine.results[1].mode == "sight" and engine.scene == "ear"
    engine.command(Command(Action.PLAY), 6)
    engine.command(Command(Action.PAUSE), 7)
    assert len(engine.results) == 2  # nothing was played, so nothing is logged


def test_prompts_are_shuffled_only_when_a_random_source_is_given() -> None:
    """Verify prompts are shuffled only when a random source is given."""
    ids = [i.item_id for i in items_for("sight", 6) if i.kind == "note"]

    def order(rng: random.Random | None) -> list[str]:
        """Answer forty prompts correctly and return the order they came in."""
        engine = study(*ids, rng=rng)
        engine.command(Command(Action.PLAY), 0)
        seen = []
        for step in range(40):
            seen.append(engine.prompt.item_id)
            tap(engine, engine.prompt.atoms[0].pitches[0].midi, step + 1)
        return seen

    plain = order(None)
    assert plain[:17] == ids and plain[17:34] == ids
    mixed = order(random.Random(2))
    assert mixed[:17] != ids and sorted(mixed[:17]) == sorted(ids)
    assert all(a != b for a, b in zip(mixed, mixed[1:], strict=False))
    assert mixed != order(random.Random(3))


def test_rhythm_is_readable_before_play_and_next_moves_through_the_set() -> None:
    """Verify rhythm is readable before play and next moves through the set."""
    engine = study("rhythm:3/4:dotted_half", "rhythm:4/4:eighths")
    before = engine.snapshot()
    assert before.layout is not None and not before.running
    assert {g.name for g in before.layout.header if g.name in "234"} == {"3", "4"}
    assert len(before.layout.heads) == 2 and before.layout.measures == 2
    engine.command(Command(Action.NEXT), 0)
    after = engine.snapshot()
    assert after.title == "Eighth-note pairs (4/4)" and not after.running
    assert after.layout is not None and len(after.layout.heads) == 8
    engine.command(Command(Action.PLAY), 1)
    engine.command(Command(Action.PAUSE), 1.5)
    assert not engine.results  # stopping during the count-in is not an attempt


def test_rhythm_accepts_any_key_and_ignores_count_in_taps() -> None:
    """Verify rhythm accepts any key and ignores count in taps."""
    engine = study("rhythm:4/4:quarters")
    engine.settings = Settings(tempo_bpm=60)
    engine.command(Command(Action.PLAY), 10)
    engine.advance_to(11.5)
    counting = engine.snapshot()
    assert counting.pulse is not None and counting.pulse.count_in
    assert counting.pulse.position == 1.5 and counting.playhead is None
    for beat in range(3):
        tap(engine, 60, 10 + beat, hold=0.5)  # tapping along with the click
    for beat in range(8):
        tap(engine, 67, 14 + beat + 0.02, hold=0.9)
    engine.advance_to(17.0)
    running = engine.snapshot()
    assert running.playhead == 3.0 and running.pulse is not None and not running.pulse.count_in
    assert [state for _, _, state in running.marks] == ["hit"] * 8
    engine.advance_to(30)
    result = engine.results[0]
    assert result.first_try and result.played == (67,) * 8
    details = json.loads(result.details)
    assert details["hit_accuracy"] == 1.0 and details["stray_count"] == 0
    assert all(a["hold_grade"] == "DURATION_OK" for a in details["attacks"])
    assert "fluent" in engine.status and not engine.running


def test_stopping_a_rhythm_round_part_way_is_logged_without_blame() -> None:
    """Verify stopping a rhythm round part way is logged without blame."""
    engine = study("rhythm:4/4:quarters")
    engine.settings = Settings(tempo_bpm=60)
    engine.command(Command(Action.PLAY), 0)
    tap(engine, 60, 4.0)
    engine.command(Command(Action.PAUSE), 5.5)
    details = json.loads(engine.results[0].details)
    assert details["incomplete"] and details["blameless"] and not engine.results[0].first_try


def test_technique_shows_the_whole_pattern_and_counts_in_at_a_fixed_tempo() -> None:
    """Verify technique shows the whole pattern and counts in at a fixed tempo."""
    engine = study("tech:rh:C_pentascale", "tech:both:C_pentascale")
    engine.settings = Settings(technique_self_paced=False, tempo_bpm=60)
    preview = engine.snapshot()
    assert preview.layout is not None and len(preview.layout.heads) == 9
    assert preview.layout.measures == 3 and preview.fingering == "all"
    engine.command(Command(Action.PLAY), 0)
    assert len(engine.output) == 4 + 9  # a bar of count-in, then one click per note
    engine.advance_to(2.5)
    pulse = engine.snapshot().pulse
    assert pulse is not None and pulse.count_in and pulse.position == 2.5
    pitches = (60, 62, 64, 65, 67, 65, 64, 62, 60)
    for i, pitch in enumerate(pitches):
        tap(engine, pitch, 4 + i, hold=0.4)
        if i == 3:
            marks = engine.snapshot().marks
            assert [m[2] for m in marks] == ["done"] * 4 + ["current"]
    details = json.loads(engine.results[0].details)
    assert details["ioi_sd_ms"] == 0 and details["hit_accuracy"] == 1.0
    assert engine.snapshot().graph == (1000.0,) * 8 and not engine.running
    assert "Excellent" in engine.status
    first = engine.prompt.item_id
    engine.command(Command(Action.PLAY), 20)
    assert engine.prompt.item_id == first and engine.running  # Play repeats the pattern
    engine.command(Command(Action.NEXT), 21)
    assert engine.prompt.item_id == "tech:both:C_pentascale" and not engine.running
    both = engine.snapshot().layout
    assert both is not None and {h.staff for h in both.heads} == {0, 1}
    assert all(h.finger is not None for h in both.heads)


def test_self_paced_technique_clicks_follow_the_first_two_notes() -> None:
    """Verify self paced technique clicks follow the first two notes."""
    engine = study("tech:rh:C_pentascale")
    engine.command(Command(Action.PLAY), 0)
    assert not engine.output and engine.snapshot().pulse is None
    tap(engine, 60, 1.0)
    tap(engine, 62, 1.5)
    clicks = sorted(note.at for note in engine.output)
    assert len(clicks) == 7 and clicks[0] == 2.0 and clicks[1] - clicks[0] == 0.5
    engine.advance_to(1.75)
    assert engine.snapshot().pulse is not None


def test_ear_notes_are_heard_against_a_reference_and_revealed_when_found() -> None:
    """Verify ear notes are heard against a reference and revealed when found."""
    engine = study("ear:note:3", "ear:interval:P5")
    engine.command(Command(Action.PLAY), 0)
    assert [(note.pitch, note.at) for note in engine.output] == [(60, 0), (64, 1.0)]
    assert engine.evaluator is not None and engine.evaluator.must_strike == frozenset({64})
    listening = engine.snapshot()
    assert listening.layout is None and listening.prompt_text == "Listen…"
    assert listening.lit == frozenset({60}) and not listening.reveal
    tap(engine, 62, 3)
    engine.output.clear()
    engine.process_midi(ControlChange(67, 127, 3.5))  # the soft pedal replays for free
    assert [note.pitch for note in engine.output] == [60, 64]
    assert engine.evaluator is not None and len(engine.evaluator.played) == 1
    tap(engine, 64, 6)
    answered = engine.snapshot()
    assert not answered.running and answered.layout is not None
    assert answered.prompt_text == "It was E, degree 3 (mi) above C"
    assert not engine.results[0].first_try and engine.results[0].played == (62, 64)
    engine.output.clear()
    engine.command(Command(Action.REPLAY), 7)
    assert [note.pitch for note in engine.output] == [60, 64] and len(engine.results) == 1
    engine.output.clear()
    engine.command(Command(Action.PLAY), 8)
    assert engine.prompt.item_id == "ear:interval:P5"
    assert [(note.pitch, note.at) for note in engine.output] == [(60, 8), (67, 8.65)]
    tap(engine, 60, 10)
    tap(engine, 67, 11)
    assert engine.results[1].first_try and "perfect 5th" in engine.status


def test_tallies_and_titles_reach_the_snapshot() -> None:
    """Verify tallies and titles reach the snapshot."""
    engine = PracticeEngine()
    engine.configure_study(StudyConfig(items_for("sight", 1), "Unit 1"))
    assert engine.snapshot().set_title == "Unit 1" and engine.snapshot().title == "Treble G4"
    engine.command(Command(Action.PLAY), 0)
    tap(engine, 67, 1)
    tap(engine, 60, 2)
    tap(engine, 53, 3)
    snapshot = engine.snapshot()
    assert snapshot.chips == ("2 answered", "50% clean first time", "streak 0", "1 of 4 cleared")
    assert snapshot.feedback == "ok" and snapshot.completed == 2 and snapshot.scene == "sight"
    assert snapshot.held == frozenset() and snapshot.expected == frozenset({60})
    for scene in ("keys", "sight", "rush", "rhythm", "technique", "ear", "echo", "song"):
        engine.command(Command(Action.SWITCH_SCENE, scene), 10)
        assert engine.snapshot().scene == scene and engine.snapshot().instruction
