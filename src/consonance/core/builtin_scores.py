"""Six elementary arrangements. All hand measures are complete, exact rational scores.

Traditional melodies are public domain; the other three pieces are original to Consonance.
These deliberately short teaching arrangements are the source of both notation and MIDI.
"""

from dataclasses import dataclass
from fractions import Fraction

from consonance.core.notation import (
    Hand,
    KeySignature,
    Measure,
    NotatedAtom,
    TimeSignature,
    natural,
)
from consonance.core.song import SongNote, SongTimeline
from consonance.core.transport import TempoMap, TempoPoint


@dataclass(frozen=True)
class BuiltinScore:
    song_id: str
    title: str
    time: TimeSignature
    key: KeySignature
    bpm: int
    measures: tuple[Measure, ...]
    description: str

    def validate(self) -> None:
        for number, measure in enumerate(self.measures, 1):
            for atoms in (measure.right, measure.left):
                if sum((a.duration for a in atoms), Fraction()) != self.time.beats:
                    raise ValueError(f"{self.title}, measure {number}: incomplete hand measure")
                for atom in atoms:
                    if len(set(p.midi for p in atom.pitches)) != len(atom.pitches):
                        raise ValueError("Duplicate pitch within chord")
                    if any(not 36 <= p.midi <= 84 for p in atom.pitches):
                        raise ValueError("Score exceeds C2..C6 sight-reading range")
                    if atom.pitches and not atom.fingering:
                        raise ValueError("Built-in notes require starter fingerings")

    def compile(self) -> SongTimeline:
        self.validate()
        notes: list[SongNote] = []
        for number, measure in enumerate(self.measures):
            for hand, atoms in ((Hand.RIGHT, measure.right), (Hand.LEFT, measure.left)):
                beat = number * self.time.beats
                for atom in atoms:
                    notes.extend(SongNote(p.midi, beat, atom.duration, hand) for p in atom.pitches)
                    beat += atom.duration
        return SongTimeline(
            self.song_id,
            self.title,
            tuple(sorted(notes, key=lambda n: (n.start_beat, n.hand, n.pitch))),
            TempoMap((TempoPoint(0, self.bpm),)),
            self.time,
        )


def _bar(source: str, *, left: bool = False) -> tuple[NotatedAtom, ...]:
    atoms: list[NotatedAtom] = []
    for token in source.split():
        spelling, duration = token.split(":")
        pitches = () if spelling == "r" else tuple(natural(p) for p in spelling.split("+"))
        fingers = tuple((5 - i if left else 1 + i) for i in range(len(pitches)))
        # Starter melodic fingering follows the C/D five-finger positions when possible.
        if len(pitches) == 1:
            index = "CDEFGAB".index(pitches[0].step)
            fingers = (max(1, min(5, 5 - index if left else index + 1)),)
        atoms.append(NotatedAtom(pitches, Fraction(duration), fingers))
    return tuple(atoms)


def _score(
    sid: str,
    title: str,
    beats: int,
    key: int,
    bpm: int,
    right: tuple[str, ...],
    left: tuple[str, ...],
    description: str,
) -> BuiltinScore:
    if len(right) != len(left):
        raise ValueError("Both hands require the same number of measures")
    score = BuiltinScore(
        sid,
        title,
        TimeSignature(beats),
        KeySignature(key),
        bpm,
        tuple(Measure(_bar(rh), _bar(lh, left=True)) for rh, lh in zip(right, left, strict=True)),
        description,
    )
    score.validate()
    return score


BUILTIN_SCORES = (
    _score(
        "landmark_waltz",
        "Landmark Anchor Waltz",
        3,
        0,
        66,
        (
            "G4:2 C4:1",
            "G4:3",
            "C4:1 E4:1 G4:1",
            "E4:3",
            "G4:2 E4:1",
            "F4:2 D4:1",
            "E4:1 D4:1 C4:1",
            "C4:3",
        ),
        ("C3:3", "G2:3", "C3:3", "C3:3", "C3:3", "F3:3", "G2:3", "C3:3"),
        "Original • landmarks and long left-hand anchors",
    ),
    _score(
        "stepping_stones",
        "Stepping Stones",
        4,
        0,
        72,
        (
            "C4:1 D4:1 E4:1 F4:1",
            "G4:2 E4:2",
            "F4:1 E4:1 D4:1 C4:1",
            "D4:2 C4:2",
            "E4:1 F4:1 G4:1 E4:1",
            "F4:2 D4:2",
            "E4:1 D4:1 C4:2",
            "C4:4",
        ),
        ("C3:4", "G3:4", "F3:4", "C3:4", "C3:4", "F3:4", "G2:4", "C3:4"),
        "Original • stepwise five-finger reading",
    ),
    _score(
        "au_clair",
        "Au Clair de la Lune",
        4,
        0,
        76,
        (
            "C4:1 C4:1 C4:1 D4:1",
            "E4:2 D4:2",
            "C4:1 E4:1 D4:1 D4:1",
            "C4:4",
            "C4:1 C4:1 C4:1 D4:1",
            "E4:2 D4:2",
            "C4:1 E4:1 D4:1 D4:1",
            "C4:4",
        ),
        ("C3:4", "C3:2 G2:2", "C3:2 G2:2", "C3:4", "C3:4", "C3:2 G2:2", "C3:2 G2:2", "C3:4"),
        "Traditional French melody • opening strain, elementary arrangement",
    ),
    _score(
        "ode_to_joy",
        "Ode to Joy",
        4,
        0,
        82,
        (
            "E4:1 E4:1 F4:1 G4:1",
            "G4:1 F4:1 E4:1 D4:1",
            "C4:1 C4:1 D4:1 E4:1",
            "E4:3/2 D4:1/2 D4:2",
            "E4:1 E4:1 F4:1 G4:1",
            "G4:1 F4:1 E4:1 D4:1",
            "C4:1 C4:1 D4:1 E4:1",
            "D4:3/2 C4:1/2 C4:2",
        ),
        (
            "C3+G3:4",
            "G2+D3:4",
            "C3+G3:4",
            "G2+D3:4",
            "C3+G3:4",
            "G2+D3:4",
            "C3+G3:2 G2+D3:2",
            "C3+G3:4",
        ),
        "Beethoven • opening theme, elementary arrangement",
    ),
    _score(
        "scarborough",
        "Scarborough Fair",
        3,
        0,
        64,
        (
            "D4:2 D4:1",
            "A4:1 A4:1 A4:1",
            "E4:3/2 F4:1/2 E4:1",
            "D4:3",
            "A4:2 C5:1",
            "D5:2 C5:1",
            "A4:1 B4:1 G4:1",
            "A4:3",
            "D5:1 D5:1 D5:1",
            "C5:2 A4:1",
            "A4:1 G4:1 F4:1",
            "E4:3",
            "D4:2 A4:1",
            "C5:2 G4:1",
            "F4:1 E4:1 C4:1",
            "D4:3",
        ),
        (
            "D3+A3:3",
            "D3+A3:3",
            "C3+G3:3",
            "D3+A3:3",
            "F3+C4:3",
            "D3+A3:3",
            "G2+D3:3",
            "A2+E3:3",
            "D3+A3:3",
            "C3+G3:3",
            "F3+C4:3",
            "A2+E3:3",
            "D3+A3:3",
            "C3+G3:3",
            "A2+E3:3",
            "D3+A3:3",
        ),
        "Traditional • D Dorian, elementary arrangement",
    ),
    _score(
        "country_dance",
        "Country Dance with Drone Fifths",
        4,
        1,
        88,
        (
            "G4:1 A4:1 B4:1 G4:1",
            "D5:2 B4:2",
            "A4:1 B4:1 C5:1 A4:1",
            "F#4:2 D4:2",
            "G4:1/2 A4:1/2 B4:1 G4:1 D5:1",
            "C5:1 B4:1 A4:2",
            "G4:1 B4:1 A4:1 F#4:1",
            "G4:4",
        ),
        ("G2+D3:4", "G2+D3:4", "D3+A3:4", "D3+A3:4", "G2+D3:4", "C3+G3:4", "D3+A3:4", "G2+D3:4"),
        "Original • G major, drone fifths and eighth-note pairs",
    ),
)


COORDINATION_SCORE = _score(
    "coordination",
    "Ostinato and Syncopation",
    4,
    0,
    72,
    (
        "E4:3/2 G4:1/2 E4:1 G4:1",
        "F4:3/2 A4:1/2 F4:1 A4:1",
        "D4:1/2 E4:1/2 G4:1 E4:3/2 D4:1/2",
        "C4:4",
    ),
    ("C3:1 G3:1 C3:1 G3:1", "F3:1 C4:1 F3:1 C4:1", "G2:1 D3:1 G2:1 D3:1", "C3:1 G3:1 C3:1 G3:1"),
    "Original • independent hands, LH ostinato and RH syncopation",
)
