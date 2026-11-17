"""Shared vocabulary for practice drills: what they need from the engine and what they show."""

import random
from dataclasses import dataclass
from typing import Protocol

from consonance.core.input_and_grading import (
    HoldRelease,
    MidiEvent,
    PianoStateTracker,
    SoftPedalTap,
    UntimedEvaluator,
)
from consonance.core.midi_output import OutputNote, Settings
from consonance.core.notation import Clef, KeySignature, NotatedAtom, TimeSignature
from consonance.core.notation_layout import StaffLayout

type Actions = tuple[HoldRelease | SoftPedalTap, ...]
type Marks = tuple[tuple[int, int, str], ...]


@dataclass(frozen=True)
class Prompt:
    """One thing the player is currently being asked to play."""

    item_id: str
    atoms: tuple[NotatedAtom, ...]
    clef: Clef = Clef.TREBLE
    key: KeySignature = KeySignature()
    time: TimeSignature = TimeSignature()
    title: str = ""
    text: str = ""
    answer: str = ""


@dataclass(frozen=True)
class PracticeResult:
    """A finished or abandoned prompt, ready to be written to the attempt log."""

    item_id: str
    expected: tuple[int, ...]
    played: tuple[int, ...]
    first_try: bool
    response_ms: float | None
    spread_ms: float | None
    velocities: tuple[int, ...]
    timing_error_ms: float | None = None
    details: str = "{}"
    mode: str = ""


@dataclass(frozen=True)
class Pulse:
    """Where the beat is: enough to draw a count-in and a visual metronome."""

    beats: int
    position: float
    count_in: bool = False


@dataclass(frozen=True)
class GameState:
    """The scoreboard of a game-style drill."""

    score: int = 0
    best: int = 0
    lives: int | None = None
    time_left: float | None = None
    over: bool = False


@dataclass(frozen=True)
class DrillView:
    """Everything a drill contributes to one rendered frame."""

    layout: StaffLayout | None = None
    expected: frozenset[int] = frozenset()
    allowed: frozenset[int] = frozenset()
    marks: Marks = ()
    playhead: float | None = None
    scrolling: bool = False
    prompt_index: int = 0
    title: str = ""
    instruction: str = ""
    prompt_text: str = ""
    chips: tuple[str, ...] = ()
    pulse: Pulse | None = None
    reveal: bool = False
    lit: frozenset[int] = frozenset()
    graph: tuple[float, ...] = ()
    velocity_graph: tuple[float, ...] = ()
    game: GameState | None = None
    tempo_scale: float = 1.0
    beat: float = 0.0
    beats_per_second: float = 0.0
    progress: float | None = None
    fingering: str = "starts"
    assisted: bool = False


class Host(Protocol):
    """The services a drill may use; the practice engine provides them."""

    piano: PianoStateTracker
    settings: Settings
    rng: random.Random | None
    bests: dict[str, float]

    def play(self, note: OutputNote) -> None:
        """Schedule a note for the piano to sound."""

    def click(self, at: float, downbeat: bool) -> None:
        """Schedule a metronome click, if the metronome is on."""

    def silence(self) -> None:
        """Release every note the computer is sounding and drop anything still queued."""

    def record(self, result: PracticeResult) -> None:
        """Hand a result to the attempt log."""

    def flash(self, kind: str, now: float) -> None:
        """Signal brief ``good``, ``ok`` or ``bad`` feedback for the views."""

    def new_best(self, key: str, value: float) -> bool:
        """Offer a score as a personal best; return True if it beats the stored one."""


class Drill:
    """Base behaviour shared by every practice mode."""

    scene = ""
    instruction = ""

    def __init__(self, host: Host) -> None:
        """Create an idle drill bound to its host."""
        self.host = host
        self.running = False
        self.status = "Press Play to begin"

    @property
    def engaged(self) -> bool:
        """Report whether something timed is under way, so practice time should accrue."""
        return False

    @property
    def evaluator(self) -> UntimedEvaluator | None:
        """Return the untimed evaluator currently listening, if this drill uses one."""
        return None

    @property
    def prompt(self) -> Prompt:
        """Return the current prompt."""
        raise NotImplementedError

    def play(self, now: float) -> None:
        """Start, or continue to the next prompt."""

    def pause(self, now: float) -> None:
        """Stop for now, keeping whatever can be resumed."""
        self.abandon(now)
        self.running = False
        self.host.silence()
        self.status = "Paused • every completed attempt is saved"

    def replay(self, now: float) -> None:
        """Present the current prompt again."""
        self.play(now)

    def skip(self, now: float) -> None:
        """Move on to the next prompt."""

    def hint(self, now: float) -> None:
        """Reveal the answer to the current prompt."""

    def midi(self, event: MidiEvent, actions: Actions, now: float) -> None:
        """Apply one input event that has already updated the piano state."""

    def tick(self, now: float) -> None:
        """Advance anything that depends on the clock."""

    def abandon(self, now: float) -> None:
        """Leave the current prompt, logging it as incomplete if it had been started."""

    def view(self, now: float) -> DrillView:
        """Describe what the views should show right now."""
        return DrillView()
