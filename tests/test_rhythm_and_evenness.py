import pytest

from consonance.core.rhythm import (
    DurationGrade,
    ExpectedStrike,
    Grade,
    TimedGrader,
    attack_grade,
    duration_grade,
)
from consonance.core.technique import measure_evenness


@pytest.mark.parametrize(
    "error,grade",
    [
        (35, Grade.PERFECT),
        (-35, Grade.PERFECT),
        (75, Grade.GOOD),
        (135, Grade.LATE_OR_EARLY),
        (136, Grade.MISS),
    ],
)
def test_attack_windows(error: float, grade: Grade) -> None:
    assert attack_grade(error) == grade


def test_offset_misses_strays_and_holds() -> None:
    grader = TimedGrader((ExpectedStrike(60, 1, 0.5), ExpectedStrike(62, 2, 1)), 20)
    hit = grader.strike(60, 1.055)
    assert hit.grade == Grade.PERFECT
    assert hit.error_ms == pytest.approx(35)
    grader.release(60, 1.055, 1.555)
    assert grader.holds[0] == DurationGrade.OK
    assert grader.strike(61, 1.1).grade == Grade.STRAY
    grader.advance_to(2.2)
    assert grader.hits[1].grade == Grade.MISS
    assert duration_grade(380, 500) == DurationGrade.OK
    assert duration_grade(349, 500) == DurationGrade.SHORT
    assert duration_grade(1400, 1000) == DurationGrade.LONG


def test_evenness_math() -> None:
    result = measure_evenness((0, 0.5, 1, 1.5), (60, 80, 60, 80))
    assert result.ioi_sd_ms == 0
    assert result.velocity_sd == 10
    assert result.label == "Excellent"
