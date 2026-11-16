"""Canonical song notes, beat-based chord checkpoints, and loop tempo progression."""

from dataclasses import dataclass
from fractions import Fraction

from consonance.core.notation import Hand, MidiPitch, TimeSignature
from consonance.core.transport import TempoMap


@dataclass(frozen=True)
class SongNote:
    pitch: MidiPitch
    start_beat: Fraction
    duration: Fraction
    hand: Hand
    velocity: int = 80
    track: int = 0


@dataclass(frozen=True)
class SongTimeline:
    song_id: str
    title: str
    notes: tuple[SongNote, ...]
    tempo: TempoMap
    time: TimeSignature = TimeSignature()

    @property
    def end_beat(self) -> float:
        return max((float(n.start_beat + n.duration) for n in self.notes), default=0.0)


@dataclass(frozen=True)
class Checkpoint:
    beat: float
    must_strike: frozenset[MidiPitch]
    allowed_held: frozenset[MidiPitch]


def checkpoints(notes: tuple[SongNote, ...], hands: frozenset[Hand]) -> tuple[Checkpoint, ...]:
    selected = sorted((n for n in notes if n.hand in hands), key=lambda n: n.start_beat)
    groups: list[list[SongNote]] = []
    for note in selected:
        # Anchor against the first onset: do not chain a long arpeggio into a chord.
        if not groups or note.start_beat - groups[-1][0].start_beat > Fraction(1, 8):
            groups.append([note])
        else:
            groups[-1].append(note)
    result: list[Checkpoint] = []
    for group in groups:
        beat = group[0].start_beat
        must = frozenset(n.pitch for n in group)
        held = (
            frozenset(
                n.pitch
                for n in selected
                if n.start_beat < beat and n.start_beat + n.duration > beat
            )
            - must
        )
        result.append(Checkpoint(float(beat), must, held))
    return tuple(result)


@dataclass
class AutoRamp:
    enabled: bool = False
    streak: int = 0

    def complete_pass(self, accuracy: float, tempo_scale: float, *, tempo_mode: bool) -> float:
        if not self.enabled or not tempo_mode:
            self.streak = 0
            return tempo_scale
        self.streak = self.streak + 1 if accuracy >= 0.95 else 0
        if self.streak >= 3:
            self.streak = 0
            return min(1.0, round(tempo_scale + 0.05, 8)) if tempo_scale < 1 else tempo_scale
        return tempo_scale
