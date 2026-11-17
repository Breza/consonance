"""Spelling and exact-duration score vocabulary, independent of rendering."""

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Literal

type Step = Literal["C", "D", "E", "F", "G", "A", "B"]
type Alter = Literal[-1, 0, 1]
STEPS: tuple[Step, ...] = ("C", "D", "E", "F", "G", "A", "B")
SEMITONES = (0, 2, 4, 5, 7, 9, 11)
MIDDLE_C = 60
PIANO_LOW = 21
PIANO_HIGH = 108
BLACK_PITCH_CLASSES = frozenset({1, 3, 6, 8, 10})
_SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")


class MidiPitch(int):
    """A MIDI note number that is guaranteed to exist on an 88-key piano."""

    def __new__(cls, value: int) -> "MidiPitch":
        """Construct a validated piano MIDI pitch."""
        if not PIANO_LOW <= value <= PIANO_HIGH:
            raise ValueError("Piano pitch must be in 21..108 (A0..C8)")
        return super().__new__(cls, value)


class Clef(StrEnum):
    """The two staves of a grand staff."""

    TREBLE = "treble"
    BASS = "bass"


class Hand(StrEnum):
    """Which hand a note belongs to."""

    RIGHT = "rh"
    LEFT = "lh"


@dataclass(frozen=True)
class NotatedPitch:
    """A spelled pitch: letter, accidental, and octave (C4 is middle C)."""

    step: Step
    alter: Alter
    octave: int

    def __post_init__(self) -> None:
        """Reject spellings outside single accidentals and the piano's range."""
        if self.step not in STEPS or self.alter not in (-1, 0, 1):
            raise ValueError("Only single-sharp, single-flat and natural pitches are supported")
        MidiPitch(self.midi)

    @property
    def midi(self) -> MidiPitch:
        """Return the sounding MIDI note number."""
        return MidiPitch(12 * (self.octave + 1) + SEMITONES[STEPS.index(self.step)] + self.alter)

    @property
    def diatonic(self) -> int:
        """Return the letter-name position counted in staff steps (C0 is 0)."""
        return self.octave * 7 + STEPS.index(self.step)

    def __str__(self) -> str:
        """Return the score-source spelling, such as F#4 or Bb3."""
        return f"{self.step}{ {-1: 'b', 0: '', 1: '#'}[self.alter] }{self.octave}"


@dataclass(frozen=True)
class KeySignature:
    """A key signature of up to two sharps (positive) or two flats (negative)."""

    fifths: int = 0

    def __post_init__(self) -> None:
        """Reject key signatures outside the supported range."""
        if self.fifths not in (-2, -1, 0, 1, 2):
            raise ValueError("Supported keys: C, G, D, F, Bb and their relative minors")

    def alteration(self, step: Step) -> int:
        """Return the accidental (-1, 0, 1) this key applies to a letter name."""
        if self.fifths > 0 and step in ("F", "C")[: self.fifths]:
            return 1
        if self.fifths < 0 and step in ("B", "E")[: -self.fifths]:
            return -1
        return 0

    @property
    def prefers_flats(self) -> bool:
        """Report whether black keys are conventionally spelled as flats in this key."""
        return self.fifths < 0


@dataclass(frozen=True)
class TimeSignature:
    """A simple quarter-note meter: 2/4, 3/4, or 4/4."""

    numerator: int = 4
    denominator: int = 4

    def __post_init__(self) -> None:
        """Reject meters the notation and transport do not model."""
        if self.numerator not in (2, 3, 4) or self.denominator != 4:
            raise ValueError("Only 2/4, 3/4 and 4/4 are supported")

    @property
    def beats(self) -> Fraction:
        """Return the number of quarter-note beats in one measure."""
        return Fraction(self.numerator)


class MeasureAccidentalState:
    """Track which accidentals must be drawn as a measure is read left to right."""

    def __init__(self, key: KeySignature = KeySignature()) -> None:
        """Start a measure in which only the key signature is in force."""
        self.key = key
        self._state: dict[tuple[Step, int], int] = {}

    def display(self, pitch: NotatedPitch) -> str | None:
        """Return the accidental glyph name to draw for a pitch, or None if implied."""
        slot = (pitch.step, pitch.octave)
        previous = self._state.get(slot, self.key.alteration(pitch.step))
        self._state[slot] = pitch.alter
        if previous == pitch.alter:
            return None
        return {-1: "Flat", 0: "Natural", 1: "Sharp"}[pitch.alter]


@dataclass(frozen=True)
class NotatedAtom:
    """One rhythmic event in a hand: a note, a chord, or (with no pitches) a rest."""

    pitches: tuple[NotatedPitch, ...]
    duration: Fraction = Fraction(1)
    fingering: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Reject durations the layout cannot draw and mismatched fingerings."""
        if self.duration not in map(Fraction, (4, 3, 2, 1.5, 1, 0.5)):
            raise ValueError("Unsupported notated duration")
        if self.fingering and (
            len(self.fingering) != len(self.pitches)
            or any(f not in range(1, 6) for f in self.fingering)
        ):
            raise ValueError("Provide one fingering (1..5) per pitch")


@dataclass(frozen=True)
class Measure:
    """One complete measure for both hands."""

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


def pitch_class_name(pitch_class: int, *, flats: bool = False, both: bool = False) -> str:
    """Name a pitch class; black keys can show both spellings, e.g. ``C# / Db``."""
    index = pitch_class % 12
    if both and index in BLACK_PITCH_CLASSES:
        return f"{_SHARP_NAMES[index]} / {_FLAT_NAMES[index]}"
    return (_FLAT_NAMES if flats else _SHARP_NAMES)[index]


def pitch_name(midi: int, *, flats: bool = False) -> str:
    """Name a MIDI note for display, e.g. 60 -> C4 and 66 -> F#4 (or Gb4)."""
    return f"{pitch_class_name(midi, flats=flats)}{midi // 12 - 1}"


def is_black_key(midi: int) -> bool:
    """Report whether a MIDI note is one of the piano's black keys."""
    return midi % 12 in BLACK_PITCH_CLASSES
