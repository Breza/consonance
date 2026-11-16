"""Channel-isolated output scheduling and non-destructive note ownership."""

import heapq
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class OutputNote:
    at: float
    pitch: int
    duration: float
    velocity: int = 80
    channel: int = 1


class MidiOutputLedger:
    def __init__(self, send: Callable[[tuple[int, ...]], None], user_channel: int = 0) -> None:
        self.send = send
        self.user_channel = user_channel
        self.active: dict[tuple[int, int], float] = {}
        self._pending: list[tuple[float, int, OutputNote]] = []
        self._serial = 0

    def schedule(self, note: OutputNote) -> None:
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
        for pair, end in tuple(self.active.items()):
            if end <= now:
                channel, pitch = pair
                self.send((0x80 | channel, pitch, 0))
                del self.active[pair]
        while self._pending and self._pending[0][0] <= now + 0.004:
            _, _, note = heapq.heappop(self._pending)
            pair = (note.channel, note.pitch)
            if pair in self.active:
                self.send((0x80 | note.channel, note.pitch, 0))
            self.send((0x90 | note.channel, note.pitch, note.velocity))
            self.active[pair] = max(now, note.at) + note.duration

    def release_computer_notes(self) -> None:
        self._pending.clear()
        for channel, pitch in self.active:
            self.send((0x80 | channel, pitch, 0))
        self.active.clear()

    def full_hardware_panic(self) -> None:
        self.release_computer_notes()
        for channel in range(16):
            self.send((0xB0 | channel, 123, 0))
            self.send((0xB0 | channel, 64, 0))


@dataclass(frozen=True)
class Settings:
    midi_judge_offset_ms: int = 0
    visual_offset_ms: int = 25
    user_channel: int = 0
    piano_channel: int = 1
    metronome_channel: int = 9
    metronome: str = "Woodblock"
    tempo_bpm: int = 72
    technique_self_paced: bool = True

    def __post_init__(self) -> None:
        if any(not -150 <= x <= 150 for x in (self.midi_judge_offset_ms, self.visual_offset_ms)):
            raise ValueError("Offsets must be in -150..150ms")
        channels = (self.user_channel, self.piano_channel, self.metronome_channel)
        if any(not 0 <= c <= 15 for c in channels) or len(set(channels)) != 3:
            raise ValueError("Use three distinct MIDI channels in 1..16")
        if self.metronome not in ("Woodblock", "Piano", "Off"):
            raise ValueError("Invalid metronome voice")
        if not 30 <= self.tempo_bpm <= 200:
            raise ValueError("Tempo must be in 30..200 BPM")

    def click(self, at: float, downbeat: bool) -> OutputNote | None:
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
