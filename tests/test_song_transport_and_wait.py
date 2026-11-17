import json
from fractions import Fraction
from pathlib import Path

import pytest

from consonance.core.builtin_scores import score_by_id
from consonance.core.engine import Action, Command, PracticeEngine
from consonance.core.input_and_grading import NoteOff, NoteOn, PianoStateTracker
from consonance.core.midi_output import MidiOutputLedger, Settings
from consonance.core.notation import Hand, MidiPitch
from consonance.core.song import SongNote, SongTimeline, checkpoints
from consonance.core.song_session import SongConfig, SongSession
from consonance.core.transport import SongTransport, TempoMap, TempoPoint, TransportState
from consonance.io.smf import MidiImport, export_midi


def test_piecewise_tempo_and_freeze() -> None:
    """Verify piecewise tempo and freeze."""
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
    """Verify wait halts future accompaniment and wall expiry."""
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
    """Verify held lh whole note is allowed at rh second beat."""
    notes = (
        SongNote(MidiPitch(48), Fraction(0), Fraction(4), Hand.LEFT),
        SongNote(MidiPitch(60), Fraction(0), Fraction(1), Hand.RIGHT),
        SongNote(MidiPitch(62), Fraction(1), Fraction(1), Hand.RIGHT),
    )
    steps = checkpoints(notes, frozenset(Hand))
    assert steps[1].allowed_held == frozenset({48})
    from consonance.core.input_and_grading import UntimedEvaluator

    piano = PianoStateTracker()
    piano.process(NoteOn(MidiPitch(48), 80, 0))
    piano.process(NoteOff(MidiPitch(60), 0.9))
    evaluator = UntimedEvaluator(steps[1].must_strike, 1, steps[1].allowed_held)
    event = NoteOn(MidiPitch(62), 80, 1.1)
    piano.process(event)
    assert evaluator.process(event, piano)


@pytest.mark.parametrize("ppqn", [96, 960])
def test_beat_clustering_is_resolution_invariant(tmp_path: Path, ppqn: int) -> None:
    """Verify beat clustering is resolution invariant."""
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


def melody(*pitches: int, left: int | None = None) -> SongTimeline:
    """Build a one-note-per-beat right-hand line at 60 BPM, optionally over a held bass note."""
    notes = [
        SongNote(MidiPitch(p), Fraction(i), Fraction(1), Hand.RIGHT) for i, p in enumerate(pitches)
    ]
    if left is not None:
        notes.append(SongNote(MidiPitch(left), Fraction(1), Fraction(1), Hand.LEFT))
    return SongTimeline("t", "test", tuple(notes), TempoMap((TempoPoint(0, 60),)))


class Player:
    """Drive a song session with explicit timestamps."""

    def __init__(self, config: SongConfig) -> None:
        """Create a session with the metronome off so output holds only accompaniment."""
        self.piano = PianoStateTracker()
        self.session = SongSession(config, Settings(metronome="Off"), self.piano)
        self.now = 0.0

    def state(self) -> TransportState:
        """Return what the song clock is doing right now."""
        return self.session.transport.state

    def run(self, until: float) -> None:
        """Advance the clock in two-millisecond ticks."""
        while self.now < until - 1e-9:
            self.now = round(self.now + 0.002, 6)
            self.session.advance_to(self.now)

    def tap(self, pitch: int, at: float, hold: float = 0.2) -> None:
        """Press and release one key at an explicit time."""
        for event in (NoteOn(MidiPitch(pitch), 80, at), NoteOff(MidiPitch(pitch), at + hold)):
            self.piano.process(event)
            self.session.process_midi(event)


def test_wait_mode_accepts_a_note_played_ahead_of_the_beat() -> None:
    """Verify wait mode accepts a note played ahead of the beat."""
    player = Player(SongConfig(melody(60, 62, left=48), tempo_scale=1))
    player.session.play(0)
    assert player.state() == TransportState.PLAYING  # no count-in in Wait mode
    player.run(0.1)
    assert player.state() == TransportState.PAUSED_WAIT
    player.tap(60, 0.2, hold=0.6)
    player.run(1.17)  # the second beat would arrive at 1.2
    assert player.session.targets == frozenset({62})
    player.tap(62, 1.17)
    assert player.session.step_index == 2
    assert player.session.transport.state == TransportState.PLAYING
    assert player.session.transport.beat_at(1.17) == 1.0  # the music moved up to meet the player
    assert [(note.pitch, note.at) for note in player.session.output] == [(48, 1.17)]
    player.run(3.0)
    assert player.session.finished and len(player.session.results) == 1


def test_wait_mode_logs_one_attempt_per_pass_and_play_starts_over() -> None:
    """Verify wait mode logs one attempt per pass and play starts over."""
    player = Player(SongConfig(melody(60, 62, 64, 65), tempo_scale=1))
    player.session.play(0)
    player.run(0.1)
    for i, pitch in enumerate((60, 62, 61, 64, 65)):  # one wrong key on the way
        player.tap(pitch, 0.5 + i * 0.5)
    player.run(6.0)
    result = player.session.results[0]
    assert len(player.session.results) == 1 and result.complete and result.steps == 4
    assert result.accuracy == 0.75 and not result.clean
    assert result.played == (60, 62, 61, 64, 65)
    assert "75%" in player.session.status and not player.session.active
    player.session.play(10.0)
    player.run(10.1)
    assert player.session.transport.beat_at(player.now) == 0.0 and player.session.active
    assert len(player.session.results) == 1  # replaying adds nothing until it is played


def test_finished_tempo_pass_is_not_logged_again_by_pressing_play() -> None:
    """Verify finished tempo pass is not logged again by pressing play."""
    config = SongConfig(melody(60, 62, 64, 65), mode="Tempo", tempo_scale=1, auto_ramp=True)
    player = Player(config)
    player.session.play(0)
    for i in range(4):
        player.run(4.0 + i)
        player.tap(60 + (0, 2, 4, 5)[i], player.now)
    player.run(8.5)
    assert len(player.session.results) == 1 and player.session.results[0].clean
    assert player.session.ramp.streak == 1 and player.session.finished
    for _ in range(3):
        player.session.play(player.now)
        player.run(player.now + 1.0)
        player.session.pause(player.now)
    assert player.session.ramp.streak == 1 and player.session.transport.tempo_scale == 1
    assert [r.complete for r in player.session.results] == [True]


def test_tempo_mode_resumes_with_a_count_in_that_judging_follows() -> None:
    """Verify tempo mode resumes with a count in that judging follows."""
    player = Player(SongConfig(melody(60, 62, 64, 65), mode="Tempo", tempo_scale=1))
    player.session.play(0)
    assert player.session.pulse(1.5) == (4, 1.5, True)
    player.run(1.0)
    player.session.pause(1.0)  # paused during the count-in
    player.session.play(10.0)
    grader = player.session.grader
    assert grader is not None and grader.expected[0].at == 14.0
    assert player.session.transport.count_end == 14.0
    player.run(14.0)
    player.tap(60, 14.0)
    player.run(15.0)
    player.tap(62, 15.01)
    player.run(15.4)
    player.session.pause(15.4)  # paused mid-song
    assert not player.session.results and player.session.status.startswith("Paused")
    player.session.play(20.0)
    assert player.session.transport.state == TransportState.COUNT_IN
    assert grader.expected[2].at == pytest.approx(24.0 + (2 - 1.4))
    player.run(24.6)
    player.tap(64, 24.6)
    player.run(25.6)
    player.tap(65, 25.6)
    player.run(27.0)
    result = player.session.results[0]
    assert result.complete and result.accuracy == 1.0 and len(player.session.results) == 1


def test_early_count_in_noodling_is_not_a_stray_and_seek_reselects() -> None:
    """Verify early count in noodling is not a stray and seek reselects."""
    player = Player(SongConfig(melody(60, 62, 64, 65, 67, 69, 71, 72), mode="Tempo", tempo_scale=1))
    player.session.play(0)
    player.tap(60, 1.0)
    grader = player.session.grader
    assert grader is not None and not grader.strays and not player.session.played
    player.tap(60, 3.9)  # a slightly early first note still counts
    assert grader.hits[0].error_ms == pytest.approx(-100)
    player.session.seek(4.0, 10.0)
    assert [float(n.start_beat) for n in player.session.selected] == [4, 5, 6, 7]
    assert player.session.start == 4.0 and len(player.session.results) == 1
    assert not player.session.results[0].complete


def play_steps(engine: PracticeEngine, count: int, start: float) -> float:
    """Answer the next Wait-mode chords correctly, half a second apart."""
    now = start
    for _ in range(count):
        engine.advance_to(now)
        song = engine.song
        assert song is not None
        for pitch in sorted(song.targets):
            engine.process_midi(NoteOn(MidiPitch(pitch), 80, now))
        for pitch in sorted(engine.piano.physically_held):
            engine.process_midi(NoteOff(pitch, now + 0.1))
        now += 0.5
    return now


def test_song_passes_carry_curriculum_identities_and_partials_are_blameless() -> None:
    """Verify song passes carry curriculum identities and partials are blameless."""
    engine = PracticeEngine()
    engine.command(Command(Action.SWITCH_SCENE, "song"), 0)
    ready = engine.snapshot()
    assert ready.title == "Hot Cross Buns • right hand" and ready.scrolling and not ready.running
    assert ready.layout is not None and ready.layout.labels[0].text == "1"
    engine.command(Command(Action.PLAY), 0)
    now = play_steps(engine, 3, 0.1)
    view = engine.snapshot()
    states = sorted(state for staff, _, state in view.marks if staff == 0)
    assert states == ["current", "done", "done", "done"] and view.reveal and view.expected
    assert view.progress is not None and 0 < view.progress < 1
    assert "3 of 3 clean" in view.chips and "Wait mode" in view.chips
    engine.command(Command(Action.SWITCH_SCENE, "sight"), now)
    partial = engine.results[0]
    assert partial.item_id == "song:hot_cross_buns:all:rh" and partial.mode == "song"
    assert json.loads(partial.details) == {
        "hit_accuracy": 1.0,
        "tempo_scale": 0.7,
        "mode": "Wait",
        "steps": 3,
        "incomplete": True,
        "blameless": True,
    }
    ode = score_by_id("ode_to_joy")
    study = score_by_id("coordination")
    assert ode is not None and study is not None
    engine.configure_song(SongConfig(ode.compile(), start_measure=3, end_measure=4))
    engine.command(Command(Action.PLAY), 100)
    now = play_steps(engine, 7, 100.1)
    engine.advance_to(now + 10)
    section = engine.results[1]
    assert section.item_id == "song:ode_to_joy:3-4:rh" and section.first_try
    assert "incomplete" not in json.loads(section.details) and not engine.running
    engine.configure_song(SongConfig(study.compile(), hands=frozenset(Hand)))
    assert engine.snapshot().layout is not None
    engine.command(Command(Action.PLAY), 200)
    play_steps(engine, 2, 200.1)
    engine.abandon()
    assert engine.results[2].item_id == "coord:ostinato:C"


def test_tempo_mode_colours_notes_and_shows_the_beat() -> None:
    """Verify tempo mode colours notes and shows the beat."""
    lamb = score_by_id("mary_lamb")
    assert lamb is not None
    engine = PracticeEngine()
    engine.settings = Settings(metronome="Piano")
    engine.configure_song(SongConfig(lamb.compile(), mode="Tempo", tempo_scale=1.0))
    engine.command(Command(Action.PLAY), 0)
    beat = 60 / 84
    assert len(engine.output) == 4  # the count-in clicks
    engine.advance_to(beat * 1.5)
    counting = engine.snapshot()
    assert counting.pulse is not None and counting.pulse.count_in and counting.beats_per_second == 0
    engine.advance_to(beat * 4)
    engine.process_midi(NoteOn(MidiPitch(64), 80, beat * 4 + 0.01))  # E on time
    engine.process_midi(NoteOn(MidiPitch(62), 80, beat * 5 + 0.1))  # D a little late
    engine.advance_to(beat * 7)
    playing = engine.snapshot()
    marks = {index: state for staff, index, state in playing.marks if staff == 0}
    assert marks == {0: "hit", 1: "near", 2: "miss"}
    assert playing.pulse is not None and not playing.pulse.count_in and playing.pulse.beats == 4
    assert playing.beats_per_second == pytest.approx(84 / 60)
    assert playing.status.startswith("Late") and playing.expected == frozenset()


def test_a_hand_with_no_notes_logs_nothing() -> None:
    """Verify a hand with no notes logs nothing."""
    for mode in ("Wait", "Tempo"):
        config = SongConfig(melody(60, 62), mode=mode, hands=frozenset({Hand.LEFT}), tempo_scale=1)
        player = Player(config)
        player.session.play(0)
        player.run(8.0)
        assert player.session.finished and not player.session.results
        assert "no notes" in player.session.status
