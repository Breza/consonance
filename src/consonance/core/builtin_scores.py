"""Twelve elementary arrangements plus one coordination study, as exact rational scores.

Traditional and classical melodies are in the public domain; the remaining pieces are
original to Consonance. These deliberately short teaching arrangements are the single
source of both the staff notation and the exported MIDI files.
"""

from dataclasses import dataclass
from fractions import Fraction

from consonance.core.fingering import finger_part
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
    """A complete two-hand teaching piece."""

    song_id: str
    title: str
    time: TimeSignature
    key: KeySignature
    bpm: int
    measures: tuple[Measure, ...]
    description: str

    def validate(self) -> None:
        """Raise ValueError unless every measure is complete, in range, and playable."""
        sounding: dict[Hand, list[tuple[Fraction, Fraction, int]]] = {Hand.RIGHT: [], Hand.LEFT: []}
        for number, measure in enumerate(self.measures, 1):
            for hand, atoms in ((Hand.RIGHT, measure.right), (Hand.LEFT, measure.left)):
                if sum((a.duration for a in atoms), Fraction()) != self.time.beats:
                    raise ValueError(f"{self.title}, measure {number}: incomplete hand measure")
                beat = (number - 1) * self.time.beats
                for atom in atoms:
                    if len(set(p.midi for p in atom.pitches)) != len(atom.pitches):
                        raise ValueError("Duplicate pitch within chord")
                    if any(not 36 <= p.midi <= 84 for p in atom.pitches):
                        raise ValueError("Score exceeds C2..C6 sight-reading range")
                    if atom.pitches and not atom.fingering:
                        raise ValueError("Built-in notes require starter fingerings")
                    sounding[hand].extend(
                        (beat, beat + atom.duration, p.midi) for p in atom.pitches
                    )
                    beat += atom.duration
        for start, end, pitch in sounding[Hand.RIGHT]:
            if any(p == pitch and s < end and start < e for s, e, p in sounding[Hand.LEFT]):
                raise ValueError(f"{self.title}: both hands need the same key at once")

    def compile(self) -> SongTimeline:
        """Flatten the score into the beat-addressed notes that playback and judging use."""
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


def _bar(source: str) -> tuple[NotatedAtom, ...]:
    """Parse one measure such as ``C4:1 E4+G4:2 r:1`` (pitch or chord, colon, beats)."""
    atoms: list[NotatedAtom] = []
    for token in source.split():
        spelling, duration = token.split(":")
        pitches = () if spelling == "r" else tuple(natural(p) for p in spelling.split("+"))
        atoms.append(NotatedAtom(pitches, Fraction(duration)))
    return tuple(atoms)


def _part(sources: tuple[str, ...], hand: Hand) -> list[tuple[NotatedAtom, ...]]:
    """Parse a hand's measures and finger the part as one continuous line."""
    bars = [_bar(source) for source in sources]
    fingered = finger_part([atom for bar in bars for atom in bar], hand)
    result: list[tuple[NotatedAtom, ...]] = []
    cursor = 0
    for bar in bars:
        result.append(fingered[cursor : cursor + len(bar)])
        cursor += len(bar)
    return result


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
    """Build and validate a score from per-measure source strings for each hand."""
    if len(right) != len(left):
        raise ValueError("Both hands require the same number of measures")
    score = BuiltinScore(
        sid,
        title,
        TimeSignature(beats),
        KeySignature(key),
        bpm,
        tuple(
            Measure(rh, lh)
            for rh, lh in zip(_part(right, Hand.RIGHT), _part(left, Hand.LEFT), strict=True)
        ),
        description,
    )
    score.validate()
    return score


_C_DRONE = ("C3+G3:4",) * 4
BUILTIN_SCORES = (
    _score(
        "hot_cross_buns",
        "Hot Cross Buns",
        4,
        0,
        80,
        (
            "E4:2 D4:2",
            "C4:4",
            "E4:2 D4:2",
            "C4:4",
            "C4:1 C4:1 C4:1 C4:1",
            "D4:1 D4:1 D4:1 D4:1",
            "E4:2 D4:2",
            "C4:4",
        ),
        ("C3:2 G3:2", "C3:4", "C3:2 G3:2", "C3:4", "C3:4", "G3:4", "C3:2 G3:2", "C3:4"),
        "Traditional • three notes, halves and quarters",
    ),
    _score(
        "mary_lamb",
        "Mary Had a Little Lamb",
        4,
        0,
        84,
        (
            "E4:1 D4:1 C4:1 D4:1",
            "E4:1 E4:1 E4:2",
            "D4:1 D4:1 D4:2",
            "E4:1 G4:1 G4:2",
            "E4:1 D4:1 C4:1 D4:1",
            "E4:1 E4:1 E4:1 E4:1",
            "D4:1 D4:1 E4:1 D4:1",
            "C4:4",
        ),
        ("C3:4", "C3:4", "G3:4", "C3:4", "C3:4", "C3:4", "G3:4", "C3:4"),
        "Traditional • steps and one skip in C position",
    ),
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
        "lightly_row",
        "Lightly Row",
        4,
        0,
        84,
        (
            "G4:1 E4:1 E4:2",
            "F4:1 D4:1 D4:2",
            "C4:1 D4:1 E4:1 F4:1",
            "G4:1 G4:1 G4:2",
            "G4:1 E4:1 E4:2",
            "F4:1 D4:1 D4:2",
            "C4:1 E4:1 G4:1 G4:1",
            "C4:4",
        ),
        ("C3:4", "G3:4", "C3:4", "C3:4", "C3:4", "G3:4", "C3:2 G3:2", "C3:4"),
        "Traditional German melody • skips of a third in C position",
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
        "jingle_bells",
        "Jingle Bells",
        4,
        0,
        96,
        (
            "E4:1 E4:1 E4:2",
            "E4:1 E4:1 E4:2",
            "E4:1 G4:1 C4:3/2 D4:1/2",
            "E4:4",
            "F4:1 F4:1 F4:3/2 F4:1/2",
            "F4:1 E4:1 E4:1 E4:1/2 E4:1/2",
            "G4:1 G4:1 F4:1 D4:1",
            "C4:4",
        ),
        (*_C_DRONE, "C3+F3:4", "C3+G3:4", "D3+G3:4", "C3+G3:4"),
        "Pierpont • chorus, with left-hand fourths and fifths",
    ),
    _score(
        "three_chord_walk",
        "Three-Chord Walk",
        4,
        0,
        76,
        (
            "E4:1 G4:1 E4:2",
            "F4:1 C4:1 F4:2",
            "D4:1 G4:1 D4:2",
            "E4:4",
            "G4:1 E4:1 C4:1 E4:1",
            "F4:2 C4:2",
            "D4:1 F4:1 E4:1 D4:1",
            "C4:4",
        ),
        (
            "C3+E3+G3:4",
            "C3+F3+A3:4",
            "B2+D3+G3:4",
            "C3+E3+G3:4",
            "C3+E3+G3:4",
            "C3+F3+A3:4",
            "B2+D3+G3:4",
            "C3+E3+G3:4",
        ),
        "Original • C, F and G triads in close position under broken chords",
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
    _score(
        "frere_jacques",
        "Frère Jacques",
        4,
        -1,
        92,
        (
            "F4:1 G4:1 A4:1 F4:1",
            "F4:1 G4:1 A4:1 F4:1",
            "A4:1 Bb4:1 C5:2",
            "A4:1 Bb4:1 C5:2",
            "C5:1/2 D5:1/2 C5:1/2 Bb4:1/2 A4:1 F4:1",
            "C5:1/2 D5:1/2 C5:1/2 Bb4:1/2 A4:1 F4:1",
            "F4:1 C4:1 F4:2",
            "F4:1 C4:1 F4:2",
        ),
        ("F2+C3:4",) * 8,
        "Traditional French round • F major with B-flat, over a drone fifth",
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

ALL_SCORES = (*BUILTIN_SCORES, COORDINATION_SCORE)


def score_by_id(song_id: str) -> BuiltinScore | None:
    """Return the built-in score with this identifier, if there is one."""
    return next((score for score in ALL_SCORES if score.song_id == song_id), None)
