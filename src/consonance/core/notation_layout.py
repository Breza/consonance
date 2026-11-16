"""Vector layout in staff spaces. Treble bottom E4 is y=4; bass G2 is y=14."""

from dataclasses import dataclass, replace
from fractions import Fraction

from consonance.core.notation import (
    Clef,
    KeySignature,
    MeasureAccidentalState,
    NotatedAtom,
    NotatedPitch,
    TimeSignature,
)


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.10


@dataclass(frozen=True)
class Glyph:
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class Head:
    x: float
    y: float
    hollow: bool
    whole: bool
    label: str
    finger: int | None = None


@dataclass(frozen=True)
class StaffLayout:
    lines: tuple[Line, ...]
    glyphs: tuple[Glyph, ...]
    heads: tuple[Head, ...]
    dots: tuple[tuple[float, float], ...]
    width: float


def pitch_y(pitch: NotatedPitch, clef: Clef) -> float:
    reference = 4 * 7 + 2 if clef == Clef.TREBLE else 2 * 7 + 4
    bottom = 4.0 if clef == Clef.TREBLE else 14.0
    return bottom - (pitch.diatonic - reference) / 2


def layout_staff(
    right: tuple[NotatedAtom, ...],
    left: tuple[NotatedAtom, ...] = (),
    key: KeySignature = KeySignature(),
    time: TimeSignature = TimeSignature(),
    width: float = 64.0,
) -> StaffLayout:
    lines = [Line(0, y, width, y) for y in (0.0, 1.0, 2.0, 3.0, 4.0, 10.0, 11.0, 12.0, 13.0, 14.0)]
    lines.extend([Line(0, 0, 0, 14, 0.16), Line(width, 0, width, 14, 0.16)])
    glyphs = [Glyph("TrebleClef", 1, 3), Glyph("BassClef", 1, 11)]
    heads: list[Head] = []
    dots: list[tuple[float, float]] = []
    for clef, offset in ((Clef.TREBLE, 0.0), (Clef.BASS, 10.0)):
        for index, step in enumerate(("F", "C")[: max(0, key.fifths)]):
            y = (0 if step == "F" else 1.5) + (1 if clef == Clef.BASS else 0)
            glyphs.append(Glyph("Sharp", 4.5 + index, offset + y))
        for index, step in enumerate(("B", "E")[: max(0, -key.fifths)]):
            y = (2 if step == "B" else 0.5) + (1 if clef == Clef.BASS else 0)
            glyphs.append(Glyph("Flat", 4.5 + index, offset + y))
        glyphs.extend([Glyph(str(time.numerator), 7, offset + 1), Glyph("4", 7, offset + 3)])
        state = MeasureAccidentalState(key)
        beat = Fraction(0)
        beam: tuple[float, float, int] | None = None
        atoms = right if clef == Clef.TREBLE else left
        for atom in atoms:
            x = 11 + float(beat / time.beats) * (width - 14)
            center = offset + 2
            ys = [pitch_y(p, clef) for p in atom.pitches]
            up = sum(ys) / len(ys) >= center if ys else True
            displaced: set[int] = set()
            order = sorted(range(len(ys)), key=lambda i: ys[i], reverse=up)
            for previous, current in zip(order, order[1:], strict=False):
                if abs(ys[previous] - ys[current]) == 0.5 and previous not in displaced:
                    displaced.add(current)
            if not atom.pitches:
                names = {
                    Fraction(4): "WholeRest",
                    Fraction(3): "HalfRest",
                    Fraction(2): "HalfRest",
                    Fraction(3, 2): "QuarterRest",
                    Fraction(1): "QuarterRest",
                    Fraction(1, 2): "EighthRest",
                }
                glyphs.append(Glyph(names[atom.duration], x, center))
                beam = None
            for index, pitch in enumerate(atom.pitches):
                y = pitch_y(pitch, clef)
                head_x = x + ((1.1 if up else -1.1) if index in displaced else 0)
                heads.append(
                    Head(
                        head_x,
                        y,
                        atom.duration >= 2,
                        atom.duration == 4,
                        str(pitch),
                        atom.fingering[index] if atom.fingering else None,
                    )
                )
                accidental = state.display(pitch)
                if accidental:
                    glyphs.append(Glyph(accidental, x - 1.5 - index * 0.4, y))
                if y <= offset - 1:
                    lines.extend(
                        Line(x - 0.85, float(v), x + 0.85, float(v))
                        for v in range(int(offset - 1), int(y) - 1, -1)
                    )
                if y >= offset + 5:
                    lines.extend(
                        Line(x - 0.85, float(v), x + 0.85, float(v))
                        for v in range(int(offset + 5), int(y) + 1)
                    )
            if atom.pitches and atom.duration != 4:
                ys = [pitch_y(p, clef) for p in atom.pitches]
                up = sum(ys) / len(ys) >= center
                stem_x = x + (0.55 if up else -0.55)
                end = (min(ys) - 3.5) if up else (max(ys) + 3.5)
                lines.append(Line(stem_x, max(ys) if up else min(ys), stem_x, end))
                if atom.duration == Fraction(1, 2):
                    if beam is not None and int(beat) == beam[2]:
                        lines.append(Line(beam[0], beam[1], stem_x, end, 0.45))
                        glyphs = [
                            g
                            for g in glyphs
                            if not (g.name.startswith("EighthFlag") and g.x == beam[0])
                        ]
                        beam = None
                    else:
                        beam = (stem_x, end, int(beat))
                        glyphs.append(Glyph("EighthFlag" if up else "EighthFlagDown", stem_x, end))
                else:
                    beam = None
            if atom.duration in (Fraction(3), Fraction(3, 2)):
                y = pitch_y(atom.pitches[0], clef) if atom.pitches else center
                dots.append((x + 1.1, y if y % 1 else y - 0.5))
            beat += atom.duration
    return StaffLayout(tuple(lines), tuple(glyphs), tuple(heads), tuple(dots), width)


def layout_measures(
    measures: tuple[tuple[tuple[NotatedAtom, ...], tuple[NotatedAtom, ...]], ...],
    key: KeySignature = KeySignature(),
    time: TimeSignature = TimeSignature(),
) -> StaffLayout:
    layouts = [layout_staff(rh, lh, key, time, width=48) for rh, lh in measures]
    return StaffLayout(
        tuple(
            replace(line, x1=line.x1 + i * 48, x2=line.x2 + i * 48)
            for i, layout in enumerate(layouts)
            for line in layout.lines
        ),
        tuple(
            replace(g, x=g.x + i * 48) for i, layout in enumerate(layouts) for g in layout.glyphs
        ),
        tuple(replace(h, x=h.x + i * 48) for i, layout in enumerate(layouts) for h in layout.heads),
        tuple((x + i * 48, y) for i, layout in enumerate(layouts) for x, y in layout.dots),
        len(layouts) * 48.0,
    )
