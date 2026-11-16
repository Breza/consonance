"""Timestamped input, physical/sustained state, and untimed assessment."""

from dataclasses import dataclass

from consonance.core.notation import MidiPitch


@dataclass(frozen=True)
class NoteOn:
    pitch: MidiPitch
    velocity: int
    timestamp: float
    channel: int = 0


@dataclass(frozen=True)
class NoteOff:
    pitch: MidiPitch
    timestamp: float
    channel: int = 0


@dataclass(frozen=True)
class ControlChange:
    control: int
    value: int
    timestamp: float
    channel: int = 0


type MidiEvent = NoteOn | NoteOff | ControlChange


def normalize(data: tuple[int, ...], timestamp: float) -> MidiEvent | None:
    if len(data) < 3:
        return None
    status, a, b = data[:3]
    kind, channel = status & 0xF0, status & 15
    if kind == 0xB0:
        return ControlChange(a, b, timestamp, channel)
    if not 21 <= a <= 108:
        return None
    if kind == 0x90 and b:
        return NoteOn(MidiPitch(a), b, timestamp, channel)
    if kind in (0x80, 0x90):
        return NoteOff(MidiPitch(a), timestamp, channel)
    return None


@dataclass(frozen=True)
class NotePress:
    timestamp: float
    velocity: int


@dataclass(frozen=True)
class HoldRelease:
    pitch: MidiPitch
    started: float
    ended: float


@dataclass(frozen=True)
class SoftPedalTap:
    timestamp: float


class PianoStateTracker:
    def __init__(self) -> None:
        self.physically_held: dict[MidiPitch, NotePress] = {}
        self.sounding: dict[MidiPitch, NotePress] = {}
        self.damper_down = False
        self.sostenuto_down = False
        self._sostenuto: set[MidiPitch] = set()
        self._soft_down = False
        self._last_soft = float("-inf")
        self._pedal_holds: list[tuple[MidiPitch, NotePress]] = []

    def process(self, event: MidiEvent) -> tuple[HoldRelease | SoftPedalTap, ...]:
        actions: list[HoldRelease | SoftPedalTap] = []
        if isinstance(event, NoteOn):
            if event.velocity == 0:
                return self.process(NoteOff(event.pitch, event.timestamp, event.channel))
            previous = self.physically_held.get(event.pitch)
            if previous:
                if self.damper_down:
                    self._pedal_holds.append((event.pitch, previous))
                else:
                    actions.append(HoldRelease(event.pitch, previous.timestamp, event.timestamp))
            press = NotePress(event.timestamp, event.velocity)
            self.physically_held[event.pitch] = press
            self.sounding[event.pitch] = press
        elif isinstance(event, NoteOff):
            released = self.physically_held.pop(event.pitch, None)
            if released:
                if self.damper_down:
                    self._pedal_holds.append((event.pitch, released))
                else:
                    actions.append(HoldRelease(event.pitch, released.timestamp, event.timestamp))
        else:
            down = event.value >= 64
            if event.control == 64:
                self.damper_down = down
            elif event.control == 66:
                if down and not self.sostenuto_down:
                    self._sostenuto = set(self.physically_held)
                if not down:
                    self._sostenuto.clear()
                self.sostenuto_down = down
            elif event.control == 67:
                if down and not self._soft_down and event.timestamp - self._last_soft >= 0.300:
                    self._last_soft = event.timestamp
                    actions.append(SoftPedalTap(event.timestamp))
                self._soft_down = down
        if not self.damper_down:
            actions.extend(
                HoldRelease(pitch, press.timestamp, event.timestamp)
                for pitch, press in self._pedal_holds
            )
            self._pedal_holds.clear()
            for pitch in tuple(self.sounding):
                if pitch not in self.physically_held and pitch not in self._sostenuto:
                    self.sounding.pop(pitch)
        return tuple(actions)


class UntimedEvaluator:
    def __init__(
        self,
        must_strike: frozenset[MidiPitch],
        activated_at: float,
        allowed_held: frozenset[MidiPitch] = frozenset(),
    ) -> None:
        if not must_strike:
            raise ValueError("An untimed checkpoint needs at least one target pitch")
        self.must_strike = must_strike
        self.allowed_held = allowed_held
        self.activated_at = activated_at
        self.strikes: dict[MidiPitch, NotePress] = {}
        self.played: list[MidiPitch] = []
        self.velocities: list[int] = []
        self.wrong_pitch_count = 0
        self.completed_at: float | None = None

    def process(self, event: MidiEvent, piano: PianoStateTracker) -> bool:
        if self.completed_at is not None:
            return True
        if isinstance(event, NoteOn) and event.velocity and event.timestamp >= self.activated_at:
            self.played.append(event.pitch)
            self.velocities.append(event.velocity)
            if event.pitch not in self.must_strike:
                self.wrong_pitch_count += 1
            else:
                self.strikes[event.pitch] = NotePress(event.timestamp, event.velocity)
        held = set(piano.physically_held)
        if (
            self.must_strike <= self.strikes.keys()
            and self.must_strike <= held
            and held <= self.must_strike | self.allowed_held
        ):
            self.completed_at = event.timestamp
            return True
        return False

    @property
    def is_first_try_correct(self) -> bool:
        return self.wrong_pitch_count == 0 and len(self.played) == len(self.must_strike)

    @property
    def chord_spread_ms(self) -> float | None:
        if len(self.must_strike) < 2 or not self.must_strike <= self.strikes.keys():
            return None
        times = [self.strikes[p].timestamp for p in self.must_strike]
        return (max(times) - min(times)) * 1000

    @property
    def response_ms(self) -> float | None:
        return None if self.completed_at is None else (self.completed_at - self.activated_at) * 1000


def spread_label(spread_ms: float) -> str:
    return "Tight" if spread_ms <= 35 else "Clean" if spread_ms <= 90 else "Rolled"
