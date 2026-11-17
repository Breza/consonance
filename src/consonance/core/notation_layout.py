"""Vector layout in staff spaces. Treble bottom line E4 is y=4; bass bottom line G2 is y=14.

A layout is one grand-staff system. Clefs, key signature and time signature live in a
separate ``header`` so that a view can keep them pinned while the music scrolls beneath.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from consonance.core.fingering import position_anchor
from consonance.core.notation import (
    Clef,
    Hand,
    KeySignature,
    MeasureAccidentalState,
    NotatedAtom,
    NotatedPitch,
    TimeSignature,
)

BEAT_WIDTH = 8.5
PAD_LEFT = 3.0
PAD_RIGHT = 0.6
CARD_SLOT = 7.5
STEM = 3.5
STAFF_OFFSETS = {Clef.TREBLE: 0.0, Clef.BASS: 10.0}
STAFF_LINES = (0.0, 1.0, 2.0, 3.0, 4.0, 10.0, 11.0, 12.0, 13.0, 14.0)
REST_NAMES = {
    Fraction(4): "WholeRest",
    Fraction(3): "HalfRest",
    Fraction(2): "HalfRest",
    Fraction(3, 2): "QuarterRest",
    Fraction(1): "QuarterRest",
    Fraction(1, 2): "EighthRest",
}

type HandMeasure = tuple[tuple[NotatedAtom, ...], tuple[NotatedAtom, ...]]


@dataclass(frozen=True)
class Line:
    """A straight stroke: staff line, barline, stem, ledger line, or beam."""

    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.10


@dataclass(frozen=True)
class Glyph:
    """A named vector symbol placed at a staff-space coordinate."""

    name: str
    x: float
    y: float


@dataclass(frozen=True)
class Head:
    """A notehead plus what a view needs to label, colour, and match it to input."""

    x: float
    y: float
    hollow: bool
    whole: bool
    label: str
    finger: int | None = None
    index: int = 0
    beat: float = 0.0
    midi: int = 0
    staff: int = 0
    finger_start: bool = False
    text_y: float = 0.0


@dataclass(frozen=True)
class Label:
    """A short piece of ordinary text, such as a measure number."""

    x: float
    y: float
    text: str


@dataclass(frozen=True)
class StaffLayout:
    """Everything needed to draw one system, in staff-space units."""

    lines: tuple[Line, ...]
    glyphs: tuple[Glyph, ...]
    heads: tuple[Head, ...]
    dots: tuple[tuple[float, float], ...]
    width: float
    header: tuple[Glyph, ...] = ()
    header_width: float = 0.0
    labels: tuple[Label, ...] = ()
    origin: float = 0.0
    beat_width: float = BEAT_WIDTH
    measure_width: float = 0.0
    measure_beats: float = 4.0
    measures: int = 1
    top: float = -4.0
    bottom: float = 18.0

    def x_at(self, beat: float) -> float:
        """Return the x coordinate at which a beat (or untimed prompt index) is drawn."""
        if self.measure_width <= 0 or self.measure_beats <= 0:
            return self.origin + beat * self.beat_width
        measure = min(max(int(beat // self.measure_beats), 0), self.measures - 1)
        inside = beat - measure * self.measure_beats
        return self.origin + measure * self.measure_width + inside * self.beat_width


def pitch_y(pitch: NotatedPitch, clef: Clef) -> float:
    """Return the vertical staff position of a pitch in a clef (lines are integers)."""
    reference = 4 * 7 + 2 if clef == Clef.TREBLE else 2 * 7 + 4
    bottom = 4.0 if clef == Clef.TREBLE else 14.0
    return bottom - (pitch.diatonic - reference) / 2


@dataclass
class _Placed:
    """An atom with its drawing position resolved."""

    atom: NotatedAtom
    x: float
    beat: Fraction
    absolute_beat: float
    index: int


class _Canvas:
    """Mutable accumulation of drawing primitives while a system is laid out."""

    def __init__(self) -> None:
        """Start an empty drawing."""
        self.lines: list[Line] = []
        self.glyphs: list[Glyph] = []
        self.heads: list[Head] = []
        self.dots: list[tuple[float, float]] = []
        self.labels: list[Label] = []
        self.anchors: dict[Clef, int | None] = {Clef.TREBLE: None, Clef.BASS: None}
        self.counts: dict[Clef, int] = {Clef.TREBLE: 0, Clef.BASS: 0}


def _header(key: KeySignature, time: TimeSignature | None) -> tuple[tuple[Glyph, ...], float]:
    """Lay out clefs, key signature and optional time signature; return them and their width."""
    glyphs = [Glyph("TrebleClef", 1, 3), Glyph("BassClef", 1, 11)]
    for clef, offset in STAFF_OFFSETS.items():
        lower = 1 if clef == Clef.BASS else 0
        for index, step in enumerate(("F", "C")[: max(0, key.fifths)]):
            glyphs.append(Glyph("Sharp", 4.5 + index, offset + (0 if step == "F" else 1.5) + lower))
        for index, step in enumerate(("B", "E")[: max(0, -key.fifths)]):
            glyphs.append(Glyph("Flat", 4.5 + index, offset + (2 if step == "B" else 0.5) + lower))
        if time is not None:
            glyphs.append(Glyph(str(time.numerator), 7, offset + 1))
            glyphs.append(Glyph(str(time.denominator), 7, offset + 3))
    width = 9.5 if time is not None else 5.0 + abs(key.fifths)
    return tuple(glyphs), width


def _stem_up(ys: Sequence[float], center: float) -> bool:
    """Choose a stem direction: notes below the middle line point up."""
    far = max(ys, key=lambda y: abs(y - center))
    return far > center


def _stem_end(ys: Sequence[float], up: bool, center: float) -> float:
    """Return where a stem finishes, reaching at least the middle line."""
    return min(min(ys) - STEM, center) if up else max(max(ys) + STEM, center)


def _beam_partners(placed: Sequence[_Placed]) -> dict[int, int]:
    """Pair neighbouring eighth notes that share a beat so they can be beamed together."""
    partner: dict[int, int] = {}
    for i in range(len(placed) - 1):
        a, b = placed[i], placed[i + 1]
        if (
            i not in partner
            and a.atom.pitches
            and b.atom.pitches
            and a.atom.duration == b.atom.duration == Fraction(1, 2)
            and a.beat.denominator == 1
        ):
            partner[i] = i + 1
            partner[i + 1] = i
    return partner


def _draw_rest(
    canvas: _Canvas,
    item: _Placed,
    center: float,
    full_rest_x: float | None,
    measure_beats: Fraction | None,
    alone: bool,
) -> None:
    """Draw a rest; a rest that fills the measure is a centred whole rest in any meter."""
    duration = item.atom.duration
    if alone and full_rest_x is not None and duration == measure_beats:
        canvas.glyphs.append(Glyph("WholeRest", full_rest_x, center))
        return
    canvas.glyphs.append(Glyph(REST_NAMES[duration], item.x, center))
    if duration in (Fraction(3), Fraction(3, 2)):
        canvas.dots.append((item.x + 1.1, center - 0.5))


def _text_base(ys: Sequence[float], clef: Clef, offset: float, tip: float | None) -> float:
    """Return how far outside the staff a note's finger number or name must sit."""
    if clef == Clef.TREBLE:
        highest = min(min(ys), tip) if tip is not None else min(ys)
        return min(offset - 1.5, highest - 1.3)
    lowest = max(max(ys), tip) if tip is not None else max(ys)
    return max(offset + 6.4, lowest + 2.2)


def _text_rows(ys: Sequence[float], clef: Clef, base: float) -> list[float]:
    """Stack one text row per chord note, outward from a shared baseline.

    Treble text sits above the staff with the highest note on top; bass text sits below
    with the lowest note at the bottom, as printed piano music does.
    """
    count = range(len(ys))
    if clef == Clef.TREBLE:
        ranks = {n: rank for rank, n in enumerate(sorted(count, key=lambda n: -ys[n]))}
        return [base - ranks[n] * 1.35 for n in count]
    ranks = {n: rank for rank, n in enumerate(sorted(count, key=lambda n: ys[n]))}
    return [base + ranks[n] * 1.35 for n in count]


def _draw_staff(
    canvas: _Canvas,
    placed: Sequence[_Placed],
    clef: Clef,
    state: MeasureAccidentalState,
    full_rest_x: float | None,
    measure_beats: Fraction | None,
) -> None:
    """Draw one staff's atoms for one measure (or one untimed card) onto the canvas."""
    offset = STAFF_OFFSETS[clef]
    center = offset + 2
    hand = Hand.RIGHT if clef == Clef.TREBLE else Hand.LEFT
    ys_of = [[pitch_y(p, clef) for p in item.atom.pitches] for item in placed]
    partner = _beam_partners(placed)
    directions = {i: _stem_up([*ys_of[i], *ys_of[j]], center) for i, j in partner.items()}
    # Every finger number in a measure shares one baseline so the row reads as a line.
    bases = []
    for i, item in enumerate(placed):
        if item.atom.pitches:
            up = directions.get(i, _stem_up(ys_of[i], center))
            reaches = item.atom.duration != 4 and up == (clef == Clef.TREBLE)
            tip = _stem_end(ys_of[i], up, center) if reaches else None
            bases.append(_text_base(ys_of[i], clef, offset, tip))
    text_base = (min if clef == Clef.TREBLE else max)(bases, default=0.0)
    stems: dict[int, tuple[float, float, bool]] = {}
    for i, item in enumerate(placed):
        atom, x, ys = item.atom, item.x, ys_of[i]
        if not atom.pitches:
            _draw_rest(canvas, item, center, full_rest_x, measure_beats, len(placed) == 1)
            continue
        up = directions.get(i, _stem_up(ys, center))
        order = sorted(range(len(ys)), key=lambda n: ys[n], reverse=up)
        displaced: set[int] = set()
        for previous, current in zip(order, order[1:], strict=False):
            if abs(ys[previous] - ys[current]) == 0.5 and previous not in displaced:
                displaced.add(current)
        head_xs = [x + ((1.1 if up else -1.1) if n in displaced else 0.0) for n in range(len(ys))]
        has_stem = atom.duration != 4
        end = _stem_end(ys, up, center)
        text_ys = _text_rows(ys, clef, text_base)
        lowest_note = max(range(len(ys)), key=lambda n: ys[n])
        starts = False
        if atom.fingering:
            anchor = position_anchor(atom.pitches[lowest_note], atom.fingering[lowest_note], hand)
            starts = canvas.anchors[clef] != anchor
            canvas.anchors[clef] = anchor
        for n, pitch in enumerate(atom.pitches):
            y = ys[n]
            canvas.heads.append(
                Head(
                    head_xs[n],
                    y,
                    atom.duration >= 2,
                    atom.duration == 4,
                    str(pitch),
                    atom.fingering[n] if atom.fingering else None,
                    item.index,
                    item.absolute_beat,
                    pitch.midi,
                    0 if clef == Clef.TREBLE else 1,
                    starts,
                    text_ys[n],
                )
            )
            accidental = state.display(pitch)
            if accidental:
                canvas.glyphs.append(Glyph(accidental, min(head_xs) - 2.0 - n * 0.4, y))
            if y <= offset - 1:
                canvas.lines.extend(
                    Line(head_xs[n] - 0.95, float(v), head_xs[n] + 0.95, float(v))
                    for v in range(int(offset - 1), math.ceil(y) - 1, -1)
                )
            if y >= offset + 5:
                canvas.lines.extend(
                    Line(head_xs[n] - 0.95, float(v), head_xs[n] + 0.95, float(v))
                    for v in range(int(offset + 5), math.floor(y) + 1)
                )
            if atom.duration in (Fraction(3), Fraction(3, 2)):
                canvas.dots.append((max(head_xs) + 1.1, y if y % 1 else y - 0.5))
        if not has_stem:
            continue
        stem_x = x + (0.55 if up else -0.55)
        stems[i] = (stem_x, end, up)
        if i in partner and partner[i] < i:
            first_x, first_end, _ = stems[partner[i]]
            if abs(first_end - end) > 1:
                first_end = end = min(first_end, end) if up else max(first_end, end)
                stems[partner[i]] = (first_x, first_end, up)
                stems[i] = (stem_x, end, up)
            canvas.lines.append(Line(first_x, first_end, stem_x, end, 0.45))
        elif atom.duration == Fraction(1, 2) and i not in partner:
            canvas.glyphs.append(Glyph("EighthFlag" if up else "EighthFlagDown", stem_x, end))
    for i, (stem_x, end, up) in stems.items():
        canvas.lines.append(Line(stem_x, max(ys_of[i]) if up else min(ys_of[i]), stem_x, end))


def _finish(
    canvas: _Canvas,
    width: float,
    header: tuple[Glyph, ...],
    header_width: float,
    origin: float,
    beat_width: float,
    measure_width: float,
    measure_beats: float,
    measures: int,
) -> StaffLayout:
    """Add the staff lines and opening barline, then freeze the canvas into a layout."""
    lines = [Line(0, y, width, y) for y in STAFF_LINES]
    lines.append(Line(0, 0, 0, 14, 0.16))
    lines.extend(canvas.lines)
    text_ys = [head.text_y for head in canvas.heads]
    head_ys = [head.y for head in canvas.heads]
    return StaffLayout(
        tuple(lines),
        tuple(canvas.glyphs),
        tuple(canvas.heads),
        tuple(canvas.dots),
        width,
        header,
        header_width,
        tuple(canvas.labels),
        origin,
        beat_width,
        measure_width,
        measure_beats,
        measures,
        min([-4.0, *(y - 1.6 for y in text_ys), *(y - 1.5 for y in head_ys)]),
        max([18.0, *(y + 0.8 for y in text_ys), *(y + 1.5 for y in head_ys)]),
    )


def layout_measures(
    measures: Sequence[HandMeasure],
    key: KeySignature = KeySignature(),
    time: TimeSignature = TimeSignature(),
    *,
    beat_width: float = BEAT_WIDTH,
    numbers: bool = False,
    final_bar: bool = False,
) -> StaffLayout:
    """Lay out consecutive measures as one system with a single clef/key/time header.

    A hand given as an empty tuple leaves that staff blank; a hand that is one rest lasting
    the whole measure is drawn as a centred whole-measure rest.
    """
    header, header_width = _header(key, time)
    beats = time.beats
    measure_width = PAD_LEFT + float(beats) * beat_width + PAD_RIGHT
    canvas = _Canvas()
    for number, (right, left) in enumerate(measures):
        left_edge = header_width + number * measure_width
        if number:
            canvas.lines.append(Line(left_edge, 0, left_edge, 14, 0.12))
        if numbers:
            canvas.labels.append(Label(left_edge + 0.35, -0.75, str(number + 1)))
        for clef, atoms in ((Clef.TREBLE, right), (Clef.BASS, left)):
            placed: list[_Placed] = []
            beat = Fraction(0)
            for atom in atoms:
                index = canvas.counts[clef]
                if atom.pitches:
                    canvas.counts[clef] += 1
                x = left_edge + PAD_LEFT + float(beat) * beat_width
                placed.append(_Placed(atom, x, beat, float(number * beats + beat), index))
                beat += atom.duration
            state = MeasureAccidentalState(key)
            _draw_staff(canvas, placed, clef, state, left_edge + measure_width / 2, beats)
    count = max(1, len(measures))
    width = header_width + count * measure_width
    if final_bar:
        canvas.lines.append(Line(width - 0.55, 0, width - 0.55, 14, 0.12))
        canvas.lines.append(Line(width - 0.12, 0, width - 0.12, 14, 0.42))
    else:
        canvas.lines.append(Line(width, 0, width, 14, 0.16))
    return _finish(
        canvas,
        width,
        header,
        header_width,
        header_width + PAD_LEFT,
        beat_width,
        measure_width,
        float(beats),
        count,
    )


def layout_staff(
    right: tuple[NotatedAtom, ...],
    left: tuple[NotatedAtom, ...] = (),
    key: KeySignature = KeySignature(),
    time: TimeSignature = TimeSignature(),
) -> StaffLayout:
    """Lay out a single measure for one or both hands."""
    return layout_measures(((right, left),), key, time)


def layout_card(
    atoms: Sequence[NotatedAtom],
    clef: Clef,
    key: KeySignature = KeySignature(),
) -> StaffLayout:
    """Lay out an untimed reading prompt: evenly spaced notes and no time signature.

    Accidentals carry across the whole card, exactly as they would inside one measure, so a
    cancelled sharp or flat is shown with its natural sign.
    """
    header, header_width = _header(key, None)
    canvas = _Canvas()
    count = max(1, len(atoms))
    body = max(14.0, count * CARD_SLOT + 4.0)
    slot = (body - 4.0) / count if count > 1 else 0.0
    origin = header_width + (body / 2 if count == 1 else 2.0 + slot / 2)
    placed: list[_Placed] = []
    for position, atom in enumerate(atoms):
        index = canvas.counts[clef]
        if atom.pitches:
            canvas.counts[clef] += 1
        x = origin + position * slot
        placed.append(_Placed(atom, x, Fraction(position), float(position), index))
    _draw_staff(canvas, placed, clef, MeasureAccidentalState(key), None, None)
    width = header_width + body
    canvas.lines.append(Line(width, 0, width, 14, 0.16))
    return _finish(canvas, width, header, header_width, origin, slot, 0.0, float(count), 1)


def group_measures(
    atoms: Sequence[NotatedAtom], time: TimeSignature = TimeSignature()
) -> tuple[tuple[NotatedAtom, ...], ...]:
    """Split a flat run of atoms into measures; a short final measure is kept as written."""
    measures: list[tuple[NotatedAtom, ...]] = []
    group: list[NotatedAtom] = []
    total = Fraction()
    for atom in atoms:
        group.append(atom)
        total += atom.duration
        if total >= time.beats:
            measures.append(tuple(group))
            group, total = [], Fraction()
    if group:
        measures.append(tuple(group))
    return tuple(measures)
