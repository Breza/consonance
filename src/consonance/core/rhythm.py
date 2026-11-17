"""One attack rubric for rhythm and songs; damper-aware duration assessment."""

from dataclasses import dataclass
from enum import StrEnum
from statistics import mean, pstdev

PERFECT_MS = 35.0
GOOD_MS = 75.0
WINDOW_MS = 135.0


class Grade(StrEnum):
    """How an attack compared with the moment it was expected."""

    PERFECT = "PERFECT"
    GOOD = "GOOD"
    LATE_OR_EARLY = "LATE_OR_EARLY"
    MISS = "MISS"
    STRAY = "STRAY"


class DurationGrade(StrEnum):
    """How long a note was held compared with its written length."""

    OK = "DURATION_OK"
    SHORT = "TOO_SHORT"
    LONG = "TOO_LONG"


def attack_grade(error_ms: float) -> Grade:
    """Grade a signed timing error against the shared 35/75/135 ms windows."""
    error = abs(error_ms)
    return (
        Grade.PERFECT
        if error <= PERFECT_MS + 1e-8
        else Grade.GOOD
        if error <= GOOD_MS + 1e-8
        else Grade.LATE_OR_EARLY
        if error <= WINDOW_MS + 1e-8
        else Grade.MISS
    )


def duration_grade(actual_ms: float, expected_ms: float) -> DurationGrade:
    """Grade a hold, tolerating the larger of 120 ms and 30% of the written length."""
    tolerance = max(120.0, 0.30 * expected_ms)
    if abs(actual_ms - expected_ms) <= tolerance + 1e-8:
        return DurationGrade.OK
    return DurationGrade.SHORT if actual_ms < expected_ms else DurationGrade.LONG


def describe_attack(grade: Grade, error_ms: float | None) -> str:
    """Put an attack grade into words a player can act on."""
    if grade == Grade.STRAY:
        return "Extra note"
    if grade == Grade.MISS or error_ms is None:
        return "Missed"
    side = "early" if error_ms < 0 else "late"
    amount = f"{abs(error_ms):.0f} ms {side}"
    if grade == Grade.PERFECT:
        return f"Perfect • {amount}" if abs(error_ms) >= 10 else "Perfect"
    if grade == Grade.GOOD:
        return f"Good • {amount}"
    return f"{side.title()} • {amount}"


def mark_for(grade: Grade) -> str:
    """Map an attack grade onto the note state a view colours."""
    return {Grade.PERFECT: "hit", Grade.GOOD: "hit", Grade.LATE_OR_EARLY: "near"}.get(grade, "miss")


@dataclass(frozen=True)
class ExpectedStrike:
    """A note that should be attacked at a wall-clock time and held for a duration."""

    pitch: int
    at: float
    duration: float


@dataclass(frozen=True)
class TimedHit:
    """The outcome of one attack, matched to an expected strike where possible."""

    index: int | None
    grade: Grade
    error_ms: float | None
    actual: float | None
    pitch: int | None = None


class TimedGrader:
    """Match incoming attacks to expected strikes and grade their timing and holds.

    With ``any_pitch`` only the timing matters, so a rhythm can be tapped on any key.
    """

    def __init__(
        self,
        expected: tuple[ExpectedStrike, ...],
        judge_offset_ms: float = 0,
        *,
        any_pitch: bool = False,
    ) -> None:
        """Prepare to grade against ``expected``; the offset is subtracted from input times."""
        self.expected = expected
        self.offset_s = judge_offset_ms / 1000
        self.any_pitch = any_pitch
        self.hits: dict[int, TimedHit] = {}
        self.strays: list[TimedHit] = []
        self.holds: dict[int, DurationGrade] = {}
        self.hold_ms: dict[int, float] = {}

    def strike(self, pitch: int, timestamp: float) -> TimedHit:
        """Grade one attack against the nearest unclaimed expected strike in its window."""
        actual = timestamp - self.offset_s
        window = WINDOW_MS / 1000 + 1e-11
        candidates = [
            i
            for i, note in enumerate(self.expected)
            if i not in self.hits
            and (self.any_pitch or note.pitch == pitch)
            and abs(actual - note.at) <= window
        ]
        if not candidates:
            hit = TimedHit(None, Grade.STRAY, None, timestamp, pitch)
            self.strays.append(hit)
            return hit
        index = min(candidates, key=lambda i: abs(actual - self.expected[i].at))
        error = (actual - self.expected[index].at) * 1000
        hit = TimedHit(index, attack_grade(error), error, timestamp, pitch)
        self.hits[index] = hit
        return hit

    def release(self, pitch: int, started: float, ended: float) -> None:
        """Grade the length of the hold that began with the attack at ``started``."""
        for i, hit in self.hits.items():
            if hit.actual == started and hit.pitch == pitch and i not in self.holds:
                self.hold_ms[i] = (ended - started) * 1000
                self.holds[i] = duration_grade(self.hold_ms[i], self.expected[i].duration * 1000)

    def advance_to(self, now: float) -> None:
        """Mark every expected strike whose window has closed without an attack as missed."""
        for i, note in enumerate(self.expected):
            if i not in self.hits and now - self.offset_s > note.at + WINDOW_MS / 1000:
                self.hits[i] = TimedHit(i, Grade.MISS, None, None)

    @property
    def accuracy(self) -> float:
        """Return hits as a share of expected strikes plus stray notes."""
        good = sum(h.grade != Grade.MISS for h in self.hits.values())
        return good / max(1, len(self.expected) + len(self.strays))

    @property
    def mean_error_ms(self) -> float:
        """Return the average signed timing error; negative means rushing."""
        errors = [h.error_ms for h in self.hits.values() if h.error_ms is not None]
        return mean(errors) if errors else 0.0

    @property
    def jitter_ms(self) -> float:
        """Return the spread of timing errors, a measure of steadiness."""
        errors = [h.error_ms for h in self.hits.values() if h.error_ms is not None]
        return pstdev(errors) if len(errors) >= 2 else 0.0
