"""Game-style practice: a reading sprint against the clock and a growing melody to echo."""

import json
import random
from collections.abc import Sequence

from consonance.core.curriculum import UNITS, CurriculumItem
from consonance.core.drills.base import (
    Actions,
    Drill,
    DrillView,
    GameState,
    Host,
    PracticeResult,
    Prompt,
)
from consonance.core.drills.sequence import SightDrill
from consonance.core.input_and_grading import MidiEvent, NoteOn
from consonance.core.midi_output import OutputNote
from consonance.core.notation import NotatedAtom, natural

RUSH_LEVELS = (
    ("Landmarks • 4 notes", (1,)),
    ("C positions • 11 notes", (1, 2)),
    ("Full range C2 to C6 • 28 notes", (1, 2, 6)),
)
ECHO_LEVELS = (
    ("Three keys • C E G", ("C4", "E4", "G4")),
    ("Five keys • C to G", ("C4", "D4", "E4", "F4", "G4")),
    ("Eight keys • C major scale", ("C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5")),
)


def rush_pool(level: int) -> tuple[CurriculumItem, ...]:
    """Return the single-note reading items a Note Rush level draws from."""
    units = RUSH_LEVELS[max(0, min(level, len(RUSH_LEVELS) - 1))][1]
    return tuple(
        item
        for unit in UNITS
        if unit.number in units
        for item in unit.items
        if item.mode == "sight" and item.kind == "note"
    )


class RushDrill(SightDrill):
    """Note Rush: read as many notes as possible before the clock runs out.

    Every note answered is logged against that note's own curriculum item, so a game also
    counts as real reading practice; the final score is kept as a personal best.
    """

    scene = "rush"
    instruction = "Sixty seconds on the clock. Play each note as fast as you can read it."
    duration = 60.0

    def __init__(
        self, host: Host, items: Sequence[CurriculumItem], title: str = "", level: int = 0
    ) -> None:
        """Create a game that is waiting for Play."""
        self.level = level
        self.score = 0
        self.over = False
        self._ends = 0.0
        super().__init__(host, items, title)
        self.status = "Press Play to start the clock"

    @property
    def best_key(self) -> str:
        """Return the key under which this level's best score is stored."""
        return f"rush:{self.level}"

    @property
    def engaged(self) -> bool:
        """The clock runs for the whole game."""
        return self.running

    def play(self, now: float) -> None:
        """Start a fresh game."""
        if self.running:
            self.abandon(now)
        self.score = self.answered = self.clean_count = self.streak = self.best_streak = 0
        self._cleared.clear()
        self.over = False
        self._ends = now + self.duration
        self.host.silence()
        self._advance()
        self._activate(now)
        self.status = "Go!"

    def replay(self, now: float) -> None:
        """Start the game over."""
        self.play(now)

    def skip(self, now: float) -> None:
        """Give up on the current note; it costs only the time already spent."""
        if self.running:
            super().skip(now)

    def pause(self, now: float) -> None:
        """Stop the game early without keeping a score."""
        if self.running:
            self.abandon(now)
            self.running = False
            self.over = True
            self.host.silence()
            self.status = "Game stopped • press Play for a fresh sixty seconds"

    def on_complete(self, now: float, clean: bool) -> None:
        """Score a point for every note read cleanly at the first attempt."""
        if clean:
            self.score += 1

    def tick(self, now: float) -> None:
        """End the game when time is up."""
        if self.running and now >= self._ends:
            self.abandon(now)
            self.running = False
            self.over = True
            self.host.silence()
            improved = self.host.new_best(self.best_key, self.score)
            details = {"game": True, "score": self.score, "answered": self.answered}
            self.host.record(
                PracticeResult(
                    self.best_key, (), (), True, None, None, (), details=json.dumps(details)
                )
            )
            best = int(self.host.bests.get(self.best_key, self.score))
            record = "a new personal best!" if improved else f"your best is {best}"
            self.status = f"Time! {self.score} notes read cleanly • {record}"
            self.host.flash("good", now)

    def view(self, now: float) -> DrillView:
        """Add the score, the best score, and the time remaining."""
        base = super().view(now)
        left = max(0.0, self._ends - now) if self.running else (0.0 if self.over else self.duration)
        best = int(self.host.bests.get(self.best_key, 0))
        return DrillView(
            layout=base.layout,
            expected=base.expected,
            marks=base.marks,
            prompt_index=base.prompt_index,
            title=RUSH_LEVELS[self.level][0] if self.level < len(RUSH_LEVELS) else base.title,
            instruction=self.instruction,
            chips=(f"score {self.score}", f"best {best}", f"clean run {self.streak}"),
            reveal=base.reveal,
            game=GameState(self.score, best, None, left, self.over),
            progress=left / self.duration,
            assisted=base.assisted,
        )


class EchoDrill(Drill):
    """Melody Echo: the piano plays a melody, you play it back, and it grows by one note.

    A wrong key costs one of three lives and the melody is played again. The game ends when
    the lives run out; the longest melody echoed is the score.
    """

    scene = "echo"
    instruction = (
        "Listen to the piano, then echo the melody from memory. It grows by one note each round."
    )
    step = 0.6
    length = 0.48
    gap = 0.9

    def __init__(self, host: Host, level: int = 1, show_call: bool = True) -> None:
        """Create a game that is waiting for Play."""
        super().__init__(host)
        self.level = max(0, min(level, len(ECHO_LEVELS) - 1))
        self.show_call = show_call
        self.pool = tuple(int(natural(name).midi) for name in ECHO_LEVELS[self.level][1])
        self.sequence: list[int] = []
        self.position = 0
        self.lives = 3
        self.longest = 0
        self.over = False
        self._random = host.rng or random.Random(0)
        self._call: list[tuple[int, float, float]] = []
        self._listen_at = 0.0
        self._next_call: float | None = None
        self._now = 0.0
        self.status = "Press Play • the piano plays first, then you echo"

    @property
    def best_key(self) -> str:
        """Return the key under which this level's best score is stored."""
        return f"echo:{self.level}"

    @property
    def prompt(self) -> Prompt:
        """Return the melody so far as single notes."""
        atoms = tuple(NotatedAtom((natural(_name(p)),)) for p in self.sequence)
        return Prompt(self.best_key, atoms, title=ECHO_LEVELS[self.level][0])

    @property
    def engaged(self) -> bool:
        """The piano's turn runs on the clock."""
        return self.running and self._now < self._listen_at

    @property
    def listening(self) -> bool:
        """Report whether it is the player's turn."""
        return self.running and self._next_call is None and self._now >= self._listen_at

    def _start_call(self, at: float) -> None:
        """Have the piano play the melody from its first note."""
        self.host.silence()
        channel = self.host.settings.piano_channel
        self._call = []
        for i, pitch in enumerate(self.sequence):
            start = at + i * self.step
            self.host.play(OutputNote(start, pitch, self.length, channel=channel))
            self._call.append((pitch, start, start + self.length))
        self._listen_at = at + len(self.sequence) * self.step - (self.step - self.length)
        self._next_call = None
        self.position = 0
        self.status = "Listen…"

    def play(self, now: float) -> None:
        """Start a new game with a one-note melody."""
        self.sequence = [self._random.choice(self.pool)]
        self.lives = 3
        self.longest = 0
        self.over = False
        self.running = True
        self._now = now
        self._start_call(now + 0.3)

    def replay(self, now: float) -> None:
        """Hear the melody again from the start, at no cost."""
        if self.running:
            self._start_call(now)
        else:
            self.play(now)

    def pause(self, now: float) -> None:
        """End the game now and keep the score reached so far."""
        if self.running:
            self._finish(now)

    def midi(self, event: MidiEvent, actions: Actions, now: float) -> None:
        """Compare each key with the next note of the melody."""
        if not self.running or not isinstance(event, NoteOn):
            return
        if self._next_call is not None or event.timestamp < self._listen_at - 0.05:
            return
        if int(event.pitch) == self.sequence[self.position]:
            self.position += 1
            self.host.flash("good", event.timestamp)
            self.status = f"Your turn • {self.position} of {len(self.sequence)}"
            if self.position == len(self.sequence):
                self.longest = len(self.sequence)
                self.sequence.append(self._random.choice(self.pool))
                self._next_call = event.timestamp + self.gap
                self.status = f"Echoed {self.longest}! Now {self.longest + 1} notes"
            return
        self.lives -= 1
        self.host.flash("bad", event.timestamp)
        if self.lives <= 0:
            self._finish(event.timestamp)
            return
        plural = "life" if self.lives == 1 else "lives"
        self.status = f"Not quite • listen again ({self.lives} {plural} left)"
        self._next_call = event.timestamp + self.gap

    def tick(self, now: float) -> None:
        """Start the piano's next turn when its moment arrives."""
        self._now = now
        if self.running and self._next_call is not None and now >= self._next_call:
            self._start_call(now)

    def _finish(self, now: float) -> None:
        """End the game, keep a personal best, and log the result."""
        self.running = False
        self.over = True
        self._next_call = None
        self.host.silence()
        improved = self.longest > 0 and self.host.new_best(self.best_key, self.longest)
        if self.longest > 0:
            details = {"game": True, "length": self.longest}
            self.host.record(
                PracticeResult(
                    self.best_key,
                    tuple(self.sequence[: self.longest]),
                    (),
                    True,
                    None,
                    None,
                    (),
                    details=json.dumps(details),
                )
            )
        best = int(self.host.bests.get(self.best_key, self.longest))
        record = "a new personal best!" if improved else f"your best is {best}"
        self.status = f"Game over • you echoed {self.longest} notes • {record}"

    def view(self, now: float) -> DrillView:
        """Light the piano's notes during its turn and show whose turn it is."""
        calling = [pitch for pitch, start, end in self._call if start <= now < end]
        if self.over:
            text = f"You echoed {self.longest} notes"
        elif not self.running:
            text = "Press Play to begin"
        elif self.listening:
            text = f"Your turn • {self.position} of {len(self.sequence)}"
        else:
            text = "Listen…"
        expected = (
            frozenset({self.sequence[self.position]})
            if self.listening and self.position < len(self.sequence)
            else frozenset()
        )
        best = int(self.host.bests.get(self.best_key, 0))
        return DrillView(
            expected=expected,
            title=ECHO_LEVELS[self.level][0],
            instruction=self.instruction,
            prompt_text=text,
            chips=(f"melody of {len(self.sequence) or 1}", f"best {best}"),
            lit=frozenset(calling) if self.show_call else frozenset(),
            game=GameState(self.longest, best, self.lives, None, self.over),
        )


def _name(pitch: int) -> str:
    """Spell a white-key MIDI pitch in the score-source language."""
    return f"{'C D EF G A B'[pitch % 12]}{pitch // 12 - 1}"
