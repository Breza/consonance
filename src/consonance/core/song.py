"""Canonical song notes, beat-based chord checkpoints, and loop tempo progression."""

from dataclasses import dataclass
from fractions import Fraction

from consonance.core.notation import Hand, MidiPitch, TimeSignature
from consonance.core.transport import TempoMap


@dataclass(frozen=True)
class SongNote:
    """One note of a song, addressed in beats from the start."""

    pitch: MidiPitch
    start_beat: Fraction
    duration: Fraction
    hand: Hand
    velocity: int = 80
    track: int = 0


@dataclass(frozen=True)
class SongTimeline:
    """A playable song: its notes for both hands, tempo map, and meter."""

    song_id: str
    title: str
    notes: tuple[SongNote, ...]
    tempo: TempoMap
    time: TimeSignature = TimeSignature()

    @property
    def end_beat(self) -> float:
        """Return the beat at which the last note stops sounding."""
        return max((float(n.start_beat + n.duration) for n in self.notes), default=0.0)

    @property
    def measure_count(self) -> int:
        """Return the number of measures the notes occupy, at least one."""
        return max(1, int((self.end_beat - 0.00001) // self.time.numerator) + 1)

    @property
    def pitch_range(self) -> tuple[int, int]:
        """Return the lowest and highest pitch used, or middle C if there are no notes."""
        pitches = [int(n.pitch) for n in self.notes]
        return (min(pitches), max(pitches)) if pitches else (60, 60)


@dataclass(frozen=True)
class Checkpoint:
    """The notes Wait mode asks for at one beat, and the earlier notes still ringing."""

    beat: float
    must_strike: frozenset[MidiPitch]
    allowed_held: frozenset[MidiPitch]


def checkpoints(notes: tuple[SongNote, ...], hands: frozenset[Hand]) -> tuple[Checkpoint, ...]:
    """Group the chosen hands' notes into chords that Wait mode waits for in turn.

    Notes whose onsets fall within an eighth of a beat of a group's first onset belong to
    that group, independent of the file's MIDI resolution.
    """
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
    """Raise the tempo five points after three consecutive clean Tempo-mode passes."""

    enabled: bool = False
    streak: int = 0

    def complete_pass(self, accuracy: float, tempo_scale: float, *, tempo_mode: bool) -> float:
        """Record a finished pass and return the tempo scale to use for the next one."""
        if not self.enabled or not tempo_mode:
            self.streak = 0
            return tempo_scale
        self.streak = self.streak + 1 if accuracy >= 0.95 else 0
        if self.streak >= 3:
            self.streak = 0
            return min(1.0, round(tempo_scale + 0.05, 8)) if tempo_scale < 1 else tempo_scale
        return tempo_scale
