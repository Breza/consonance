"""Channel-isolated output scheduling, non-destructive note ownership, and settings."""

import heapq
import json
from collections.abc import Callable
from dataclasses import dataclass, fields, replace

LOOKAHEAD = 0.004


@dataclass(frozen=True)
class OutputNote:
    """A note the computer asks the piano to sound at a wall-clock time."""

    at: float
    pitch: int
    duration: float
    velocity: int = 80
    channel: int = 1


class MidiOutputLedger:
    """Dispatch scheduled notes on time and remember which notes the computer owns."""

    def __init__(self, send: Callable[[tuple[int, ...]], None], user_channel: int = 0) -> None:
        """Create a ledger that writes raw MIDI bytes through ``send``."""
        self.send = send
        self.user_channel = user_channel
        self.active: dict[tuple[int, int], float] = {}
        self._pending: list[tuple[float, int, OutputNote]] = []
        self._serial = 0

    def schedule(self, note: OutputNote) -> None:
        """Queue a note; it must be valid and must never use the player's own channel."""
        if (
            note.channel == self.user_channel
            or not 0 <= note.channel <= 15
            or not 0 <= note.pitch <= 127
            or not 1 <= note.velocity <= 127
            or note.duration <= 0
        ):
            raise ValueError("Computer output must use an isolated channel and valid note")
        self._serial += 1
        heapq.heappush(self._pending, (note.at, self._serial, note))

    def advance_to(self, now: float) -> None:
        """Advance scheduled state to the supplied monotonic time in seconds."""
        for pair, end in tuple(self.active.items()):
            if end <= now:
                channel, pitch = pair
                self.send((0x80 | channel, pitch, 0))
                del self.active[pair]
        while self._pending and self._pending[0][0] <= now + LOOKAHEAD:
            _, _, note = heapq.heappop(self._pending)
            pair = (note.channel, note.pitch)
            if pair in self.active:
                self.send((0x80 | note.channel, note.pitch, 0))
            self.send((0x90 | note.channel, note.pitch, note.velocity))
            self.active[pair] = max(now, note.at) + note.duration

    def release_computer_notes(self) -> None:
        """Release only ledger-owned notes and discard pending computer output."""
        self._pending.clear()
        for channel, pitch in self.active:
            self.send((0x80 | channel, pitch, 0))
        self.active.clear()

    def forget(self) -> None:
        """Drop all bookkeeping without sending anything, after the output port is lost."""
        self._pending.clear()
        self.active.clear()

    def full_hardware_panic(self) -> None:
        """Release owned notes and clear notes and damper across all MIDI channels."""
        self.release_computer_notes()
        for channel in range(16):
            self.send((0xB0 | channel, 123, 0))
            self.send((0xB0 | channel, 64, 0))


@dataclass(frozen=True)
class Settings:
    """Everything the practice engine is told about the setup and the player's preferences."""

    midi_judge_offset_ms: int = 0
    visual_offset_ms: int = 25
    user_channel: int = 0
    piano_channel: int = 1
    metronome_channel: int = 9
    metronome: str = "Woodblock"
    tempo_bpm: int = 72
    technique_self_paced: bool = True
    auto_hint_misses: int = 2
    show_names: bool = False
    key_hints: bool = False

    def __post_init__(self) -> None:
        """Reject offsets, channels, voices, and tempos outside their supported ranges."""
        if any(not -150 <= x <= 150 for x in (self.midi_judge_offset_ms, self.visual_offset_ms)):
            raise ValueError("Offsets must be in -150..150ms")
        channels = (self.user_channel, self.piano_channel, self.metronome_channel)
        if any(not 0 <= c <= 15 for c in channels) or len(set(channels)) != 3:
            raise ValueError("Use three distinct MIDI channels in 1..16")
        if self.metronome not in ("Woodblock", "Piano", "Off"):
            raise ValueError("Invalid metronome voice")
        if not 30 <= self.tempo_bpm <= 200:
            raise ValueError("Tempo must be in 30..200 BPM")
        if not 0 <= self.auto_hint_misses <= 9:
            raise ValueError("Auto-hint must be off (0) or after 1..9 misses")

    @property
    def assisted(self) -> bool:
        """Report whether an on-screen aid is giving the answer away."""
        return self.show_names or self.key_hints

    def same_routing(self, other: "Settings") -> bool:
        """Report whether two settings send computer output to the same places."""
        return (self.user_channel, self.piano_channel, self.metronome_channel, self.metronome) == (
            other.user_channel,
            other.piano_channel,
            other.metronome_channel,
            other.metronome,
        )

    @classmethod
    def from_json(cls, raw: str | None) -> "Settings":
        """Load saved settings, keeping every value that is still valid.

        Unknown keys from other versions are ignored and an invalid value falls back to
        its default, so one bad field never discards the rest of a saved setup.
        """
        settings = cls()
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            return settings
        if not isinstance(data, dict):
            return settings
        names = {f.name for f in fields(cls)}
        clean = {
            key: value
            for key, value in data.items()
            if key in names and type(value) is type(getattr(settings, key))
        }
        try:
            return replace(settings, **clean)
        except ValueError:
            pass
        for key, value in clean.items():
            try:
                settings = replace(settings, **{key: value})
            except ValueError:
                continue
        return settings

    def click(self, at: float, downbeat: bool) -> OutputNote | None:
        """Return the metronome click for a beat, or None when the metronome is off."""
        if self.metronome == "Off":
            return None
        piano = self.metronome == "Piano"
        return OutputNote(
            at,
            (96 if downbeat else 91) if piano else (76 if downbeat else 77),
            0.040,
            90 if downbeat else 70,
            self.piano_channel if piano else self.metronome_channel,
        )
