"""Eight open curriculum units, concrete item identities, and latency-aware review."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from statistics import median

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


@dataclass(frozen=True)
class CurriculumItem:
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

    @property
    def target_fluency_ms(self) -> float:
        if self.kind == "phrase":
            return 3800
        if self.kind in ("interval", "ear_interval", "melodic_interval"):
            return 2400
        if self.kind in ("triad", "ear_triad"):
            return 2800
        return 1600

    def atoms(self, variation: int = 0) -> tuple[NotatedAtom, ...]:
        pitches = tuple(natural(n) for n in self.names)
        if self.kind == "phrase":
            # Vary anchor and contour within the unit's diatonic range on each presentation.
            contours = ((0, 1, 2, 1), (0, 2, 1, 3), (3, 2, 1, 0), (0, 1, 3, 2))
            pattern = contours[variation % len(contours)]
            anchor = pitches[variation % len(pitches)]
            base = anchor.diatonic
            result: list[NotatedAtom] = []
            for distance in pattern:
                diatonic = base + distance
                step = STEPS[diatonic % 7]
                alteration = KeySignature(self.key_fifths).alteration(step)
                pitch = NotatedPitch(
                    step, 1 if alteration == 1 else -1 if alteration == -1 else 0, diatonic // 7
                )
                result.append(NotatedAtom((pitch,)))
            return tuple(result)
        if self.kind in ("technique", "contrary"):
            sequence = (0, 1, 2, 3, 4, 3, 2, 1, 0)
            atoms: list[NotatedAtom] = []
            for i in sequence:
                pitch = pitches[i]
                lower = pitches[4 - i] if self.kind == "contrary" else pitch
                both = (pitch, NotatedPitch(lower.step, lower.alter, lower.octave - 1))
                if self.hand == "both":
                    atoms.append(
                        NotatedAtom(
                            both, fingering=(i + 1, i + 1 if self.kind == "contrary" else 5 - i)
                        )
                    )
                else:
                    atoms.append(
                        NotatedAtom((pitch,), fingering=(5 - i if self.hand == "lh" else i + 1,))
                    )
            return tuple(atoms)
        if self.kind == "rhythm":
            return tuple(
                NotatedAtom((natural("C4"),) if strike else (), duration)
                for duration, strike in self.rhythm
            )
        if self.kind in ("ear_interval", "ear_note", "melodic_interval") and len(pitches) > 1:
            return tuple(NotatedAtom((p,)) for p in pitches)
        return (NotatedAtom(pitches),) if pitches else ()


@dataclass(frozen=True)
class CurriculumUnit:
    number: int
    title: str
    description: str
    items: tuple[CurriculumItem, ...]


def _units() -> tuple[CurriculumUnit, ...]:
    groups: dict[int, list[CurriculumItem]] = {i: [] for i in range(1, 9)}
    names: tuple[str, ...]
    anchors: tuple[str, ...]

    def note(unit: int, clef: Clef, name: str, fifths: int = 0) -> None:
        sid = f"note:{clef}:{name}"
        if not any(i.item_id == sid for items in groups.values() for i in items):
            groups[unit].append(
                CurriculumItem(
                    sid, f"{clef.title()} {name}", "sight", unit, clef, (name,), key_fifths=fifths
                )
            )

    for clef, name in (
        (Clef.TREBLE, "G4"),
        (Clef.BASS, "F3"),
        (Clef.TREBLE, "C4"),
        (Clef.BASS, "C4"),
    ):
        note(1, clef, name)
    rhythm_cells = (
        (1, "4/4", "quarters", ((1, True), (1, True), (1, True), (1, True))),
        (1, "4/4", "halves", ((2, True), (2, True))),
        (1, "4/4", "whole", ((4, True),)),
        (3, "3/4", "dotted_half", ((3, True),)),
        (4, "4/4", "eighths", ((0.5, True), (0.5, True), (1, True), (1, False), (1, True))),
        (4, "3/4", "rest_and_eighths", ((1, False), (0.5, True), (0.5, True), (1, True))),
        (8, "4/4", "syncopation", ((1.5, True), (0.5, True), (1, False), (0.5, True), (0.5, True))),
    )
    for unit, signature, cell, values in rhythm_cells:
        groups[unit].append(
            CurriculumItem(
                f"rhythm:{signature}:{cell}",
                f"{signature} {cell.replace('_', ' ')}",
                "rhythm",
                unit,
                kind="rhythm",
                rhythm=tuple((Fraction(d), strike) for d, strike in values),
                time=TimeSignature(int(signature[0])),
            )
        )
    for clef, octave in ((Clef.TREBLE, 4), (Clef.BASS, 3)):
        for step in "CDEFG":
            note(2, clef, f"{step}{octave}")
        for pattern in ("steps", "skips"):
            groups[2].append(
                CurriculumItem(
                    f"phrase:{clef}:C:{pattern}",
                    f"{clef.title()} four-note {pattern}",
                    "sight",
                    2,
                    clef,
                    (f"C{octave}", f"D{octave}"),
                    "phrase",
                )
            )
    for hand in ("rh", "lh", "both"):
        octave = 3 if hand == "lh" else 4
        groups[2].append(
            CurriculumItem(
                f"tech:{hand}:C_pentascale",
                f"{hand.upper()} C evenness",
                "technique",
                2,
                Clef.BASS if hand == "lh" else Clef.TREBLE,
                tuple(f"{s}{octave}" for s in "CDEFG"),
                "technique",
                hand=hand,
            )
        )
    for number, (label, target) in enumerate(
        (("2nd", "D"), ("3rd", "E"), ("4th", "F"), ("5th", "G"))
    ):
        unit = 3 if number < 2 else 4
        for clef, octave in ((Clef.TREBLE, 4), (Clef.BASS, 3)):
            groups[unit].append(
                CurriculumItem(
                    f"interval_read:{clef}:{label}",
                    f"{clef.title()} harmonic {label}",
                    "sight",
                    unit,
                    clef,
                    (f"C{octave}", f"{target}{octave}"),
                    "interval",
                )
            )
            groups[unit].append(
                CurriculumItem(
                    f"interval_read:{clef}:melodic_{label}",
                    f"{clef.title()} melodic {label}",
                    "sight",
                    unit,
                    clef,
                    (f"C{octave}", f"{target}{octave}"),
                    "melodic_interval",
                )
            )
    for degree, step in enumerate("CDEFG", 1):
        groups[3].append(
            CurriculumItem(
                f"ear:note:{degree}",
                f"Ear anchor: degree {degree}",
                "ear",
                3,
                names=(f"{step}4",),
                kind="ear_note",
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
        groups[3 if interval in ("M2", "M3", "P5") else 5].append(
            CurriculumItem(
                f"ear:interval:{interval}",
                f"Hear a {interval}",
                "ear",
                3 if interval in ("M2", "M3", "P5") else 5,
                names=("C4", upper),
                kind="ear_interval",
            )
        )
    for root, quality, names in (
        ("C", "maj", ("C4", "E4", "G4")),
        ("F", "maj", ("F3", "A3", "C4")),
        ("G", "maj", ("G3", "B3", "D4")),
        ("A", "min", ("A3", "C4", "E4")),
        ("D", "min", ("D4", "F4", "A4")),
        ("E", "min", ("E4", "G4", "B4")),
    ):
        triad_clef = Clef.BASS if root in ("F", "G", "A") else Clef.TREBLE
        groups[5].append(
            CurriculumItem(
                f"triad:{triad_clef}:{root}_{quality}",
                f"{root} {quality} triad • aim below 70ms",
                "sight",
                5,
                clef=triad_clef,
                names=names,
                kind="triad",
            )
        )
    for quality, names in (("maj", ("C4", "E4", "G4")), ("min", ("C4", "Eb4", "G4"))):
        groups[5].append(
            CurriculumItem(
                f"ear:triad:{quality}",
                f"Hear a {quality} triad",
                "ear",
                5,
                names=names,
                kind="ear_triad",
            )
        )
    for name in ("A4", "B4", "C5", "D5", "E5", "F5", "G5", "A5", "B5", "C6"):
        note(6, Clef.TREBLE, name)
    for name in ("C2", "D2", "E2", "F2", "G2", "A2", "B2"):
        note(6, Clef.BASS, name)
    for mode, anchor in (("Am", "A"), ("D_dorian", "D")):
        for clef, octave in ((Clef.TREBLE, 4), (Clef.BASS, 3)):
            groups[6].append(
                CurriculumItem(
                    f"phrase:{clef}:{mode}:steps",
                    f"{clef.title()} {mode.replace('_', ' ')} contour",
                    "sight",
                    6,
                    clef,
                    (f"{anchor}{octave}",),
                    "phrase",
                )
            )
    for key, fifths, names in (
        ("G", 1, ("G4", "A4", "B4", "C5", "D5")),
        ("F", -1, ("F4", "G4", "A4", "Bb4", "C5")),
    ):
        groups[7].append(
            CurriculumItem(
                f"tech:rh:{key}_pentascale",
                f"{key} major evenness",
                "technique",
                7,
                names=names,
                kind="technique",
                key_fifths=fifths,
            )
        )
        for spelling in (("F#4", "F4", "F#4", "G4") if key == "G" else ("Bb4", "B4", "Bb4", "A4"),):
            groups[7].append(
                CurriculumItem(
                    f"phrase:treble:{key}:cancellation",
                    f"{key} major • natural cancellation",
                    "sight",
                    7,
                    names=spelling,
                    kind="ear_note",
                    key_fifths=fifths,
                )
            )
    for key, fifths, names in (
        ("D", 2, ("D4", "E4", "F#4", "G4", "A4")),
        ("Bb", -2, ("Bb3", "C4", "D4", "Eb4", "F4")),
    ):
        for clef in Clef:
            anchors = names[:2]
            if clef == Clef.BASS:
                anchors = tuple(
                    str(NotatedPitch(p.step, p.alter, p.octave - 1)) for p in map(natural, anchors)
                )
            groups[8].append(
                CurriculumItem(
                    f"phrase:{clef}:{key}:steps",
                    f"{key} major {clef} steps",
                    "sight",
                    8,
                    clef,
                    anchors,
                    "phrase",
                    fifths,
                )
            )
    groups[8].extend(
        (
            CurriculumItem(
                "coord:parallel:C",
                "Parallel motion",
                "technique",
                8,
                names=("C4", "D4", "E4", "F4", "G4"),
                kind="technique",
                hand="both",
            ),
            CurriculumItem(
                "coord:contrary:C",
                "Contrary motion",
                "technique",
                8,
                names=("C4", "D4", "E4", "F4", "G4"),
                kind="contrary",
                hand="both",
            ),
            CurriculumItem(
                "coord:ostinato:C", "LH ostinato / RH syncopation", "song", 8, kind="coordination"
            ),
        )
    )
    song_units = (
        ("landmark_waltz", 2),
        ("stepping_stones", 2),
        ("au_clair", 3),
        ("ode_to_joy", 4),
        ("scarborough", 6),
        ("country_dance", 7),
    )
    for song, unit in song_units:
        for hand in ("rh", "lh", "both"):
            groups[unit].append(
                CurriculumItem(
                    f"song:{song}:all:{hand}",
                    f"{song.replace('_', ' ').title()} • {hand.upper()}",
                    "song",
                    unit,
                    kind="song",
                    hand=hand,
                )
            )
    titles = (
        "Landmarks & Pulse",
        "Five-Finger Positions & Evenness",
        "Steps, Skips & Ear Anchors",
        "Fourths, Fifths & Eighths",
        "Triads & Chord Spread",
        "Ledger Range, Minor & Dorian",
        "G Major & F Major",
        "Independent Two-Hand Coordination",
    )
    descriptions = (
        "Find G4, F3, and both middle Cs. Feel the pulse.",
        "Read small contours and explore an even touch.",
        "Read distances, then hear them.",
        "Ground the left hand and divide the beat.",
        "Build major and minor shapes calmly.",
        "Expand to C2..C6 and explore modal melody.",
        "Read key signatures and cancellations.",
        "Combine motion, ostinatos, syncopation, D and Bb major.",
    )
    return tuple(
        CurriculumUnit(i, titles[i - 1], descriptions[i - 1], tuple(groups[i])) for i in range(1, 9)
    )


UNITS = _units()
ITEMS = {item.item_id: item for unit in UNITS for item in unit.items}


@dataclass(frozen=True)
class StudyConfig:
    items: tuple[CurriculumItem, ...]

    def __post_init__(self) -> None:
        if not self.items or len({i.mode for i in self.items}) != 1:
            raise ValueError("A study queue requires items from the same practice mode")


@dataclass(frozen=True)
class ItemSchedule:
    item_id: str
    box: int
    due_at_utc: str
    rolling_accuracy: float
    rolling_median_ms: float
    mastered: bool


def fluent(attempt: Attempt) -> bool:
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


def rebuild_schedule(attempts: list[Attempt]) -> dict[str, ItemSchedule]:
    histories: dict[str, list[Attempt]] = {}
    states: dict[str, ItemSchedule] = {}
    intervals = (
        timedelta(hours=4),
        timedelta(days=1),
        timedelta(days=3),
        timedelta(days=7),
        timedelta(days=21),
    )
    for attempt in attempts:
        history = histories.setdefault(attempt.item_id, [])
        history.append(attempt)
        recent = history[-10:]
        old_box = states[attempt.item_id].box if attempt.item_id in states else 1
        clean = attempt.is_first_try_correct
        quick = fluent(attempt)
        box = min(5, old_box + 1) if clean and quick else old_box if clean else 1
        delay = intervals[box - 1] if clean and quick else intervals[0]
        accuracy = sum(a.is_first_try_correct for a in recent) / len(recent)
        responses = [a.response_ms for a in recent if a.response_ms is not None]
        latency = float(median(responses)) if responses else 0.0
        if attempt.mode in ("rhythm", "technique", "song"):
            mastery = len(recent) == 10 and accuracy >= 0.9 and sum(fluent(a) for a in recent) >= 9
        else:
            # Evaluate fluency using the median over the same most-recent ten attempts.
            synthetic = Attempt(
                "", attempt.mode, attempt.item_id, (), (), True, 0, latency if responses else None
            )
            mastery = len(recent) == 10 and accuracy >= 0.9 and fluent(synthetic)
        timestamp = datetime.fromisoformat(attempt.timestamp_utc).astimezone(UTC)
        states[attempt.item_id] = ItemSchedule(
            attempt.item_id, box, (timestamp + delay).isoformat(), accuracy, latency, mastery
        )
    return states


def recommended_unit(states: dict[str, ItemSchedule]) -> int:
    for unit in UNITS:
        mastered = sum(states[i.item_id].mastered for i in unit.items if i.item_id in states)
        if mastered / max(1, len(unit.items)) < 0.8:
            return unit.number
    return 8
