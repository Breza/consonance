from fractions import Fraction

from consonance.core.notation import (
    Clef,
    KeySignature,
    MeasureAccidentalState,
    NotatedAtom,
    TimeSignature,
    natural,
    pitch_class_name,
    pitch_name,
)
from consonance.core.notation_layout import (
    group_measures,
    layout_card,
    layout_measures,
    layout_staff,
    pitch_y,
)


def atom(source: str, duration: float = 1) -> NotatedAtom:
    """Build an atom from ``C4+E4`` style source; ``r`` is a rest."""
    pitches = () if source == "r" else tuple(natural(p) for p in source.split("+"))
    return NotatedAtom(pitches, Fraction(duration))


def test_spelling_and_clefs() -> None:
    """Verify spelling and clefs."""
    assert natural("C#4").midi == natural("Db4").midi
    assert pitch_y(natural("C#4"), Clef.TREBLE) != pitch_y(natural("Db4"), Clef.TREBLE)
    assert pitch_y(natural("C4"), Clef.TREBLE) == 5
    assert pitch_y(natural("C4"), Clef.BASS) == 9
    assert pitch_name(60) == "C4" and pitch_name(66, flats=True) == "Gb4"
    assert pitch_class_name(61, both=True) == "C# / Db"


def test_accidental_cancellation() -> None:
    """Verify accidental cancellation."""
    for key, altered, plain in ((1, "F#4", "F4"), (-1, "Bb3", "B3")):
        state = MeasureAccidentalState(KeySignature(key))
        assert state.display(natural(altered)) is None
        assert state.display(natural(plain)) == "Natural"
        assert state.display(natural(plain)) is None
        assert MeasureAccidentalState(KeySignature(key)).display(natural(altered)) is None


def test_beams_rests_and_dots() -> None:
    """Verify beams rests and dots."""
    atoms = (atom("C4", 0.5), atom("D4", 0.5), atom("r", 3))
    layout = layout_staff(atoms)
    assert any(line.width == 0.45 for line in layout.lines)
    assert not any(g.name.startswith("EighthFlag") for g in layout.glyphs)
    assert any(g.name == "HalfRest" for g in layout.glyphs)
    assert len(layout.dots) == 1


def test_one_header_for_the_whole_system() -> None:
    """Verify one header for the whole system."""
    bar = (atom("C4"), atom("D4"), atom("E4"), atom("F4"))
    rest = (atom("r", 4),)
    layout = layout_measures(((bar, rest), (bar, rest), (bar, rest)), numbers=True)
    assert [g.name for g in layout.header].count("TrebleClef") == 1
    assert [g.name for g in layout.header].count("BassClef") == 1
    assert not any(g.name.endswith("Clef") for g in layout.glyphs)
    assert layout.measures == 3 and [label.text for label in layout.labels] == ["1", "2", "3"]
    # Beats map to the x of the note that sounds on them, in every measure.
    for head in layout.heads:
        assert layout.x_at(head.beat) == head.x
    assert layout.x_at(4.0) - layout.x_at(0.0) == layout.measure_width


def test_a_rest_filling_the_measure_is_a_centred_whole_rest() -> None:
    """Verify a rest filling the measure is a centred whole rest."""
    for beats in (3, 4):
        time = TimeSignature(beats)
        layout = layout_measures((((atom("C4", beats),), (atom("r", beats),)),), time=time)
        rests = [g for g in layout.glyphs if g.name.endswith("Rest")]
        assert [g.name for g in rests] == ["WholeRest"]
        centre = layout.header_width + layout.measure_width / 2
        assert rests[0].x == centre


def test_ledger_lines_stop_at_the_note_in_both_clefs() -> None:
    """Verify ledger lines stop at the note in both clefs."""

    def ledgers(source: str, clef: Clef) -> list[float]:
        """Return the heights of the short ledger lines drawn for one note."""
        layout = layout_card((atom(source),), clef)
        return sorted(line.y1 for line in layout.lines if 0 < line.x2 - line.x1 < 3)

    assert ledgers("C4", Clef.TREBLE) == [5.0]
    assert ledgers("A3", Clef.TREBLE) == [5.0, 6.0]
    assert ledgers("B5", Clef.TREBLE) == [-1.0]
    assert ledgers("C4", Clef.BASS) == [9.0]
    assert ledgers("D4", Clef.BASS) == [9.0]
    assert ledgers("E4", Clef.BASS) == [8.0, 9.0]
    assert ledgers("G4", Clef.TREBLE) == []


def test_beamed_pair_shares_one_stem_direction() -> None:
    """Verify beamed pair shares one stem direction."""
    layout = layout_staff((atom("C4", 0.5), atom("C5", 0.5), atom("r", 3)))
    beam = next(line for line in layout.lines if line.width == 0.45)
    head_ys = [head.y for head in layout.heads]
    assert (beam.y1 < min(head_ys)) == (beam.y2 < min(head_ys))
    assert (beam.y1 > max(head_ys)) == (beam.y2 > max(head_ys))


def test_reading_cards_carry_accidentals_and_have_no_time_signature() -> None:
    """Verify reading cards carry accidentals and have no time signature."""
    names = ("F#4", "F4", "F#4", "G4")
    layout = layout_card(tuple(atom(n) for n in names), Clef.TREBLE, KeySignature(1))
    assert [g.name for g in layout.glyphs] == ["Natural", "Sharp"]
    assert not any(g.name in "234" for g in layout.header)
    assert [head.index for head in layout.heads] == [0, 1, 2, 3]
    xs = [head.x for head in layout.heads]
    assert xs == sorted(xs) and [layout.x_at(i) for i in range(4)] == xs
    single = layout_card((atom("G4"),), Clef.TREBLE)
    assert single.heads[0].x == single.header_width + (single.width - single.header_width) / 2


def test_finger_numbers_mark_position_changes_outside_the_staff() -> None:
    """Verify finger numbers mark position changes outside the staff."""
    right = tuple(
        NotatedAtom((natural(n),), fingering=(f,))
        for n, f in (("C4", 1), ("D4", 2), ("E4", 3), ("A4", 1))
    )
    left = tuple(NotatedAtom((natural(n),), fingering=(f,)) for n, f in (("C3", 5), ("G3", 1)))
    layout = layout_measures(((right, (*left, atom("r", 2))),))
    treble = [h for h in layout.heads if h.staff == 0]
    bass = [h for h in layout.heads if h.staff == 1]
    assert [h.finger_start for h in treble] == [True, False, False, True]
    assert [h.finger_start for h in bass] == [True, False]
    assert all(h.text_y < 0 for h in treble) and all(h.text_y > 14 for h in bass)
    assert len({h.text_y for h in treble}) == 1


def test_grouping_into_measures_keeps_a_short_final_bar() -> None:
    """Verify grouping into measures keeps a short final bar."""
    atoms = [atom("C4")] * 9
    assert [len(bar) for bar in group_measures(atoms)] == [4, 4, 1]
    assert [len(bar) for bar in group_measures(atoms, TimeSignature(3))] == [3, 3, 3]
