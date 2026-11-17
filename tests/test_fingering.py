from consonance.core.fingering import chord_fingers, finger_part, position_anchor
from consonance.core.notation import Hand, NotatedAtom, natural


def part(source: str, hand: Hand) -> list[tuple[int, ...]]:
    """Finger a space-separated line of notes and chords and return the fingerings."""
    atoms = [NotatedAtom(tuple(natural(p) for p in token.split("+"))) for token in source.split()]
    return [atom.fingering for atom in finger_part(atoms, hand)]


def test_five_finger_positions_in_both_hands() -> None:
    """Verify five finger positions in both hands."""
    assert part("C4 D4 E4 F4 G4 F4 E4 D4 C4", Hand.RIGHT) == [
        (f,) for f in (1, 2, 3, 4, 5, 4, 3, 2, 1)
    ]
    assert part("C3 D3 E3 F3 G3", Hand.LEFT) == [(f,) for f in (5, 4, 3, 2, 1)]
    assert part("G4 A4 B4 C5 D5", Hand.RIGHT) == [(f,) for f in (1, 2, 3, 4, 5)]


def test_chords_put_outer_notes_under_outer_fingers() -> None:
    """Verify chords put outer notes under outer fingers."""
    assert part("C4+E4+G4 C4+G4 C4+E4", Hand.RIGHT) == [(1, 3, 5), (1, 5), (1, 3)]
    assert part("C3+E3+G3 C3+G3", Hand.LEFT) == [(5, 3, 1), (5, 1)]
    # Close-position IV and V chords lean toward the thumb, as the hand does.
    assert chord_fingers(tuple(map(natural, ("C3", "F3", "A3"))), Hand.LEFT) == (5, 2, 1)
    assert chord_fingers(tuple(map(natural, ("E4", "G4", "C5"))), Hand.RIGHT) == (1, 2, 5)
    # Fingers follow the order in which the pitches were written.
    assert chord_fingers((natural("G3"), natural("C3")), Hand.LEFT) == (1, 5)


def test_a_note_outside_the_position_moves_the_hand_once() -> None:
    """Verify a note outside the position moves the hand once."""
    fingers = part("C4 D4 E4 F4 G4 A4 B4 C5", Hand.RIGHT)
    pitches = [natural(n) for n in "C4 D4 E4 F4 G4 A4 B4 C5".split()]
    anchors = [position_anchor(p, f[0], Hand.RIGHT) for p, f in zip(pitches, fingers, strict=True)]
    assert all(1 <= f[0] <= 5 for f in fingers)
    assert len(set(anchors)) == 2
    assert anchors == sorted(anchors)


def test_a_shift_never_reuses_one_finger_on_neighbouring_notes() -> None:
    """Verify a shift never reuses one finger on neighbouring notes."""
    line = "F4 G4 A4 F4 A4 Bb4 C5 C5 D5 C5 Bb4 A4 F4"
    fingers = [f[0] for f in part(line, Hand.RIGHT)]
    pitches = [natural(n).midi for n in line.split()]
    for (a, fa), (b, fb) in zip(
        zip(pitches, fingers, strict=True), zip(pitches[1:], fingers[1:], strict=True), strict=False
    ):
        if abs(a - b) in (1, 2):
            assert fa != fb, (a, b, fa)


def test_written_fingerings_are_kept_and_rests_are_skipped() -> None:
    """Verify written fingerings are kept and rests are skipped."""
    atoms = [
        NotatedAtom((natural("C4"),), fingering=(3,)),
        NotatedAtom(()),
        NotatedAtom((natural("D4"),)),
    ]
    result = finger_part(atoms, Hand.RIGHT)
    assert result[0].fingering == (3,)
    assert result[1].fingering == ()
    assert result[2].fingering == (4,)
