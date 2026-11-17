"""Timestamped input, physical/sustained state, and untimed assessment."""

from dataclasses import dataclass

from consonance.core.notation import MidiPitch


@dataclass(frozen=True)
class NoteOn:
    """A key going down."""

    pitch: MidiPitch
    velocity: int
    timestamp: float
    channel: int = 0


@dataclass(frozen=True)
class NoteOff:
    """A key coming up."""

    pitch: MidiPitch
    timestamp: float
    channel: int = 0


@dataclass(frozen=True)
class ControlChange:
    """A pedal or other controller movement."""

    control: int
    value: int
    timestamp: float
    channel: int = 0


type MidiEvent = NoteOn | NoteOff | ControlChange


def normalize(data: tuple[int, ...], timestamp: float) -> MidiEvent | None:
    """Turn raw MIDI bytes into an event, or None for anything practice ignores."""
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
    """When and how hard a key was struck."""

    timestamp: float
    velocity: int


@dataclass(frozen=True)
class HoldRelease:
    """A note that has stopped sounding, with the span for which it sounded."""

    pitch: MidiPitch
    started: float
    ended: float


@dataclass(frozen=True)
class SoftPedalTap:
    """A debounced press of the soft pedal, used as a hands-free replay button."""

    timestamp: float


class PianoStateTracker:
    """Follow which keys are physically down and which notes the pedals keep sounding."""

    def __init__(self) -> None:
        """Start with every key up and every pedal released."""
        self.physically_held: dict[MidiPitch, NotePress] = {}
        self.sounding: dict[MidiPitch, NotePress] = {}
        self.damper_down = False
        self.sostenuto_down = False
        self._sostenuto: set[MidiPitch] = set()
        self._soft_down = False
        self._last_soft = float("-inf")
        self._pedal_holds: list[tuple[MidiPitch, NotePress]] = []

    def process(self, event: MidiEvent) -> tuple[HoldRelease | SoftPedalTap, ...]:
        """Apply one event and return the releases and pedal taps it caused."""
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

    def reset(self) -> None:
        """Forget every held key and pedal, for example after the input port changes."""
        self.physically_held.clear()
        self.sounding.clear()
        self.damper_down = self.sostenuto_down = self._soft_down = False
        self._sostenuto.clear()
        self._pedal_holds.clear()


class UntimedEvaluator:
    """Decide when a note or chord has been answered, however slowly it is assembled.

    The answer is complete at the first instant when every target has been freshly struck
    since activation, all of them are physically held together, and no other key is down
    apart from ``allowed_held`` notes that the notation says are still sounding. With
    ``any_octave`` a target is satisfied by the same note name in any octave, which is how
    "play any C" and chords-by-name are judged.
    """

    def __init__(
        self,
        must_strike: frozenset[MidiPitch],
        activated_at: float,
        allowed_held: frozenset[MidiPitch] = frozenset(),
        *,
        any_octave: bool = False,
    ) -> None:
        """Begin listening for the targets from ``activated_at`` onward."""
        if not must_strike:
            raise ValueError("An untimed checkpoint needs at least one target pitch")
        self.must_strike = must_strike
        self.allowed_held = allowed_held
        self.activated_at = activated_at
        self.any_octave = any_octave
        self._by_class = {int(p) % 12: p for p in must_strike}
        self.strikes: dict[MidiPitch, NotePress] = {}
        self.played: list[MidiPitch] = []
        self.velocities: list[int] = []
        self.wrong_pitch_count = 0
        self.completed_at: float | None = None

    def accepts(self, pitch: int) -> bool:
        """Report whether a key is one of the targets."""
        if self.any_octave:
            return pitch % 12 in self._by_class
        return pitch in self.must_strike

    def _target(self, pitch: MidiPitch) -> MidiPitch:
        """Map a played key onto the target it satisfies."""
        return self._by_class[int(pitch) % 12] if self.any_octave else pitch

    def process(self, event: MidiEvent, piano: PianoStateTracker) -> bool:
        """Apply one event (already applied to ``piano``); return True once answered."""
        if self.completed_at is not None:
            return True
        if isinstance(event, NoteOn) and event.velocity and event.timestamp >= self.activated_at:
            self.played.append(event.pitch)
            self.velocities.append(event.velocity)
            if self.accepts(event.pitch):
                self.strikes[self._target(event.pitch)] = NotePress(event.timestamp, event.velocity)
            else:
                self.wrong_pitch_count += 1
        held = set(piano.physically_held)
        if self.any_octave:
            covered = {self._by_class[int(p) % 12] for p in held if self.accepts(p)}
            extras = {p for p in held if not self.accepts(p)}
        else:
            covered = held & self.must_strike
            extras = held - self.must_strike
        if (
            self.must_strike <= self.strikes.keys()
            and self.must_strike <= covered
            and extras <= self.allowed_held
        ):
            self.completed_at = event.timestamp
            return True
        return False

    @property
    def is_first_try_correct(self) -> bool:
        """Report whether exactly the targets were struck, with no stray or repeated keys."""
        return self.wrong_pitch_count == 0 and len(self.played) == len(self.must_strike)

    @property
    def chord_spread_ms(self) -> float | None:
        """Return the time between the first and last chord note, or None for one note."""
        if len(self.must_strike) < 2 or not self.must_strike <= self.strikes.keys():
            return None
        times = [self.strikes[p].timestamp for p in self.must_strike]
        return (max(times) - min(times)) * 1000

    @property
    def response_ms(self) -> float | None:
        """Return how long the answer took from activation, once it is complete."""
        return None if self.completed_at is None else (self.completed_at - self.activated_at) * 1000


def spread_label(spread_ms: float) -> str:
    """Describe how together a chord landed."""
    return "Tight" if spread_ms <= 35 else "Clean" if spread_ms <= 90 else "Rolled"
