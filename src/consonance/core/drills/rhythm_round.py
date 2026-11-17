"""Rhythm Sniper: tap a two-bar rhythm against the click and have every attack graded."""

import json
from collections.abc import Sequence
from fractions import Fraction

from consonance.core.curriculum import CurriculumItem
from consonance.core.drills.base import (
    Actions,
    Drill,
    DrillView,
    Host,
    PracticeResult,
    Prompt,
    Pulse,
)
from consonance.core.input_and_grading import HoldRelease, MidiEvent, NoteOn
from consonance.core.notation import NotatedAtom, TimeSignature
from consonance.core.notation_layout import StaffLayout, group_measures, layout_measures
from consonance.core.prompt_queue import PromptQueue
from consonance.core.rhythm import (
    WINDOW_MS,
    DurationGrade,
    ExpectedStrike,
    Grade,
    TimedGrader,
    describe_attack,
    mark_for,
)

EARLY = 0.2  # seconds before the first note in which a tap already counts


class RhythmDrill(Drill):
    """One round is a one-bar count-in followed by the item's rhythm played twice."""

    scene = "rhythm"
    instruction = (
        "Read the rhythm, press Play, and after the one-bar count-in tap it on any key. "
        "Hold each note for its full length."
    )

    def __init__(self, host: Host, items: Sequence[CurriculumItem], title: str = "") -> None:
        """Create the drill showing its first rhythm, ready to be read."""
        super().__init__(host)
        self.items = tuple(items)
        self.set_title = title
        self.queue = PromptQueue(len(self.items))
        self.grader: TimedGrader | None = None
        self.rounds = 0
        self.best_accuracy = 0.0
        self._atoms: tuple[NotatedAtom, ...] = ()
        self._time = TimeSignature()
        self._layout: StaffLayout | None = None
        self._beat = 0.0
        self._count_start = 0.0
        self._start = 0.0
        self._end = 0.0
        self._played: list[int] = []
        self._velocities: list[int] = []
        self._prepare()

    @property
    def item(self) -> CurriculumItem:
        """Return the rhythm currently on the stand."""
        return self.items[self.queue.current]

    @property
    def prompt(self) -> Prompt:
        """Return the current rhythm as a prompt."""
        item = self.item
        return Prompt(item.item_id, item.atoms(), time=item.time, title=item.title)

    @property
    def engaged(self) -> bool:
        """A round runs on the clock from count-in to final note."""
        return self.running

    def _prepare(self) -> None:
        """Write out the current rhythm so it can be read before the round starts."""
        item = self.item
        self._time = item.time
        self._atoms = item.atoms() * 2
        rest = (NotatedAtom((), Fraction(self._time.beats)),)
        measures = tuple((bar, rest) for bar in group_measures(self._atoms, self._time))
        self._layout = layout_measures(measures, time=self._time)
        self.grader = None
        self.status = f"{item.title} • read it through, then press Play"

    def play(self, now: float) -> None:
        """Start a round: one bar of clicks, then the rhythm twice."""
        if self.running:
            self.abandon(now)
        self.host.silence()
        settings = self.host.settings
        self._beat = 60 / settings.tempo_bpm
        bar = self._time.numerator
        self._count_start = now
        self._start = now + bar * self._beat
        strikes: list[ExpectedStrike] = []
        beat = 0.0
        for atom in self._atoms:
            length = float(atom.duration)
            if atom.pitches:
                strikes.append(
                    ExpectedStrike(60, self._start + beat * self._beat, length * self._beat)
                )
            beat += length
        offset = settings.midi_judge_offset_ms
        self.grader = TimedGrader(tuple(strikes), offset, any_pitch=True)
        self._end = (
            max(
                n.at
                + max(n.duration + max(0.12, 0.30 * n.duration), WINDOW_MS / 1000 + offset / 1000)
                for n in strikes
            )
            + 0.001
        )
        self._played, self._velocities = [], []
        for i in range(bar * 3):
            self.host.click(now + i * self._beat, i % bar == 0)
        self.running = True
        self.status = "Count-in… come in on the next bar"

    def skip(self, now: float) -> None:
        """Put the next rhythm of the set on the stand, without starting it."""
        self.abandon(now)
        self.running = False
        self.host.silence()
        self.queue.advance()
        self._prepare()

    def midi(self, event: MidiEvent, actions: Actions, now: float) -> None:
        """Grade a tap against the nearest expected note, and a release against its length."""
        grader = self.grader
        if not self.running or grader is None:
            return
        if isinstance(event, NoteOn) and event.timestamp >= self._start - EARLY:
            hit = grader.strike(event.pitch, event.timestamp)
            self._played.append(int(event.pitch))
            self._velocities.append(event.velocity)
            self.status = describe_attack(hit.grade, hit.error_ms)
            good = hit.grade in (Grade.PERFECT, Grade.GOOD)
            self.host.flash("good" if good else "bad", event.timestamp)
        for action in actions:
            if isinstance(action, HoldRelease):
                grader.release(action.pitch, action.started, action.ended)

    def tick(self, now: float) -> None:
        """Close the windows of notes that were never tapped and end the round on time."""
        if self.running and self.grader is not None:
            self.grader.advance_to(now)
            if now >= self._end:
                self._finish(now)

    def _finish(self, now: float) -> None:
        """Summarise the round, log it, and stop."""
        grader = self.grader
        assert grader is not None
        struck = [i for i, hit in grader.hits.items() if hit.grade != Grade.MISS]
        for i in struck:
            grader.holds.setdefault(i, DurationGrade.LONG)  # still held when the round ended
        missed = len(grader.hits) - len(struck)
        lengths_ok = sum(grader.holds[i] == DurationGrade.OK for i in struck)
        accuracy = grader.accuracy
        clean = accuracy >= 0.9 and not missed and lengths_ok == len(struck)
        settings = self.host.settings
        details = {
            "hit_accuracy": accuracy,
            "jitter_ms": grader.jitter_ms,
            "tempo_bpm": settings.tempo_bpm,
            "stray_count": len(grader.strays),
            "attacks": [
                {
                    "pitch": grader.hits[i].pitch,
                    "duration_s": note.duration,
                    "grade": grader.hits[i].grade.value,
                    "error_ms": grader.hits[i].error_ms,
                    "hold_ms": grader.hold_ms.get(i),
                    "hold_grade": grader.holds[i].value if i in grader.holds else None,
                }
                for i, note in enumerate(grader.expected)
            ],
        }
        self.host.record(
            PracticeResult(
                self.item.item_id,
                (60,) * len(grader.expected),
                tuple(self._played),
                clean,
                None,
                None,
                tuple(self._velocities),
                grader.mean_error_ms,
                json.dumps(details),
            )
        )
        mean = grader.mean_error_ms
        lean = "early" if mean < 0 else "late"
        self.status = (
            f"{accuracy:.0%} on the beat • average {abs(mean):.0f} ms {lean}"
            f" • steadiness ±{grader.jitter_ms:.0f} ms"
            f" • {lengths_ok} of {len(grader.expected)} note lengths right"
        )
        if clean and grader.jitter_ms <= 35 and settings.tempo_bpm >= 60:
            self.status += " • fluent"
        self.rounds += 1
        self.best_accuracy = max(self.best_accuracy, accuracy)
        self.running = False
        self.host.silence()
        self.host.flash("good" if clean else "ok", now)

    def abandon(self, now: float) -> None:
        """Log a round that was stopped after tapping began; it is never held against you."""
        grader = self.grader
        if self.running and grader is not None:
            if self._played:
                details = {"incomplete": True, "blameless": True, "hit_accuracy": grader.accuracy}
                self.host.record(
                    PracticeResult(
                        self.item.item_id,
                        tuple(n.pitch for n in grader.expected),
                        tuple(self._played),
                        False,
                        None,
                        None,
                        tuple(self._velocities),
                        grader.mean_error_ms,
                        json.dumps(details),
                    )
                )
            self.grader = None

    def view(self, now: float) -> DrillView:
        """Show the rhythm, each note's grade so far, the playhead, and the beat."""
        bar = self._time.numerator
        grader = self.grader
        marks = (
            tuple((0, i, mark_for(hit.grade)) for i, hit in grader.hits.items()) if grader else ()
        )
        playhead = None
        pulse = None
        speed = 0.0
        if self.running and self._beat:
            speed = 1 / self._beat
            if now < self._start:
                pulse = Pulse(bar, (now - self._count_start) / self._beat, True)
            else:
                position = (now - self._start) / self._beat
                playhead = min(position, 2.0 * bar)
                pulse = Pulse(bar, position % bar)
        chips = [f"{self.host.settings.tempo_bpm} BPM"]
        if self.rounds:
            chips.append(f"{self.rounds} rounds")
            chips.append(f"best {self.best_accuracy:.0%}")
        if len(self.items) > 1:
            chips.append(f"rhythm {self.queue.current + 1} of {len(self.items)}")
        return DrillView(
            layout=self._layout,
            marks=marks,
            playhead=playhead,
            title=self.item.title,
            instruction=self.instruction,
            chips=tuple(chips),
            pulse=pulse,
            beat=playhead or 0.0,
            beats_per_second=speed,
        )
