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
from consonance.core.rhythm import ExpectedStrike, TimedGrader
from consonance.core.song import AutoRamp, SongTimeline, checkpoints
from consonance.core.transport import SongTransport, TransportState


@dataclass(frozen=True)
class SongConfig:
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
        total = max(1, int((self.timeline.end_beat - 0.00001) // self.timeline.time.numerator) + 1)
        if self.mode not in ("Wait", "Tempo") or not self.hands:
            raise ValueError("Choose Wait/Tempo mode and at least one hand")
        if not 1 <= self.start_measure <= (self.end_measure or total) <= total:
            raise ValueError("Loop measures must lie inside the song, with A <= B")
        if not 0.25 <= self.tempo_scale <= 1.25:
            raise ValueError("Tempo scale must be in 0.25..1.25")


@dataclass(frozen=True)
class SongResult:
    expected: tuple[int, ...]
    played: tuple[int, ...]
    velocities: tuple[int, ...]
    clean: bool
    spread_ms: float | None
    response_ms: float | None
    timing_error_ms: float | None
    accuracy: float
    tempo_scale: float


class SongSession:
    def __init__(self, config: SongConfig, settings: Settings, piano: PianoStateTracker) -> None:
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
        self.steps = tuple(
            c
            for c in checkpoints(config.timeline.notes, config.hands)
            if self.start <= c.beat < self.end
        )
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
        self.status = "Ready • press Play for a one-bar count-in"
        self.played: list[int] = []
        self.velocities: list[int] = []
        self._paused_at = 0.0

    @property
    def active(self) -> bool:
        return self.transport.state in (
            TransportState.COUNT_IN,
            TransportState.PLAYING,
            TransportState.PAUSED_WAIT,
        )

    def play(self, now: float) -> None:
        if self.transport.state == TransportState.PAUSED_USER:
            if self.grader:
                delta = now - self._paused_at
                self.grader.expected = tuple(
                    replace(n, at=n.at + delta) for n in self.grader.expected
                )
            self.transport.play(now)
        else:
            self.restart(now)

    def restart(self, now: float, *, count_in: bool = True) -> None:
        self.release_requested = True
        self.output.clear()
        self.step_index = 0
        self.evaluator = None
        self.emitted.clear()
        self.clicked.clear()
        self.played = []
        self.velocities = []
        self.clean_steps = self.total_steps = 0
        count = self.config.timeline.time.numerator if count_in else 0
        self.transport.play(now, self.start, count)
        seconds = 60 / self.config.timeline.tempo.points[0].bpm / self.transport.tempo_scale
        for i in range(count):
            click = self.settings.click(now + i * seconds, i == 0)
            if click:
                self.output.append(click)
        begin = now + count * seconds
        self.grader = TimedGrader(
            tuple(
                ExpectedStrike(
                    n.pitch,
                    begin
                    + (
                        self.config.timeline.tempo.seconds_at(float(n.start_beat))
                        - self.config.timeline.tempo.seconds_at(self.start)
                    )
                    / self.transport.tempo_scale,
                    (
                        self.config.timeline.tempo.seconds_at(float(n.start_beat + n.duration))
                        - self.config.timeline.tempo.seconds_at(float(n.start_beat))
                    )
                    / self.transport.tempo_scale,
                )
                for n in self.config.timeline.notes
                if n.hand in self.config.hands and self.start <= n.start_beat < self.end
            ),
            self.settings.midi_judge_offset_ms,
        )
        self.status = "Count in…" if count else "Playing"

    def pause(self, now: float) -> None:
        if self.evaluator and self.evaluator.played:
            e = self.evaluator
            self.results.append(
                SongResult(
                    tuple(sorted(e.must_strike)),
                    tuple(e.played),
                    tuple(e.velocities),
                    False,
                    e.chord_spread_ms,
                    None,
                    None,
                    self.clean_steps / max(1, self.total_steps + 1),
                    self.transport.tempo_scale,
                )
            )
            self.evaluator = None
        elif self.config.mode == "Tempo" and self.played and self.grader:
            self.results.append(
                SongResult(
                    tuple(n.pitch for n in self.grader.expected),
                    tuple(self.played),
                    tuple(self.velocities),
                    False,
                    None,
                    None,
                    self.grader.mean_error_ms,
                    self.grader.accuracy,
                    self.transport.tempo_scale,
                )
            )
            self.played = []
            self.velocities = []
        self.transport.pause(now)
        self._paused_at = now
        self.release_requested = True
        self.status = "Paused"

    def seek(self, beat: float, now: float) -> None:
        self.ramp.streak = 0
        self.start = max(0.0, min(beat, self.end - 0.001))
        self.restart(now)

    def process_midi(self, event: MidiEvent, soft_tap: bool = False) -> None:
        if soft_tap:
            self.ramp.streak = 0
            self.restart(event.timestamp)
            return
        if self.transport.state == TransportState.PAUSED_WAIT and self.evaluator:
            if self.evaluator.process(event, self.piano):
                e = self.evaluator
                self.clean_steps += int(e.is_first_try_correct)
                self.total_steps += 1
                self.results.append(
                    SongResult(
                        tuple(sorted(e.must_strike)),
                        tuple(e.played),
                        tuple(e.velocities),
                        e.is_first_try_correct,
                        e.chord_spread_ms,
                        e.response_ms,
                        None,
                        self.clean_steps / self.total_steps,
                        self.transport.tempo_scale,
                    )
                )
                self.step_index += 1
                self.evaluator = None
                self.transport.play(event.timestamp)
                self.status = f"Clean Step {self.clean_steps / self.total_steps:.0%}"
            elif isinstance(event, NoteOn) and event.pitch not in self.evaluator.must_strike:
                self.status = "Release the extra key, then complete the chord"
        elif (
            self.config.mode == "Tempo"
            and self.transport.state in (TransportState.PLAYING, TransportState.COUNT_IN)
            and self.grader
            and isinstance(event, NoteOn)
            and event.velocity
        ):
            hit = self.grader.strike(event.pitch, event.timestamp)
            self.played.append(event.pitch)
            self.velocities.append(event.velocity)
            self.status = f"{hit.grade} • {hit.error_ms or 0:+.0f}ms"

    def _accompaniment(self, beat: float, now: float) -> None:
        for i, note in enumerate(self.config.timeline.notes):
            if (
                i not in self.emitted
                and note.hand not in self.config.hands
                and self.start <= note.start_beat < self.end
                and note.start_beat <= beat + 1e-8
            ):
                duration = self.config.timeline.tempo.seconds_at(
                    float(note.start_beat + note.duration)
                ) - self.config.timeline.tempo.seconds_at(float(note.start_beat))
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
        beat = self.transport.advance_to(now)
        if self.transport.state != TransportState.PLAYING:
            return
        if self.config.mode == "Wait" and self.step_index < len(self.steps):
            checkpoint = self.steps[self.step_index]
            if beat >= checkpoint.beat:
                self._accompaniment(checkpoint.beat, now)
                self.transport.pause(now, wait=True, checkpoint=checkpoint.beat)
                self.evaluator = UntimedEvaluator(
                    checkpoint.must_strike, now, checkpoint.allowed_held
                )
                self.status = "Waiting for your notes • roll the chord at your own pace"
                return
        self._accompaniment(min(beat, self.end - 0.00001), now)
        tick = int(beat)
        if tick not in self.clicked:
            self.clicked.add(tick)
            click = self.settings.click(now, tick % self.config.timeline.time.numerator == 0)
            if click:
                self.output.append(click)
        if self.grader and self.config.mode == "Tempo":
            self.grader.advance_to(now)
        if beat >= self.end:
            accuracy = (
                self.grader.accuracy
                if self.config.mode == "Tempo" and self.grader
                else self.clean_steps / max(1, self.total_steps)
            )
            if self.config.mode == "Tempo" and self.grader:
                self.results.append(
                    SongResult(
                        tuple(n.pitch for n in self.grader.expected),
                        tuple(self.played),
                        tuple(self.velocities),
                        accuracy >= 0.9,
                        None,
                        None,
                        self.grader.mean_error_ms,
                        accuracy,
                        self.transport.tempo_scale,
                    )
                )
            old_scale = self.transport.tempo_scale
            new_scale = self.ramp.complete_pass(
                accuracy, old_scale, tempo_mode=self.config.mode == "Tempo"
            )
            self.transport.set_scale(new_scale, now)
            banner = (
                f"Three clean passes! Tempo +5% → {new_scale:.0%}" if new_scale > old_scale else ""
            )
            if self.config.loop:
                self.restart(now, count_in=False)
            else:
                self.transport.pause(now, checkpoint=self.end)
                self.release_requested = True
            self.status = banner or f"Pass complete • {accuracy:.0%} • tempo {new_scale:.0%}"
