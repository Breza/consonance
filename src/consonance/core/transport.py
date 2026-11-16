"""Piecewise tempo integration and a wall-time/beat transport with exact pause anchors."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class TempoPoint:
    beat: float
    bpm: float


@dataclass(frozen=True)
class TempoMap:
    points: tuple[TempoPoint, ...] = (TempoPoint(0, 72),)

    def __post_init__(self) -> None:
        if (
            not self.points
            or self.points[0].beat != 0
            or any(p.bpm <= 0 for p in self.points)
            or any(b.beat <= a.beat for a, b in zip(self.points, self.points[1:], strict=False))
        ):
            raise ValueError("Tempo map needs positive BPM and strictly ordered points from beat 0")

    def seconds_at(self, beat: float) -> float:
        seconds = 0.0
        for i, point in enumerate(self.points):
            end = self.points[i + 1].beat if i + 1 < len(self.points) else beat
            seconds += max(0, min(beat, end) - point.beat) * 60 / point.bpm
            if beat <= end:
                break
        return seconds

    def beat_at(self, seconds: float) -> float:
        remaining = max(0.0, seconds)
        for i, point in enumerate(self.points):
            if i + 1 == len(self.points):
                return point.beat + remaining * point.bpm / 60
            duration = (self.points[i + 1].beat - point.beat) * 60 / point.bpm
            if remaining <= duration:
                return point.beat + remaining * point.bpm / 60
            remaining -= duration
        return 0.0


class TransportState(StrEnum):
    STOPPED = "STOPPED"
    COUNT_IN = "COUNT_IN"
    PLAYING = "PLAYING"
    PAUSED_WAIT = "PAUSED_WAIT"
    PAUSED_USER = "PAUSED_USER"


class SongTransport:
    def __init__(self, tempo_map: TempoMap, tempo_scale: float = 1.0) -> None:
        self.tempo_map = tempo_map
        self._scale = 1.0
        self.state = TransportState.STOPPED
        self._beat = 0.0
        self._wall = 0.0
        self._count_end = 0.0
        self.set_scale(tempo_scale, 0)

    @property
    def tempo_scale(self) -> float:
        return self._scale

    def beat_at(self, now: float) -> float:
        if self.state == TransportState.COUNT_IN:
            if now < self._count_end:
                return self._beat
            return self.tempo_map.beat_at(
                self.tempo_map.seconds_at(self._beat) + (now - self._count_end) * self._scale
            )
        if self.state != TransportState.PLAYING:
            return self._beat
        return self.tempo_map.beat_at(
            self.tempo_map.seconds_at(self._beat) + max(0.0, now - self._wall) * self._scale
        )

    def advance_to(self, now: float) -> float:
        beat = self.beat_at(now)
        if self.state == TransportState.COUNT_IN and now >= self._count_end:
            self.state = TransportState.PLAYING
            self._wall = self._count_end
        return beat

    def play(self, now: float, beat: float | None = None, count_in_beats: int = 0) -> None:
        self._beat = self.beat_at(now) if beat is None else beat
        self._wall = now
        if count_in_beats:
            bpm = self.tempo_map.points[0].bpm
            self._count_end = now + count_in_beats * 60 / bpm / self._scale
            self.state = TransportState.COUNT_IN
        else:
            self.state = TransportState.PLAYING

    def pause(self, now: float, *, wait: bool = False, checkpoint: float | None = None) -> None:
        self._beat = self.beat_at(now) if checkpoint is None else checkpoint
        self._wall = now
        self.state = TransportState.PAUSED_WAIT if wait else TransportState.PAUSED_USER

    def seek(self, beat: float, now: float) -> None:
        if beat < 0:
            raise ValueError("Cannot seek before beat 0")
        self._beat = beat
        self._wall = now

    def stop(self, now: float) -> None:
        self.seek(0, now)
        self.state = TransportState.STOPPED

    def set_scale(self, scale: float, now: float) -> None:
        if not 0.25 <= scale <= 1.25:
            raise ValueError("Tempo scale must be in 0.25..1.25")
        beat = self.beat_at(now)
        if self.state == TransportState.COUNT_IN:
            self._count_end = now + max(0.0, self._count_end - now) * self._scale / scale
        self._beat, self._wall, self._scale = beat, now, scale

    def wall_at(self, beat: float, now: float) -> float:
        current = self.beat_at(now)
        return (
            now
            + (self.tempo_map.seconds_at(beat) - self.tempo_map.seconds_at(current)) / self._scale
        )
