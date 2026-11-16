"""SMF Type 1 importer with explicit persisted track assignments; no inferred hand splitting."""

import hashlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import mido

from consonance.core.notation import Hand, MidiPitch, TimeSignature
from consonance.core.song import SongNote, SongTimeline
from consonance.core.transport import TempoMap, TempoPoint


class MidiValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TrackInfo:
    index: int
    name: str
    note_count: int
    channels: tuple[int, ...]


class MidiImport:
    def __init__(self, path: Path) -> None:
        self.digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.path = path
        try:
            self.file: Any = mido.MidiFile(path)
        except (OSError, EOFError, ValueError) as exc:
            raise MidiValidationError(f"Cannot read MIDI: {exc}") from exc
        if self.file.type not in (0, 1) or self.file.ticks_per_beat <= 0:
            raise MidiValidationError(
                "Use SMF Type 1 multi-track piano or Type 0 single-part drills"
            )
        tracks: list[TrackInfo] = []
        for i, track in enumerate(self.file.tracks):
            notes = [m for m in track if m.type == "note_on" and m.velocity > 0]
            if notes:
                if any(m.channel == 9 for m in notes):
                    raise MidiValidationError(
                        "Percussion tracks are unsupported; import piano parts"
                    )
                tracks.append(
                    TrackInfo(
                        i,
                        str(track.name or f"Track {i + 1}"),
                        len(notes),
                        tuple(sorted({m.channel for m in notes})),
                    )
                )
        if not tracks:
            raise MidiValidationError("MIDI contains no playable piano notes")
        if self.file.type == 0 and (len(tracks) != 1 or len(tracks[0].channels) != 1):
            raise MidiValidationError("Type 0 must contain one channel / single part; use Type 1")
        self.tracks = tuple(tracks)

    def timeline(self, assignment: dict[int, Hand | None]) -> SongTimeline:
        if any(t.index not in assignment for t in self.tracks):
            raise MidiValidationError("Assign every note track to Right, Left, or Ignore")
        notes: list[SongNote] = []
        tempos: dict[int, float] = {0: 120.0}
        time = TimeSignature()
        ppqn = self.file.ticks_per_beat
        for index, track in enumerate(self.file.tracks):
            tick = 0
            opened: dict[tuple[int, int], tuple[int, int]] = {}
            for msg in track:
                tick += msg.time
                if msg.type == "set_tempo":
                    tempos[tick] = 60_000_000 / msg.tempo
                elif msg.type == "time_signature":
                    try:
                        signature = TimeSignature(msg.numerator, msg.denominator)
                    except ValueError as exc:
                        raise MidiValidationError(str(exc)) from exc
                    if tick and signature != time:
                        raise MidiValidationError("Changing time signatures are unsupported in v1")
                    time = signature
                elif msg.type == "key_signature" and msg.key not in (
                    "C",
                    "G",
                    "D",
                    "F",
                    "Bb",
                    "Am",
                    "Em",
                    "Bm",
                    "Dm",
                    "Gm",
                ):
                    raise MidiValidationError("Key signature exceeds two sharps or flats")
                if assignment.get(index) is None:
                    continue
                if msg.type not in ("note_on", "note_off"):
                    continue
                slot = (msg.channel, msg.note)
                if msg.type == "note_on" and msg.velocity:
                    if slot in opened:
                        raise MidiValidationError("Overlapping repeated pitch in one track")
                    opened[slot] = (tick, msg.velocity)
                elif slot in opened:
                    start, velocity = opened.pop(slot)
                    if tick <= start or not 21 <= msg.note <= 108:
                        raise MidiValidationError(
                            "Notes must have positive duration and pitch 21..108"
                        )
                    hand = assignment[index]
                    assert hand is not None
                    notes.append(
                        SongNote(
                            MidiPitch(msg.note),
                            Fraction(start, ppqn),
                            Fraction(tick - start, ppqn),
                            hand,
                            velocity,
                            index,
                        )
                    )
            if opened:
                raise MidiValidationError("Track has note_on without matching note_off")
        if not notes:
            raise MidiValidationError("Assign at least one playable track")
        return SongTimeline(
            self.digest,
            self.path.stem,
            tuple(sorted(notes, key=lambda n: (n.start_beat, n.hand, n.pitch))),
            TempoMap(tuple(TempoPoint(t / ppqn, bpm) for t, bpm in sorted(tempos.items()))),
            time,
        )


def export_midi(timeline: SongTimeline, path: Path, ppqn: int = 960) -> None:
    midi = mido.MidiFile(type=1, ticks_per_beat=ppqn)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(
        mido.MetaMessage("time_signature", numerator=timeline.time.numerator, denominator=4, time=0)
    )
    last = 0
    for tempo in timeline.tempo.points:
        tick = round(tempo.beat * ppqn)
        conductor.append(
            mido.MetaMessage("set_tempo", tempo=round(60_000_000 / tempo.bpm), time=tick - last)
        )
        last = tick
    for hand in (Hand.RIGHT, Hand.LEFT):
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name=hand.value, time=0))
        events: list[tuple[int, bool, int, int]] = []
        for note in timeline.notes:
            if note.hand == hand:
                events.extend(
                    [
                        (round(note.start_beat * ppqn), True, note.pitch, note.velocity),
                        (round((note.start_beat + note.duration) * ppqn), False, note.pitch, 0),
                    ]
                )
        last = 0
        for tick, on, pitch, velocity in sorted(events):
            track.append(
                mido.Message(
                    "note_on" if on else "note_off",
                    channel=1,
                    note=pitch,
                    velocity=velocity,
                    time=tick - last,
                )
            )
            last = tick
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.save(path)
