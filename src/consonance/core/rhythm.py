"""One attack rubric for rhythm and songs; damper-aware duration assessment."""

from dataclasses import dataclass
from enum import StrEnum
from statistics import mean, pstdev


class Grade(StrEnum):
    PERFECT = "PERFECT"
    GOOD = "GOOD"
    LATE_OR_EARLY = "LATE_OR_EARLY"
    MISS = "MISS"
    STRAY = "STRAY"


class DurationGrade(StrEnum):
    OK = "DURATION_OK"
    SHORT = "TOO_SHORT"
    LONG = "TOO_LONG"


def attack_grade(error_ms: float) -> Grade:
    error = abs(error_ms)
    return (
        Grade.PERFECT
        if error <= 35.00000001
        else Grade.GOOD
        if error <= 75.00000001
        else Grade.LATE_OR_EARLY
        if error <= 135.00000001
        else Grade.MISS
    )


def duration_grade(actual_ms: float, expected_ms: float) -> DurationGrade:
    tolerance = max(120.0, 0.30 * expected_ms)
    if abs(actual_ms - expected_ms) <= tolerance + 1e-8:
        return DurationGrade.OK
    return DurationGrade.SHORT if actual_ms < expected_ms else DurationGrade.LONG


@dataclass(frozen=True)
class ExpectedStrike:
    pitch: int
    at: float
    duration: float


@dataclass(frozen=True)
class TimedHit:
    index: int | None
    grade: Grade
    error_ms: float | None
    actual: float | None


class TimedGrader:
    def __init__(self, expected: tuple[ExpectedStrike, ...], judge_offset_ms: float = 0) -> None:
        self.expected = expected
        self.offset_s = judge_offset_ms / 1000
        self.hits: dict[int, TimedHit] = {}
        self.strays: list[TimedHit] = []
        self.holds: dict[int, DurationGrade] = {}
        self.hold_ms: dict[int, float] = {}

    def strike(self, pitch: int, timestamp: float) -> TimedHit:
        actual = timestamp - self.offset_s
        candidates = [
            i
            for i, note in enumerate(self.expected)
            if i not in self.hits and note.pitch == pitch and abs(actual - note.at) <= 0.13500000001
        ]
        if not candidates:
            hit = TimedHit(None, Grade.STRAY, None, timestamp)
            self.strays.append(hit)
            return hit
        index = min(candidates, key=lambda i: abs(actual - self.expected[i].at))
        error = (actual - self.expected[index].at) * 1000
        hit = TimedHit(index, attack_grade(error), error, timestamp)
        self.hits[index] = hit
        return hit

    def release(self, pitch: int, started: float, ended: float) -> None:
        for i, hit in self.hits.items():
            if hit.actual == started and self.expected[i].pitch == pitch and i not in self.holds:
                self.hold_ms[i] = (ended - started) * 1000
                self.holds[i] = duration_grade(self.hold_ms[i], self.expected[i].duration * 1000)

    def advance_to(self, now: float) -> None:
        for i, note in enumerate(self.expected):
            if i not in self.hits and now - self.offset_s > note.at + 0.135:
                self.hits[i] = TimedHit(i, Grade.MISS, None, None)

    @property
    def accuracy(self) -> float:
        good = sum(h.grade != Grade.MISS for h in self.hits.values())
        return good / max(1, len(self.expected) + len(self.strays))

    @property
    def mean_error_ms(self) -> float:
        errors = [h.error_ms for h in self.hits.values() if h.error_ms is not None]
        return mean(errors) if errors else 0.0

    @property
    def jitter_ms(self) -> float:
        errors = [h.error_ms for h in self.hits.values() if h.error_ms is not None]
        return pstdev(errors) if len(errors) >= 2 else 0.0
