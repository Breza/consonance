"""Eight open curriculum units, concrete item identities, and latency-aware review."""

import json
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from statistics import median

from consonance.core.builtin_scores import ALL_SCORES
from consonance.core.db import Attempt
from consonance.core.notation import (
    STEPS,
    Clef,
    KeySignature,
    NotatedAtom,
    NotatedPitch,
    TimeSignature,
    natural,
)

MODE_TITLES = {
    "keys": "Key Finder",
    "sight": "Sight-Reader",
    "rush": "Note Rush",
    "rhythm": "Rhythm Sniper",
    "technique": "Technique Lab",
    "ear": "Ear Trainer",
    "echo": "Melody Echo",
    "song": "Song Studio",
}

# Four-note contours inside a five-finger position, as steps above its lowest note.
PHRASE_SHAPES = {
    "steps": ((0, 1, 2, 1), (0, 1, 2, 3), (3, 2, 1, 0), (2, 1, 0, 1), (1, 2, 3, 2), (2, 3, 2, 1)),
    "skips": ((0, 2, 4, 2), (4, 2, 0, 2), (0, 2, 1, 3), (3, 1, 2, 0), (0, 2, 0, 4), (4, 2, 4, 0)),
    "mixed": ((0, 1, 2, 1), (0, 2, 1, 3), (3, 2, 1, 0), (0, 1, 3, 2), (4, 2, 3, 1), (0, 2, 4, 3)),
}
INTERVAL_NAMES = {
    "m2": "minor 2nd",
    "M2": "major 2nd",
    "m3": "minor 3rd",
    "M3": "major 3rd",
    "P4": "perfect 4th",
    "TT": "tritone",
    "P5": "perfect 5th",
    "m6": "minor 6th",
    "M6": "major 6th",
    "m7": "minor 7th",
    "M7": "major 7th",
    "P8": "octave",
}
SOLFEGE = ("do", "re", "mi", "fa", "so")
HAND_NAMES = {"rh": "right hand", "lh": "left hand", "both": "hands together"}


@dataclass(frozen=True)
class CurriculumItem:
    """One thing a learner can practise and, eventually, master."""

    item_id: str
    title: str
    mode: str
    unit: int
    clef: Clef = Clef.TREBLE
    names: tuple[str, ...] = ()
    kind: str = "note"
    key_fifths: int = 0
    hand: str = "rh"
    rhythm: tuple[tuple[Fraction, bool], ...] = ()
    time: TimeSignature = TimeSignature()
    pattern: str = ""
    fingers: tuple[int, ...] = ()
    song_id: str = ""
    prompt: str = ""
    answer: str = ""

    @property
    def target_fluency_ms(self) -> float:
        """Return how quickly a clean answer must arrive to count as fluent."""
        if self.kind in ("phrase", "sequence"):
            return 3800
        if self.kind in ("interval", "ear_interval", "melodic_interval"):
            return 2400
        if self.kind in ("triad", "ear_triad", "chord_class"):
            return 2800
        return 1600

    @property
    def variations(self) -> int:
        """Return how many distinct presentations :meth:`atoms` can produce."""
        return len(self._phrase_choices()) if self.kind == "phrase" else 1

    def _phrase_choices(self) -> list[tuple[tuple[int, ...], int]]:
        """Enumerate every contour and starting step that stays inside the position."""
        return [
            (shape, start)
            for shape in PHRASE_SHAPES[self.pattern or "mixed"]
            for start in range(0, 5 - max(shape))
        ]

    def _phrase(self, variation: int) -> tuple[NotatedAtom, ...]:
        """Spell one four-note contour in this item's key and hand position."""
        choices = self._phrase_choices()
        shape, start = choices[variation % len(choices)]
        base = natural(self.names[0]).diatonic + start
        key = KeySignature(self.key_fifths)
        atoms = []
        for distance in shape:
            step = STEPS[(base + distance) % 7]
            alteration = key.alteration(step)
            pitch = NotatedPitch(
                step,
                1 if alteration == 1 else -1 if alteration == -1 else 0,
                (base + distance) // 7,
            )
            atoms.append(NotatedAtom((pitch,)))
        return tuple(atoms)

    def _pattern(self) -> tuple[NotatedAtom, ...]:
        """Build a five-finger or scale pattern, up and back, ending on a long note."""
        pitches = tuple(natural(n) for n in self.names)
        top = len(pitches) - 1
        order = (*range(top + 1), *range(top - 1, -1, -1))
        final = Fraction(4 - (len(order) - 1) % 4)
        atoms: list[NotatedAtom] = []
        for position, i in enumerate(order):
            duration = final if position == len(order) - 1 else Fraction(1)
            pitch = pitches[i]
            if self.kind == "scale":
                atoms.append(NotatedAtom((pitch,), duration, (self.fingers[i],)))
            elif self.hand == "both":
                lower = pitches[top - i] if self.kind == "contrary" else pitch
                left = NotatedPitch(lower.step, lower.alter, lower.octave - 1)
                fingers = (i + 1, i + 1 if self.kind == "contrary" else 5 - i)
                atoms.append(NotatedAtom((pitch, left), duration, fingers))
            else:
                atoms.append(
                    NotatedAtom((pitch,), duration, (5 - i if self.hand == "lh" else i + 1,))
                )
        return tuple(atoms)

    def atoms(self, variation: int = 0) -> tuple[NotatedAtom, ...]:
        """Return the notes to present; phrase items change with ``variation``."""
        if self.kind == "phrase":
            return self._phrase(variation)
        if self.kind in ("technique", "contrary", "scale"):
            return self._pattern()
        if self.kind == "rhythm":
            return tuple(
                NotatedAtom((natural("C4"),) if strike else (), duration)
                for duration, strike in self.rhythm
            )
        pitches = tuple(natural(n) for n in self.names)
        if self.kind in ("ear_interval", "melodic_interval", "sequence"):
            return tuple(NotatedAtom((p,)) for p in pitches)
        return (NotatedAtom(pitches),) if pitches else ()


@dataclass(frozen=True)
class CurriculumUnit:
    """A numbered stage of the course; nothing is ever locked."""

    number: int
    title: str
    description: str
    items: tuple[CurriculumItem, ...]


SONG_UNITS = (
    ("hot_cross_buns", 2),
    ("mary_lamb", 2),
    ("landmark_waltz", 2),
    ("stepping_stones", 2),
    ("au_clair", 3),
    ("lightly_row", 3),
    ("ode_to_joy", 4),
    ("jingle_bells", 4),
    ("three_chord_walk", 5),
    ("scarborough", 6),
    ("country_dance", 7),
    ("frere_jacques", 7),
)
RHYTHM_CELLS = (
    (1, "4/4", "quarters", "Quarter notes", ((1, True),) * 4),
    (1, "4/4", "halves", "Half notes", ((2, True), (2, True))),
    (1, "4/4", "whole", "Whole notes", ((4, True),)),
    (1, "4/4", "quarter_quarter_half", "Quarter, quarter, half", ((1, True), (1, True), (2, True))),
    (2, "4/4", "quarter_rests", "Quarter notes and rests", ((1, True), (1, False)) * 2),
    (3, "3/4", "dotted_half", "Dotted half notes", ((3, True),)),
    (3, "3/4", "quarters", "Quarter notes", ((1, True),) * 3),
    (3, "3/4", "half_quarter", "Half, then quarter", ((2, True), (1, True))),
    (
        4,
        "4/4",
        "eighths",
        "Eighth-note pairs",
        ((0.5, True), (0.5, True), (1, True), (1, False), (1, True)),
    ),
    (
        4,
        "3/4",
        "rest_and_eighths",
        "Rest, then eighths",
        ((1, False), (0.5, True), (0.5, True), (1, True)),
    ),
    (
        6,
        "4/4",
        "dotted_quarter",
        "Dotted quarter and eighth",
        ((1.5, True), (0.5, True), (1, True), (1, True)),
    ),
    (
        8,
        "4/4",
        "syncopation",
        "Syncopation",
        ((1.5, True), (0.5, True), (1, False), (0.5, True), (0.5, True)),
    ),
)
UNIT_TITLES = (
    (
        "Keyboard, Landmarks & Pulse",
        "Find every key by name, then G4, F3 and Middle C on the staff.",
    ),
    ("Five-Finger Positions & Evenness", "Read small contours and explore an even touch."),
    ("Steps, Skips & Ear Anchors", "Read distances, then hear them."),
    ("Fourths, Fifths & Eighths", "Ground the left hand and divide the beat."),
    ("Triads & Chord Spread", "Build major and minor shapes calmly."),
    ("Ledger Range, Minor & Dorian", "Expand to C2..C6, play a full scale, explore modal melody."),
    ("G Major & F Major", "Name the black keys; read key signatures and cancellations."),
    (
        "Independent Two-Hand Coordination",
        "Combine motion, ostinatos, syncopation, D and Bb major.",
    ),
)


def _note(unit: int, clef: Clef, name: str) -> CurriculumItem:
    """Describe reading one written note."""
    return CurriculumItem(
        f"note:{clef}:{name}", f"{clef.title()} {name}", "sight", unit, clef, (name,)
    )


def _phrase(
    unit: int, clef: Clef, tag: str, title: str, low: str, pattern: str, fifths: int = 0
) -> CurriculumItem:
    """Describe reading a four-note contour that varies on every presentation."""
    return CurriculumItem(
        f"phrase:{clef}:{tag}",
        f"{title} • {clef}",
        "sight",
        unit,
        clef,
        (low,),
        "phrase",
        fifths,
        pattern=pattern,
    )


def _key_items() -> dict[int, list[CurriculumItem]]:
    """Describe finding keys and chords by name, before or beside staff reading."""
    items: dict[int, list[CurriculumItem]] = {1: [], 5: [], 7: []}
    for letter in "CDEFGAB":
        items[1].append(
            CurriculumItem(
                f"key:{letter}",
                f"Find {letter}",
                "keys",
                1,
                names=(f"{letter}4",),
                kind="key_class",
                prompt=f"Play any {letter}",
            )
        )
    for tag, title, name, prompt in (
        ("middle_C", "Find Middle C", "C4", "Play Middle C"),
        ("treble_G", "Find Treble G", "G4", "Play the G above Middle C"),
        ("bass_F", "Find Bass F", "F3", "Play the F below Middle C"),
    ):
        items[1].append(
            CurriculumItem(
                f"key:{tag}", title, "keys", 1, names=(name,), kind="key_pitch", prompt=prompt
            )
        )
    for sharp, flat in (("C#", "Db"), ("D#", "Eb"), ("F#", "Gb"), ("G#", "Ab"), ("A#", "Bb")):
        items[7].append(
            CurriculumItem(
                f"key:{sharp}",
                f"Find {sharp} / {flat}",
                "keys",
                7,
                names=(f"{sharp}4",),
                kind="key_class",
                prompt=f"Play any {sharp} (also called {flat})",
            )
        )
    for root, quality, names in (
        ("C", "major", ("C4", "E4", "G4")),
        ("F", "major", ("F4", "A4", "C5")),
        ("G", "major", ("G4", "B4", "D5")),
        ("A", "minor", ("A4", "C5", "E5")),
        ("D", "minor", ("D4", "F4", "A4")),
        ("E", "minor", ("E4", "G4", "B4")),
    ):
        items[5].append(
            CurriculumItem(
                f"chord:{root}_{quality}",
                f"{root} {quality} chord by name",
                "keys",
                5,
                names=names,
                kind="chord_class",
                prompt=f"Play a {root} {quality} chord",
                answer=" - ".join(n[:-1] for n in names),
            )
        )
    return items


def _sight_items() -> dict[int, list[CurriculumItem]]:
    """Describe every staff-reading item: notes, intervals, triads, and contours."""
    items: dict[int, list[CurriculumItem]] = {i: [] for i in range(1, 9)}
    for clef, name in (
        (Clef.TREBLE, "G4"),
        (Clef.BASS, "F3"),
        (Clef.TREBLE, "C4"),
        (Clef.BASS, "C4"),
    ):
        items[1].append(_note(1, clef, name))
    for clef, octave in ((Clef.TREBLE, 4), (Clef.BASS, 3)):
        seen = {i.item_id for i in items[1]}
        for step in "CDEFG":
            note = _note(2, clef, f"{step}{octave}")
            if note.item_id not in seen:
                items[2].append(note)
        for pattern in ("steps", "skips"):
            title = f"Four-note {pattern}"
            items[2].append(_phrase(2, clef, f"C:{pattern}", title, f"C{octave}", pattern))
    for number, (label, target) in enumerate(
        (("2nd", "D"), ("3rd", "E"), ("4th", "F"), ("5th", "G"))
    ):
        unit = 3 if number < 2 else 4
        for clef, octave in ((Clef.TREBLE, 4), (Clef.BASS, 3)):
            pair = (f"C{octave}", f"{target}{octave}")
            for tag, word, kind in (
                (label, "Harmonic", "interval"),
                (f"melodic_{label}", "Melodic", "melodic_interval"),
            ):
                items[unit].append(
                    CurriculumItem(
                        f"interval_read:{clef}:{tag}",
                        f"{word} {label} • {clef}",
                        "sight",
                        unit,
                        clef,
                        pair,
                        kind,
                    )
                )
    for root, quality, word, names in (
        ("C", "maj", "major", ("C4", "E4", "G4")),
        ("F", "maj", "major", ("F3", "A3", "C4")),
        ("G", "maj", "major", ("G3", "B3", "D4")),
        ("A", "min", "minor", ("A3", "C4", "E4")),
        ("D", "min", "minor", ("D4", "F4", "A4")),
        ("E", "min", "minor", ("E4", "G4", "B4")),
    ):
        clef = Clef.BASS if root in ("F", "G", "A") else Clef.TREBLE
        items[5].append(
            CurriculumItem(
                f"triad:{clef}:{root}_{quality}",
                f"{root} {word} triad on the staff",
                "sight",
                5,
                clef,
                names,
                "triad",
            )
        )
    for name in ("A4", "B4", "C5", "D5", "E5", "F5", "G5", "A5", "B5", "C6"):
        items[6].append(_note(6, Clef.TREBLE, name))
    for name in ("C2", "D2", "E2", "F2", "G2", "A2", "B2"):
        items[6].append(_note(6, Clef.BASS, name))
    for tag, title, treble, bass in (
        ("Am:steps", "A minor melody", "A4", "A2"),
        ("D_dorian:steps", "D Dorian melody", "D4", "D3"),
    ):
        items[6].append(_phrase(6, Clef.TREBLE, tag, title, treble, "mixed"))
        items[6].append(_phrase(6, Clef.BASS, tag, title, bass, "mixed"))
    for key, fifths, spelling, title in (
        ("G", 1, ("F#4", "F4", "F#4", "G4"), "G major: F-sharp, then F-natural"),
        ("F", -1, ("Bb4", "B4", "Bb4", "A4"), "F major: B-flat, then B-natural"),
    ):
        items[7].append(
            CurriculumItem(
                f"phrase:treble:{key}:cancellation",
                title,
                "sight",
                7,
                names=spelling,
                kind="sequence",
                key_fifths=fifths,
            )
        )
    for key, fifths, treble, bass in (("D", 2, "D4", "D3"), ("Bb", -2, "Bb3", "Bb2")):
        title = f"{key} major melody"
        items[8].append(_phrase(8, Clef.TREBLE, f"{key}:steps", title, treble, "mixed", fifths))
        items[8].append(_phrase(8, Clef.BASS, f"{key}:steps", title, bass, "mixed", fifths))
    return items


def _ear_items() -> dict[int, list[CurriculumItem]]:
    """Describe listening items: scale degrees over a sounded tonic, intervals, triads."""
    items: dict[int, list[CurriculumItem]] = {3: [], 5: []}
    for degree, step in enumerate("CDEFG", 1):
        items[3].append(
            CurriculumItem(
                f"ear:note:{degree}",
                f"Hear scale degree {degree} ({SOLFEGE[degree - 1]})",
                "ear",
                3,
                names=(f"{step}4",),
                kind="ear_note",
                answer=f"{step}, degree {degree} ({SOLFEGE[degree - 1]}) above C",
            )
        )
    for interval, upper in (
        ("m2", "Db4"),
        ("M2", "D4"),
        ("m3", "Eb4"),
        ("M3", "E4"),
        ("P4", "F4"),
        ("TT", "F#4"),
        ("P5", "G4"),
        ("m6", "Ab4"),
        ("M6", "A4"),
        ("m7", "Bb4"),
        ("M7", "B4"),
        ("P8", "C5"),
    ):
        unit = 3 if interval in ("M2", "M3", "P5") else 5
        name = INTERVAL_NAMES[interval]
        items[unit].append(
            CurriculumItem(
                f"ear:interval:{interval}",
                f"Hear a {name}",
                "ear",
                unit,
                names=("C4", upper),
                kind="ear_interval",
                answer=f"C up to {upper[:-1]}, a {name}",
            )
        )
    for quality, word, names in (
        ("maj", "major", ("C4", "E4", "G4")),
        ("min", "minor", ("C4", "Eb4", "G4")),
    ):
        items[5].append(
            CurriculumItem(
                f"ear:triad:{quality}",
                f"Hear a {word} triad",
                "ear",
                5,
                names=names,
                kind="ear_triad",
                answer=f"C {word}: " + " - ".join(n[:-1] for n in names),
            )
        )
    return items


def _technique_items() -> dict[int, list[CurriculumItem]]:
    """Describe evenness patterns: five-finger positions, scales, and two-hand motion."""
    items: dict[int, list[CurriculumItem]] = {2: [], 6: [], 7: [], 8: []}
    for hand in ("rh", "lh", "both"):
        octave = 3 if hand == "lh" else 4
        items[2].append(
            CurriculumItem(
                f"tech:{hand}:C_pentascale",
                f"C five-finger pattern • {HAND_NAMES[hand]}",
                "technique",
                2,
                Clef.BASS if hand == "lh" else Clef.TREBLE,
                tuple(f"{s}{octave}" for s in "CDEFG"),
                "technique",
                hand=hand,
            )
        )
    for tag, hand, unit, fifths, spelled, fingers in (
        ("rh:C_major", "rh", 6, 0, "C4 D4 E4 F4 G4 A4 B4 C5", (1, 2, 3, 1, 2, 3, 4, 5)),
        ("lh:C_major", "lh", 6, 0, "C3 D3 E3 F3 G3 A3 B3 C4", (5, 4, 3, 2, 1, 3, 2, 1)),
        ("rh:G_major", "rh", 7, 1, "G4 A4 B4 C5 D5 E5 F#5 G5", (1, 2, 3, 1, 2, 3, 4, 5)),
        ("rh:F_major", "rh", 7, -1, "F4 G4 A4 Bb4 C5 D5 E5 F5", (1, 2, 3, 4, 1, 2, 3, 4)),
    ):
        key = tag.split(":")[1].split("_")[0]
        items[unit].append(
            CurriculumItem(
                f"scale:{tag}",
                f"{key} major scale • {HAND_NAMES[hand]}",
                "technique",
                unit,
                Clef.BASS if hand == "lh" else Clef.TREBLE,
                tuple(spelled.split()),
                "scale",
                fifths,
                hand,
                fingers=fingers,
            )
        )
    for key, fifths, names in (
        ("G", 1, ("G4", "A4", "B4", "C5", "D5")),
        ("F", -1, ("F4", "G4", "A4", "Bb4", "C5")),
    ):
        items[7].append(
            CurriculumItem(
                f"tech:rh:{key}_pentascale",
                f"{key} five-finger pattern • right hand",
                "technique",
                7,
                names=names,
                kind="technique",
                key_fifths=fifths,
            )
        )
    for tag, title, kind in (
        ("parallel", "Parallel motion", "technique"),
        ("contrary", "Contrary motion", "contrary"),
    ):
        items[8].append(
            CurriculumItem(
                f"coord:{tag}:C",
                f"{title} • hands together",
                "technique",
                8,
                names=("C4", "D4", "E4", "F4", "G4"),
                kind=kind,
                hand="both",
            )
        )
    return items


def _units() -> tuple[CurriculumUnit, ...]:
    """Assemble the eight units in the order a learner meets each kind of work."""
    groups: dict[int, list[CurriculumItem]] = {i: [] for i in range(1, 9)}
    keys, sight, ear, technique = _key_items(), _sight_items(), _ear_items(), _technique_items()
    rhythm: dict[int, list[CurriculumItem]] = {}
    for unit, signature, cell, title, values in RHYTHM_CELLS:
        rhythm.setdefault(unit, []).append(
            CurriculumItem(
                f"rhythm:{signature}:{cell}",
                f"{title} ({signature})",
                "rhythm",
                unit,
                kind="rhythm",
                rhythm=tuple((Fraction(d), strike) for d, strike in values),
                time=TimeSignature(int(signature[0])),
            )
        )
    titles = {score.song_id: score.title for score in ALL_SCORES}
    songs: dict[int, list[CurriculumItem]] = {}
    for song, unit in SONG_UNITS:
        for hand in ("rh", "both"):
            songs.setdefault(unit, []).append(
                CurriculumItem(
                    f"song:{song}:all:{hand}",
                    f"{titles[song]} • {HAND_NAMES[hand]}",
                    "song",
                    unit,
                    kind="song",
                    hand=hand,
                    song_id=song,
                )
            )
    songs.setdefault(8, []).append(
        CurriculumItem(
            "coord:ostinato:C",
            f"{titles['coordination']} • hands together",
            "song",
            8,
            kind="coordination",
            hand="both",
            song_id="coordination",
        )
    )
    for unit in groups:
        for source in (keys, sight, rhythm, technique, ear, songs):
            groups[unit].extend(source.get(unit, ()))
    return tuple(
        CurriculumUnit(i, UNIT_TITLES[i - 1][0], UNIT_TITLES[i - 1][1], tuple(groups[i]))
        for i in range(1, 9)
    )


UNITS = _units()
ITEMS = {item.item_id: item for unit in UNITS for item in unit.items}
SONG_ITEMS = {(i.song_id, i.hand): i.item_id for i in ITEMS.values() if i.mode == "song"}


def song_item_id(song_id: str, hand: str, section: str = "all") -> str:
    """Return the identity under which a song pass is logged.

    A complete pass of a curriculum piece uses that piece's curriculum identity, so it
    counts toward mastery; a looped section or an imported file gets a descriptive one.
    """
    if section == "all" and (song_id, hand) in SONG_ITEMS:
        return SONG_ITEMS[(song_id, hand)]
    return f"song:{song_id}:{section}:{hand}"


def items_for(mode: str, unit: int | None = None) -> tuple[CurriculumItem, ...]:
    """Return a mode's items, from one unit or in course order across all of them."""
    units = UNITS if unit is None else (UNITS[unit - 1],)
    return tuple(i for u in units for i in u.items if i.mode == mode)


@dataclass(frozen=True)
class StudyConfig:
    """A request to practise a set of same-mode items, optionally with a display title."""

    items: tuple[CurriculumItem, ...]
    title: str = ""

    def __post_init__(self) -> None:
        """Reject empty or mixed-mode study sets."""
        if not self.items or len({i.mode for i in self.items}) != 1:
            raise ValueError("A study queue requires items from the same practice mode")


SCHEDULE_VERSION = 2
BOX_INTERVALS = (
    timedelta(hours=4),
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
    timedelta(days=21),
)
WINDOW = 10


@dataclass(frozen=True)
class ItemSchedule:
    """The derived review state of one item; always rebuildable from the attempt log."""

    item_id: str
    box: int
    due_at_utc: str
    rolling_accuracy: float
    rolling_median_ms: float
    mastered: bool


def countable(attempt: Attempt) -> bool:
    """Report whether an attempt is evidence about the learner's skill.

    Attempts abandoned without an error, attempts made with note names or key hints
    showing, and game scores stay in the log but never move the schedule either way.
    """
    raw = attempt.prompt_json
    if "blameless" not in raw and "assisted" not in raw and "game" not in raw:
        return True
    data = json.loads(raw)
    return not (data.get("blameless") or data.get("assisted") or data.get("game"))


def fluent(attempt: Attempt) -> bool:
    """Check the attempt against its mode-specific fluency requirements."""
    item = ITEMS.get(attempt.item_id)
    if attempt.mode in ("rhythm", "technique", "song"):
        data = json.loads(attempt.prompt_json)
        accuracy = float(data.get("hit_accuracy", 0))
        if attempt.mode == "technique":
            return accuracy >= 0.9 and float(data.get("ioi_sd_ms", 999)) <= 35
        if attempt.mode == "rhythm":
            return (
                accuracy >= 0.9
                and float(data.get("jitter_ms", 999)) <= 35
                and float(data.get("tempo_bpm", 0)) >= 60
            )
        return (
            accuracy >= 0.9
            and float(data.get("tempo_scale", 0)) >= 0.8
            and data.get("mode") == "Tempo"
        )
    target = (
        item.target_fluency_ms
        if item
        else (
            3800
            if attempt.item_id.startswith("phrase:")
            else 2800
            if "triad" in attempt.item_id
            else 2400
            if "interval" in attempt.item_id
            else 1600
        )
    )
    return attempt.response_ms is not None and attempt.response_ms <= target


def advance_schedule(previous: ItemSchedule | None, recent: Sequence[Attempt]) -> ItemSchedule:
    """Fold the newest countable attempt into an item's review state.

    ``recent`` holds the item's latest countable attempts, oldest first and at most
    :data:`WINDOW` long, ending with the attempt being applied. A clean, fluent answer
    promotes the item one box only if the item was new or actually due; extra practice
    before then leaves the box and due date alone, so a single sitting cannot push an item
    weeks into the future. A clean but slow answer returns in four hours, and a mistake
    restarts the item in box 1.
    """
    attempt = recent[-1]
    at = datetime.fromisoformat(attempt.timestamp_utc).astimezone(UTC)
    old_box = previous.box if previous else 1
    was_due = previous is None or at >= datetime.fromisoformat(previous.due_at_utc)
    clean, quick = attempt.is_first_try_correct, fluent(attempt)
    if not clean:
        box, due = 1, (at + BOX_INTERVALS[0]).isoformat()
    elif not quick:
        box, due = old_box, (at + BOX_INTERVALS[0]).isoformat()
    elif was_due or previous is None:
        box = min(5, old_box + 1)
        due = (at + BOX_INTERVALS[box - 1]).isoformat()
    else:
        box, due = old_box, previous.due_at_utc
    accuracy = sum(a.is_first_try_correct for a in recent) / len(recent)
    responses = [a.response_ms for a in recent if a.response_ms is not None]
    latency = float(median(responses)) if responses else 0.0
    full = len(recent) >= WINDOW and accuracy >= 0.9
    if attempt.mode in ("rhythm", "technique", "song"):
        mastered = full and sum(fluent(a) for a in recent) >= 9
    else:
        # Judge fluency on the median response across the same most-recent window.
        typical = Attempt(
            "", attempt.mode, attempt.item_id, (), (), True, 0, latency if responses else None
        )
        mastered = full and fluent(typical)
    return ItemSchedule(attempt.item_id, box, due, accuracy, latency, mastered)


def rebuild_schedule(attempts: Iterable[Attempt]) -> dict[str, ItemSchedule]:
    """Replay the whole attempt log, oldest first, into a fresh review state per item."""
    histories: dict[str, deque[Attempt]] = {}
    states: dict[str, ItemSchedule] = {}
    for attempt in attempts:
        if not countable(attempt):
            continue
        history = histories.setdefault(attempt.item_id, deque(maxlen=WINDOW))
        history.append(attempt)
        states[attempt.item_id] = advance_schedule(states.get(attempt.item_id), tuple(history))
    return states


def unit_progress(states: dict[str, ItemSchedule]) -> tuple[tuple[int, int], ...]:
    """Return (mastered, total) item counts for each unit, in unit order."""
    return tuple(
        (
            sum(1 for i in unit.items if i.item_id in states and states[i.item_id].mastered),
            len(unit.items),
        )
        for unit in UNITS
    )


def recommended_unit(states: dict[str, ItemSchedule]) -> int:
    """Return the first unit with fewer than 80% of its items mastered."""
    for number, (mastered, total) in enumerate(unit_progress(states), 1):
        if mastered / max(1, total) < 0.8:
            return number
    return 8


def item_status(item_id: str, states: dict[str, ItemSchedule], now: datetime) -> str:
    """Classify an item as ``new``, ``due``, ``learning`` or ``mastered`` for display."""
    state = states.get(item_id)
    if state is None:
        return "new"
    if datetime.fromisoformat(state.due_at_utc) <= now:
        return "due"
    return "mastered" if state.mastered else "learning"
