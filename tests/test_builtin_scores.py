from fractions import Fraction

from consonance.core.builtin_scores import BUILTIN_SCORES


def test_every_measure_is_complete_and_timeline_matches() -> None:
    assert len(BUILTIN_SCORES) == 6
    for score in BUILTIN_SCORES:
        score.validate()
        timeline = score.compile()
        for measure in score.measures:
            for atoms in (measure.right, measure.left):
                assert sum((a.duration for a in atoms), Fraction()) == score.time.beats
                assert all(1 <= f <= 5 for a in atoms for f in a.fingering)
        assert timeline.end_beat == len(score.measures) * score.time.beats
        for i, a in enumerate(timeline.notes):
            for b in timeline.notes[i + 1 :]:
                if a.hand == b.hand and a.start_beat != b.start_beat:
                    assert (
                        a.start_beat + a.duration <= b.start_beat
                        or b.start_beat + b.duration <= a.start_beat
                    )
