"""Spelling and exact-duration score vocabulary, independent of rendering."""

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Literal

type Step = Literal["C", "D", "E", "F", "G", "A", "B"]
type Alter = Literal[-1, 0, 1]
STEPS: tuple[Step, ...] = ("C", "D", "E", "F", "G", "A", "B")
SEMITONES = (0, 2, 4, 5, 7, 9, 11)


class MidiPitch(int):
    def __new__(cls, value: int) -> "MidiPitch":
        if not 21 <= value <= 108:
            raise ValueError("Piano pitch must be in 21..108 (A0..C8)")
        return super().__new__(cls, value)


class Clef(StrEnum):
    TREBLE = "treble"
    BASS = "bass"


class Hand(StrEnum):
    RIGHT = "rh"
    LEFT = "lh"


@dataclass(frozen=True)
class NotatedPitch:
    step: Step
    alter: Alter
    octave: int

    def __post_init__(self) -> None:
        if self.step not in STEPS or self.alter not in (-1, 0, 1):
            raise ValueError("Only single-sharp, single-flat and natural pitches are supported")
        MidiPitch(self.midi)

    @property
    def midi(self) -> MidiPitch:
        return MidiPitch(12 * (self.octave + 1) + SEMITONES[STEPS.index(self.step)] + self.alter)

    @property
    def diatonic(self) -> int:
        return self.octave * 7 + STEPS.index(self.step)

    def __str__(self) -> str:
        return f"{self.step}{ {-1: 'b', 0: '', 1: '#'}[self.alter] }{self.octave}"


@dataclass(frozen=True)
class KeySignature:
    fifths: int = 0

    def __post_init__(self) -> None:
        if self.fifths not in (-2, -1, 0, 1, 2):
            raise ValueError("Supported keys: C, G, D, F, Bb and their relative minors")

    def alteration(self, step: Step) -> int:
        if self.fifths > 0 and step in ("F", "C")[: self.fifths]:
            return 1
        if self.fifths < 0 and step in ("B", "E")[: -self.fifths]:
            return -1
        return 0


@dataclass(frozen=True)
class TimeSignature:
    numerator: int = 4
    denominator: int = 4

    def __post_init__(self) -> None:
        if self.numerator not in (2, 3, 4) or self.denominator != 4:
            raise ValueError("Only 2/4, 3/4 and 4/4 are supported")

    @property
    def beats(self) -> Fraction:
        return Fraction(self.numerator)


class MeasureAccidentalState:
    def __init__(self, key: KeySignature = KeySignature()) -> None:
        self.key = key
        self._state: dict[tuple[Step, int], int] = {}

    def display(self, pitch: NotatedPitch) -> str | None:
        slot = (pitch.step, pitch.octave)
        previous = self._state.get(slot, self.key.alteration(pitch.step))
        self._state[slot] = pitch.alter
        if previous == pitch.alter:
            return None
        return {-1: "Flat", 0: "Natural", 1: "Sharp"}[pitch.alter]


@dataclass(frozen=True)
class NotatedAtom:
    pitches: tuple[NotatedPitch, ...]
    duration: Fraction = Fraction(1)
    fingering: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.duration not in map(Fraction, (4, 3, 2, 1.5, 1, 0.5)):
            raise ValueError("Unsupported notated duration")
        if self.fingering and (
            len(self.fingering) != len(self.pitches)
            or any(f not in range(1, 6) for f in self.fingering)
        ):
            raise ValueError("Provide one fingering (1..5) per pitch")


@dataclass(frozen=True)
class Measure:
    right: tuple[NotatedAtom, ...]
    left: tuple[NotatedAtom, ...]


def natural(name: str) -> NotatedPitch:
    """Parse our small score-source spelling language, e.g. C4, F#4, Bb3."""
    if not name or name[0] not in STEPS:
        raise ValueError(f"Invalid spelling: {name}")
    step = STEPS["CDEFGAB".index(name[0])]
    alter: Alter = 0
    tail = name[1:]
    if tail.startswith(("#", "b")):
        alter = 1 if tail[0] == "#" else -1
        tail = tail[1:]
    return NotatedPitch(step, alter, int(tail))
