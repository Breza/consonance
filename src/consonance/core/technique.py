from dataclasses import dataclass
from statistics import pstdev


@dataclass(frozen=True)
class Evenness:
    ioi_sd_ms: float
    velocity_sd: float
    label: str
    intervals_ms: tuple[float, ...]


def measure_evenness(onsets: tuple[float, ...], velocities: tuple[int, ...]) -> Evenness:
    intervals = tuple((b - a) * 1000 for a, b in zip(onsets, onsets[1:], strict=False))
    timing = pstdev(intervals) if len(intervals) >= 2 else 0.0
    velocity = pstdev(velocities) if len(velocities) >= 2 else 0.0
    return Evenness(
        timing,
        velocity,
        "Excellent" if timing <= 18 else "Good" if timing <= 35 else "Keep exploring",
        intervals,
    )
