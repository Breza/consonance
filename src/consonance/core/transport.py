"""Piecewise tempo integration and a wall-time/beat transport with exact pause anchors."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class TempoPoint:
    """A tempo that takes effect at a beat."""

    beat: float
    bpm: float


@dataclass(frozen=True)
class TempoMap:
    """A song's tempo as constant-BPM stretches starting at beat 0."""

    points: tuple[TempoPoint, ...] = (TempoPoint(0, 72),)

    def __post_init__(self) -> None:
        """Reject empty, unordered, or non-positive tempo maps."""
        if (
            not self.points
            or self.points[0].beat != 0
            or any(p.bpm <= 0 for p in self.points)
            or any(b.beat <= a.beat for a, b in zip(self.points, self.points[1:], strict=False))
        ):
            raise ValueError("Tempo map needs positive BPM and strictly ordered points from beat 0")

    def seconds_at(self, beat: float) -> float:
        """Integrate the tempo map to return elapsed seconds at a song beat."""
        seconds = 0.0
        for i, point in enumerate(self.points):
            end = self.points[i + 1].beat if i + 1 < len(self.points) else beat
            seconds += max(0, min(beat, end) - point.beat) * 60 / point.bpm
            if beat <= end:
                break
        return seconds

    def beat_at(self, seconds: float) -> float:
        """Return the musical beat corresponding to the supplied time."""
        remaining = max(0.0, seconds)
        for i, point in enumerate(self.points):
            if i + 1 == len(self.points):
                return point.beat + remaining * point.bpm / 60
            duration = (self.points[i + 1].beat - point.beat) * 60 / point.bpm
            if remaining <= duration:
                return point.beat + remaining * point.bpm / 60
            remaining -= duration
        return 0.0

    def bpm_at(self, beat: float) -> float:
        """Return the written tempo in force at a beat."""
        current = self.points[0].bpm
        for point in self.points:
            if point.beat <= beat:
                current = point.bpm
        return current


class TransportState(StrEnum):
    """What the song clock is doing."""

    STOPPED = "STOPPED"
    COUNT_IN = "COUNT_IN"
    PLAYING = "PLAYING"
    PAUSED_WAIT = "PAUSED_WAIT"
    PAUSED_USER = "PAUSED_USER"


class SongTransport:
    """Map wall-clock time to song beats through play, pause, count-in, and tempo scaling."""

    def __init__(self, tempo_map: TempoMap, tempo_scale: float = 1.0) -> None:
        """Create a stopped transport at beat 0."""
        self.tempo_map = tempo_map
        self._scale = 1.0
        self.state = TransportState.STOPPED
        self._beat = 0.0
        self._wall = 0.0
        self._count_end = 0.0
        self._count_beats = 0
        self.set_scale(tempo_scale, 0)

    @property
    def tempo_scale(self) -> float:
        """Return the playback speed as a fraction of the written tempo."""
        return self._scale

    @property
    def count_end(self) -> float:
        """Return the wall time at which the current count-in gives way to the music."""
        return self._count_end

    def count_in_position(self, now: float) -> float | None:
        """Return beats elapsed in the count-in bar, or None when not counting in."""
        if self.state != TransportState.COUNT_IN or now >= self._count_end:
            return None
        beat_seconds = 60 / self.tempo_map.points[0].bpm / self._scale
        return max(0.0, self._count_beats - (self._count_end - now) / beat_seconds)

    def beat_at(self, now: float) -> float:
        """Return the musical beat corresponding to the supplied time."""
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

    def beats_per_second(self, now: float) -> float:
        """Return how fast the song position is moving right now (0 when it is not)."""
        counting = self.state == TransportState.COUNT_IN and now >= self._count_end
        if self.state != TransportState.PLAYING and not counting:
            return 0.0
        return self.tempo_map.bpm_at(self.beat_at(now)) / 60 * self._scale

    def advance_to(self, now: float) -> float:
        """Advance scheduled state to the supplied monotonic time in seconds."""
        beat = self.beat_at(now)
        if self.state == TransportState.COUNT_IN and now >= self._count_end:
            self.state = TransportState.PLAYING
            self._wall = self._count_end
        return beat

    def play(self, now: float, beat: float | None = None, count_in_beats: int = 0) -> None:
        """Start or resume, optionally from a given beat and after a count-in."""
        self._beat = self.beat_at(now) if beat is None else beat
        self._wall = now
        self._count_beats = count_in_beats
        if count_in_beats:
            bpm = self.tempo_map.points[0].bpm
            self._count_end = now + count_in_beats * 60 / bpm / self._scale
            self.state = TransportState.COUNT_IN
        else:
            self.state = TransportState.PLAYING

    def pause(self, now: float, *, wait: bool = False, checkpoint: float | None = None) -> None:
        """Freeze the position, either waiting for the player or at the user's request."""
        self._beat = self.beat_at(now) if checkpoint is None else checkpoint
        self._wall = now
        self.state = TransportState.PAUSED_WAIT if wait else TransportState.PAUSED_USER

    def seek(self, beat: float, now: float) -> None:
        """Move to a beat without changing the play state."""
        if beat < 0:
            raise ValueError("Cannot seek before beat 0")
        self._beat = beat
        self._wall = now

    def stop(self, now: float) -> None:
        """Return to beat 0 and stop."""
        self.seek(0, now)
        self.state = TransportState.STOPPED

    def set_scale(self, scale: float, now: float) -> None:
        """Change playback speed without moving the current position."""
        if not 0.25 <= scale <= 1.25:
            raise ValueError("Tempo scale must be in 0.25..1.25")
        beat = self.beat_at(now)
        if self.state == TransportState.COUNT_IN:
            self._count_end = now + max(0.0, self._count_end - now) * self._scale / scale
        self._beat, self._wall, self._scale = beat, now, scale

    def wall_at(self, beat: float, now: float) -> float:
        """Map a song beat to monotonic wall time using the current tempo scale."""
        current = self.beat_at(now)
        return (
            now
            + (self.tempo_map.seconds_at(beat) - self.tempo_map.seconds_at(current)) / self._scale
        )
