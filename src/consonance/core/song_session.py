"""Wait/Tempo song execution; accompaniment is emitted only as beats are crossed."""

from dataclasses import dataclass, replace

from consonance.core.input_and_grading import (
    MidiEvent,
    NoteOn,
    PianoStateTracker,
    UntimedEvaluator,
)
from consonance.core.midi_output import OutputNote, Settings
from consonance.core.notation import Hand
from consonance.core.rhythm import ExpectedStrike, Grade, TimedGrader, describe_attack
from consonance.core.song import AutoRamp, Checkpoint, SongNote, SongTimeline, checkpoints
from consonance.core.transport import SongTransport, TransportState

ANTICIPATION = 0.25  # seconds before a count-in ends in which the first notes already count
RUNNING = (TransportState.COUNT_IN, TransportState.PLAYING, TransportState.PAUSED_WAIT)


@dataclass(frozen=True)
class SongConfig:
    """Everything that defines one way of practising a song."""

    timeline: SongTimeline
    mode: str = "Wait"
    hands: frozenset[Hand] = frozenset({Hand.RIGHT})
    tempo_scale: float = 0.7
    start_measure: int = 1
    end_measure: int = 0
    loop: bool = False
    auto_ramp: bool = False
    item_id: str = ""

    def __post_init__(self) -> None:
        """Reject impossible modes, hands, sections, and tempo scales."""
        total = self.timeline.measure_count
        if self.mode not in ("Wait", "Tempo") or not self.hands:
            raise ValueError("Choose Wait/Tempo mode and at least one hand")
        if not 1 <= self.start_measure <= (self.end_measure or total) <= total:
            raise ValueError("Loop measures must lie inside the song, with A <= B")
        if not 0.25 <= self.tempo_scale <= 1.25:
            raise ValueError("Tempo scale must be in 0.25..1.25")

    @property
    def hand_name(self) -> str:
        """Return ``rh``, ``lh`` or ``both`` for the hands being practised."""
        return "both" if len(self.hands) == 2 else next(iter(self.hands)).value

    @property
    def section(self) -> str:
        """Return ``all`` for the whole song, otherwise the measure range practised."""
        total = self.timeline.measure_count
        if self.start_measure == 1 and (self.end_measure or total) == total:
            return "all"
        return f"{self.start_measure}-{self.end_measure or total}"


@dataclass(frozen=True)
class SongResult:
    """One pass through the chosen section, complete or abandoned part-way."""

    expected: tuple[int, ...]
    played: tuple[int, ...]
    velocities: tuple[int, ...]
    clean: bool
    spread_ms: float | None
    response_ms: float | None
    timing_error_ms: float | None
    accuracy: float
    tempo_scale: float
    complete: bool = True
    steps: int = 0


class SongSession:
    """Run one song configuration.

    In Wait mode the music follows the player: each chord may be played as soon as the
    previous one is done, the accompaniment jumps forward to meet an early note, and the
    transport freezes at a chord that has not arrived yet. In Tempo mode the transport
    never waits and every attack is graded against the beat.
    """

    def __init__(self, config: SongConfig, settings: Settings, piano: PianoStateTracker) -> None:
        """Prepare a stopped session for ``config``."""
        self.config = config
        self.settings = settings
        self.piano = piano
        self.transport = SongTransport(config.timeline.tempo, config.tempo_scale)
        self.start = float((config.start_measure - 1) * config.timeline.time.beats)
        self.end = (
            float(config.end_measure * config.timeline.time.beats)
            if config.end_measure
            else config.timeline.end_beat
        )
        self.steps: tuple[Checkpoint, ...] = ()
        self.selected: tuple[SongNote, ...] = ()
        self._select()
        self.step_index = 0
        self.evaluator: UntimedEvaluator | None = None
        self.grader: TimedGrader | None = None
        self.output: list[OutputNote] = []
        self.results: list[SongResult] = []
        self.release_requested = False
        self.emitted: set[int] = set()
        self.clicked: set[int] = set()
        self.ramp = AutoRamp(config.auto_ramp)
        self.clean_steps = 0
        self.total_steps = 0
        self.played: list[int] = []
        self.velocities: list[int] = []
        self.finished = False
        self.passes = 0
        self.last_accuracy: float | None = None
        self.feedback: tuple[str, float] | None = None
        self.status = (
            "Ready • press Play, then play each note when you are ready"
            if self.wait
            else "Ready • press Play for a one-bar count-in"
        )

    @property
    def wait(self) -> bool:
        """Report whether this session follows the player rather than the clock."""
        return self.config.mode == "Wait"

    @property
    def active(self) -> bool:
        """Report whether a pass is under way (including waiting for the player)."""
        return self.transport.state in RUNNING

    @property
    def engaged(self) -> bool:
        """Report whether the clock itself is moving, so practice time should accrue."""
        return self.transport.state in (TransportState.COUNT_IN, TransportState.PLAYING)

    @property
    def targets(self) -> frozenset[int]:
        """Return the keys Wait mode is currently listening for."""
        return frozenset(self.evaluator.must_strike) if self.evaluator else frozenset()

    @property
    def allowed(self) -> frozenset[int]:
        """Return earlier notes that may legitimately still be held."""
        return frozenset(self.evaluator.allowed_held) if self.evaluator else frozenset()

    @property
    def focus_beat(self) -> float | None:
        """Return the beat of the chord Wait mode wants next, if a pass is under way."""
        if self.wait and self.active and self.step_index < len(self.steps):
            return self.steps[self.step_index].beat
        return None

    def progress(self, now: float) -> float:
        """Return how far through the chosen section the transport is, from 0 to 1."""
        length = max(1e-9, self.end - self.start)
        return min(1.0, max(0.0, (self.transport.beat_at(now) - self.start) / length))

    def pulse(self, now: float) -> tuple[int, float, bool] | None:
        """Return (beats per bar, position in the bar, counting in) while the clock runs."""
        beats = self.config.timeline.time.numerator
        counting = self.transport.count_in_position(now)
        if counting is not None:
            return beats, counting, True
        if self.transport.state == TransportState.PLAYING and not self.wait:
            return beats, self.transport.beat_at(now) % beats, False
        return None

    def graded(self) -> list[tuple[SongNote, Grade]]:
        """Return the Tempo-mode notes judged so far in this pass, with their grades."""
        if self.grader is None:
            return []
        return [(self.selected[i], hit.grade) for i, hit in self.grader.hits.items()]

    def _select(self) -> None:
        """Pick the notes and Wait-mode chords inside the practised section."""
        hands = self.config.hands
        self.selected = tuple(
            n
            for n in self.config.timeline.notes
            if n.hand in hands and self.start <= n.start_beat < self.end
        )
        self.steps = tuple(
            c
            for c in checkpoints(self.config.timeline.notes, hands)
            if self.start <= c.beat < self.end
        )

    def _beat_seconds(self) -> float:
        """Return the length of one count-in beat at the current speed."""
        return 60 / self.config.timeline.tempo.points[0].bpm / self.transport.tempo_scale

    def _count_in(self, now: float, beats: int) -> None:
        """Schedule the metronome clicks of a count-in bar."""
        for i in range(beats):
            click = self.settings.click(now + i * self._beat_seconds(), i == 0)
            if click:
                self.output.append(click)

    def _retime(self, beat: float, wall: float) -> None:
        """Re-anchor timed judging so that song ``beat`` falls at wall time ``wall``."""
        if self.grader is None:
            return
        tempo, scale = self.config.timeline.tempo, self.transport.tempo_scale
        origin = tempo.seconds_at(beat)
        self.grader.expected = tuple(
            replace(strike, at=wall + (tempo.seconds_at(float(note.start_beat)) - origin) / scale)
            for strike, note in zip(self.grader.expected, self.selected, strict=True)
        )

    def _arm(self, now: float) -> None:
        """Start listening for the next Wait-mode chord."""
        step = self.steps[self.step_index]
        self.evaluator = UntimedEvaluator(step.must_strike, now, step.allowed_held)

    def play(self, now: float) -> None:
        """Start a pass, or continue one the user paused."""
        state = self.transport.state
        if state in RUNNING:
            return
        if state != TransportState.PAUSED_USER or self.finished:
            self.restart(now)
        elif self.wait:
            self.transport.play(now)
            self.status = "Playing • the music waits for you"
        else:
            # Coming back in tempo needs a bar to find the pulse again.
            beats = self.config.timeline.time.numerator
            self.transport.play(now, count_in_beats=beats)
            self._count_in(now, beats)
            self._retime(self.transport.beat_at(now), self.transport.count_end)
            self.status = "Count in…"

    def restart(self, now: float, *, count_in: bool | None = None) -> None:
        """Begin a fresh pass from the section start; Tempo mode counts in by default."""
        self._abandon_pass()
        self.finished = False
        self.release_requested = True
        self.output.clear()
        self.step_index = 0
        self.evaluator = None
        self.emitted.clear()
        self.clicked.clear()
        counted = (not self.wait) if count_in is None else count_in
        beats = self.config.timeline.time.numerator if counted else 0
        self.transport.play(now, self.start, beats)
        self._count_in(now, beats)
        begin = self.transport.count_end if beats else now
        self.grader = None
        if not self.wait:
            tempo, scale = self.config.timeline.tempo, self.transport.tempo_scale
            self.grader = TimedGrader(
                tuple(
                    ExpectedStrike(
                        n.pitch,
                        0.0,
                        (
                            tempo.seconds_at(float(n.start_beat + n.duration))
                            - tempo.seconds_at(float(n.start_beat))
                        )
                        / scale,
                    )
                    for n in self.selected
                ),
                self.settings.midi_judge_offset_ms,
            )
            self._retime(self.start, begin)
        elif not beats and self.steps:
            self._arm(now)
        self.status = "Count in…" if beats else "Play when ready" if self.wait else "Playing"

    def pause(self, now: float) -> None:
        """Freeze a running pass so that Play can pick it up again."""
        self.release_requested = True
        if self.transport.state in RUNNING:
            self.transport.pause(now)
            self.status = "Paused • press Play to continue"

    def abandon(self, now: float) -> None:
        """Give up the current pass, logging it as incomplete if it had been started."""
        self._abandon_pass()
        self.transport.stop(now)
        self.evaluator = None
        self.release_requested = True

    def _abandon_pass(self) -> None:
        """Record an unfinished pass (never as a mistake) and clear its tallies."""
        unfinished = not self.finished and self.transport.state != TransportState.STOPPED
        if unfinished and self.played:
            self.results.append(
                SongResult(
                    tuple(int(n.pitch) for n in self.selected),
                    tuple(self.played),
                    tuple(self.velocities),
                    False,
                    None,
                    None,
                    self.grader.mean_error_ms if self.grader else None,
                    self.grader.accuracy
                    if self.grader
                    else self.clean_steps / max(1, self.total_steps),
                    self.transport.tempo_scale,
                    complete=False,
                    steps=self.total_steps,
                )
            )
        self.played = []
        self.velocities = []
        self.clean_steps = self.total_steps = 0

    def seek(self, beat: float, now: float) -> None:
        """Restart from a different beat inside the section."""
        self.ramp.streak = 0
        self._abandon_pass()
        self.start = max(0.0, min(beat, self.end - 0.001))
        self._select()
        self.restart(now)

    def process_midi(self, event: MidiEvent, soft_tap: bool = False) -> None:
        """Apply a timestamped MIDI event to the current practice state."""
        if soft_tap:
            self.ramp.streak = 0
            self.restart(event.timestamp)
            return
        struck = isinstance(event, NoteOn) and bool(event.velocity)
        if self.wait:
            if self.evaluator is None:
                return
            if isinstance(event, NoteOn) and struck:
                self.played.append(int(event.pitch))
                self.velocities.append(event.velocity)
            if self.evaluator.process(event, self.piano):
                self._step_done(event.timestamp)
            elif isinstance(event, NoteOn) and struck and not self.evaluator.accepts(event.pitch):
                self.feedback = ("bad", event.timestamp)
                self.status = "Not that key • release it and play the highlighted notes"
            return
        counting = self.transport.state == TransportState.COUNT_IN
        if counting and event.timestamp < self.transport.count_end - ANTICIPATION:
            return
        if (
            self.grader
            and isinstance(event, NoteOn)
            and struck
            and self.transport.state in (TransportState.PLAYING, TransportState.COUNT_IN)
        ):
            hit = self.grader.strike(event.pitch, event.timestamp)
            self.played.append(int(event.pitch))
            self.velocities.append(event.velocity)
            good = hit.grade in (Grade.PERFECT, Grade.GOOD)
            self.feedback = ("good" if good else "bad", event.timestamp)
            self.status = describe_attack(hit.grade, hit.error_ms)

    def _step_done(self, now: float) -> None:
        """Credit a completed Wait-mode chord and let the music move on."""
        evaluator = self.evaluator
        assert evaluator is not None
        step = self.steps[self.step_index]
        clean = evaluator.is_first_try_correct
        self.clean_steps += int(clean)
        self.total_steps += 1
        self.step_index += 1
        self.evaluator = None
        self.feedback = ("good" if clean else "ok", now)
        state = self.transport.state
        if state == TransportState.PAUSED_WAIT:
            self.transport.play(now)
        elif state == TransportState.PLAYING and self.transport.beat_at(now) < step.beat - 1e-9:
            # The player is ahead of the clock: bring the music forward to meet them.
            for index, note in enumerate(self.config.timeline.notes):
                if note.start_beat < step.beat - 1e-6:
                    self.emitted.add(index)
            self.transport.play(now, beat=step.beat)
            self._accompaniment(step.beat, now)
        self.status = f"{self.clean_steps} of {self.total_steps} clean so far"
        if self.step_index < len(self.steps):
            self._arm(now)

    def _accompaniment(self, beat: float, now: float) -> None:
        """Sound every not-yet-played note of the hands the computer is covering."""
        tempo = self.config.timeline.tempo
        for i, note in enumerate(self.config.timeline.notes):
            if (
                i not in self.emitted
                and note.hand not in self.config.hands
                and self.start <= note.start_beat < self.end
                and note.start_beat <= beat + 1e-8
            ):
                duration = tempo.seconds_at(float(note.start_beat + note.duration)) - (
                    tempo.seconds_at(float(note.start_beat))
                )
                self.output.append(
                    OutputNote(
                        now,
                        note.pitch,
                        duration / self.transport.tempo_scale,
                        note.velocity,
                        self.settings.piano_channel,
                    )
                )
                self.emitted.add(i)

    def advance_to(self, now: float) -> None:
        """Advance scheduled state to the supplied monotonic time in seconds."""
        counting = self.transport.state == TransportState.COUNT_IN
        beat = self.transport.advance_to(now)
        state = self.transport.state
        if counting and state == TransportState.PLAYING:
            self.status = "Play when ready" if self.wait else "Playing • stay with the click"
        waiting_steps = self.wait and self.step_index < len(self.steps)
        if state == TransportState.COUNT_IN:
            if waiting_steps and self.evaluator is None:
                if now >= self.transport.count_end - ANTICIPATION:
                    self._arm(now)
            return
        if state != TransportState.PLAYING:
            return
        if waiting_steps:
            step = self.steps[self.step_index]
            if self.evaluator is None:
                self._arm(now)
            if beat >= step.beat:
                self._accompaniment(step.beat, now)
                self.transport.pause(now, wait=True, checkpoint=step.beat)
                self.status = "Waiting for you • play the highlighted notes"
                return
        self._accompaniment(min(beat, self.end - 0.00001), now)
        if not self.wait:
            tick = int(beat)
            if tick not in self.clicked and beat < self.end:
                self.clicked.add(tick)
                downbeat = tick % self.config.timeline.time.numerator == 0
                click = self.settings.click(now, downbeat)
                if click:
                    self.output.append(click)
            if self.grader:
                self.grader.advance_to(now)
        if beat >= self.end:
            self._finish_pass(now)

    def _finish_pass(self, now: float) -> None:
        """Log a completed pass, apply the auto-ramp, then loop or come to rest."""
        tempo_mode = not self.wait
        if tempo_mode and self.grader:
            accuracy = self.grader.accuracy
            timing: float | None = self.grader.mean_error_ms
            clean = accuracy >= 0.9
        else:
            accuracy = self.clean_steps / max(1, self.total_steps)
            timing = None
            clean = accuracy >= 0.9 and self.total_steps == len(self.steps)
        if (tempo_mode and self.selected) or self.total_steps:
            self.results.append(
                SongResult(
                    tuple(int(n.pitch) for n in self.selected),
                    tuple(self.played),
                    tuple(self.velocities),
                    clean,
                    None,
                    None,
                    timing,
                    accuracy,
                    self.transport.tempo_scale,
                    steps=self.total_steps,
                )
            )
        self.passes += 1
        self.last_accuracy = accuracy
        self.played = []
        self.velocities = []
        self.clean_steps = self.total_steps = 0
        old_scale = self.transport.tempo_scale
        new_scale = self.ramp.complete_pass(accuracy, old_scale, tempo_mode=tempo_mode)
        self.transport.set_scale(new_scale, now)
        self.finished = True
        self.feedback = ("good" if clean else "ok", now)
        if self.config.loop:
            self.restart(now, count_in=False)
        else:
            self.transport.pause(now, checkpoint=self.end)
            self.evaluator = None
            self.release_requested = True
        if not self.selected:
            self.status = "This hand has no notes in the chosen section • pick the other hand"
        elif new_scale > old_scale:
            self.status = f"Three clean passes! Tempo +5% → {new_scale:.0%}"
        elif tempo_mode:
            self.status = f"Pass complete • {accuracy:.0%} on time • tempo {new_scale:.0%}"
        else:
            self.status = f"Pass complete • {accuracy:.0%} of chords clean first time"
