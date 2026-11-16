from fractions import Fraction

from consonance.core.notation import (
    Clef,
    KeySignature,
    MeasureAccidentalState,
    NotatedAtom,
    natural,
)
from consonance.core.notation_layout import layout_staff, pitch_y


def test_spelling_and_clefs() -> None:
    assert natural("C#4").midi == natural("Db4").midi
    assert pitch_y(natural("C#4"), Clef.TREBLE) != pitch_y(natural("Db4"), Clef.TREBLE)
    assert pitch_y(natural("C4"), Clef.TREBLE) == 5
    assert pitch_y(natural("C4"), Clef.BASS) == 9


def test_accidental_cancellation() -> None:
    for key, altered, plain in ((1, "F#4", "F4"), (-1, "Bb3", "B3")):
        state = MeasureAccidentalState(KeySignature(key))
        assert state.display(natural(altered)) is None
        assert state.display(natural(plain)) == "Natural"
        assert state.display(natural(plain)) is None
        assert MeasureAccidentalState(KeySignature(key)).display(natural(altered)) is None


def test_beams_rests_and_dots() -> None:
    atoms = (
        NotatedAtom((natural("C4"),), Fraction(1, 2)),
        NotatedAtom((natural("D4"),), Fraction(1, 2)),
        NotatedAtom((), Fraction(3)),
    )
    layout = layout_staff(atoms)
    assert any(line.width == 0.45 for line in layout.lines)
    assert not any(g.name.startswith("EighthFlag") for g in layout.glyphs)
    assert any(g.name == "HalfRest" for g in layout.glyphs)
    assert len(layout.dots) == 1
