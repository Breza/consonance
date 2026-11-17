from fractions import Fraction
from pathlib import Path

import pytest

from consonance.core.builtin_scores import (
    ALL_SCORES,
    BUILTIN_SCORES,
    BuiltinScore,
    score_by_id,
)
from consonance.core.fingering import position_anchor
from consonance.core.notation import Hand, NotatedAtom
from consonance.core.song import SongNote
from consonance.io.smf import MidiImport


def test_every_measure_is_complete_and_timeline_matches() -> None:
    """Verify every measure is complete and timeline matches."""
    assert len(BUILTIN_SCORES) == 12
    assert len(ALL_SCORES) == 13
    assert len({score.song_id for score in ALL_SCORES}) == 13
    for score in ALL_SCORES:
        score.validate()
        timeline = score.compile()
        for measure in score.measures:
            for atoms in (measure.right, measure.left):
                assert sum((a.duration for a in atoms), Fraction()) == score.time.beats
                assert all(1 <= f <= 5 for a in atoms for f in a.fingering)
        assert timeline.end_beat == len(score.measures) * score.time.beats
        assert timeline.measure_count == len(score.measures)
        for i, a in enumerate(timeline.notes):
            for b in timeline.notes[i + 1 :]:
                if a.hand == b.hand and a.start_beat != b.start_beat:
                    assert (
                        a.start_beat + a.duration <= b.start_beat
                        or b.start_beat + b.duration <= a.start_beat
                    )


def test_hands_never_need_the_same_key_at_once() -> None:
    """Verify hands never need the same key at once."""
    for score in ALL_SCORES:
        notes = score.compile().notes
        right = [n for n in notes if n.hand == Hand.RIGHT]
        left = [n for n in notes if n.hand == Hand.LEFT]
        for a in right:
            for b in left:
                overlap = (
                    a.start_beat < b.start_beat + b.duration
                    and b.start_beat < a.start_beat + a.duration
                )
                assert not (a.pitch == b.pitch and overlap), score.song_id


def test_starter_fingerings_are_real_hand_positions() -> None:
    """Verify starter fingerings are real hand positions."""
    for score in ALL_SCORES:
        for hand in (Hand.RIGHT, Hand.LEFT):
            atoms: list[NotatedAtom] = [
                atom
                for measure in score.measures
                for atom in (measure.right if hand == Hand.RIGHT else measure.left)
                if atom.pitches
            ]
            for atom in atoms:
                assert len(set(atom.fingering)) == len(atom.fingering), score.song_id
                ordered = sorted(
                    zip(atom.pitches, atom.fingering, strict=True), key=lambda x: x[0].midi
                )
                fingers = [finger for _, finger in ordered]
                # Higher notes take higher fingers in the right hand, lower ones in the left.
                assert fingers == sorted(fingers, reverse=hand == Hand.LEFT), score.song_id
                span = ordered[-1][0].diatonic - ordered[0][0].diatonic
                if span <= 4:
                    anchors = {position_anchor(p, f, hand) for p, f in ordered}
                    assert len(anchors) == 1, (score.song_id, [str(p) for p in atom.pitches])


def test_left_hand_fifths_use_the_outer_fingers() -> None:
    """Verify left hand fifths use the outer fingers."""
    ode = score_by_id("ode_to_joy")
    assert ode is not None
    assert all(atom.fingering == (5, 1) for m in ode.measures for atom in m.left)
    assert [a.fingering for a in ode.measures[0].right] == [(3,), (3,), (4,), (5,)]


@pytest.mark.parametrize("score", ALL_SCORES, ids=lambda s: s.song_id)
def test_checked_in_demo_midi_matches_the_score(score: BuiltinScore) -> None:
    """Verify checked in demo midi matches the score."""
    builtin = score
    imported = MidiImport(Path("songs/demo") / f"{builtin.song_id}.mid")
    assert [t.name for t in imported.tracks] == ["rh", "lh"]
    hands = {t.index: Hand.RIGHT if t.name == "rh" else Hand.LEFT for t in imported.tracks}
    loaded = imported.timeline(hands)
    expected = builtin.compile()

    def key(note: SongNote) -> tuple[Fraction, Fraction, int, str]:
        """Order notes without regard to how the file happened to store them."""
        return (note.start_beat, note.duration, int(note.pitch), note.hand.value)

    assert sorted(map(key, loaded.notes)) == sorted(map(key, expected.notes))
    assert loaded.time == expected.time
    assert loaded.tempo.points[0].bpm == pytest.approx(expected.tempo.points[0].bpm, abs=0.01)
