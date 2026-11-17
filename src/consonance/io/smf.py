"""SMF importer with explicit persisted track assignments; no inferred hand splitting."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import mido

from consonance.core.notation import Hand, MidiPitch, TimeSignature
from consonance.core.song import SongNote, SongTimeline
from consonance.core.transport import TempoMap, TempoPoint

DRUM_CHANNEL = 9
_DIGEST_PREFIX = re.compile(r"^[0-9a-f]{12}_")


class MidiValidationError(ValueError):
    """A MIDI file cannot be used for practice; the message says why in plain words."""


@dataclass(frozen=True)
class TrackInfo:
    """A track that contains piano notes and therefore needs a hand assignment."""

    index: int
    name: str
    note_count: int
    channels: tuple[int, ...]


def display_title(path: Path) -> str:
    """Return a file's title without the digest prefix added to stored copies."""
    return _DIGEST_PREFIX.sub("", path.stem).replace("_", " ").strip() or path.stem


def _meter(numerator: int, denominator: int) -> TimeSignature:
    """Map a file's meter onto bars of two, three or four quarter-note beats."""
    quarters = Fraction(numerator * 4, denominator)
    if quarters not in (2, 3, 4):
        raise MidiValidationError(
            f"{numerator}/{denominator} time is not supported yet • "
            "use a file whose bars are 2, 3 or 4 quarter notes long"
        )
    return TimeSignature(int(quarters))


class MidiImport:
    """Read a Standard MIDI File and turn chosen tracks into a practice timeline."""

    def __init__(self, path: Path) -> None:
        """Open and inspect a file, listing the tracks that hold piano notes."""
        self.path = path
        self.title = display_title(path)
        self.notices: list[str] = []
        try:
            self.digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.file: Any = mido.MidiFile(path)
        except (OSError, EOFError, ValueError, KeyError, IndexError) as exc:
            raise MidiValidationError(f"Cannot read MIDI: {exc}") from exc
        if self.file.type not in (0, 1) or self.file.ticks_per_beat <= 0:
            raise MidiValidationError(
                "Use SMF Type 1 multi-track piano or Type 0 single-part drills"
            )
        tracks: list[TrackInfo] = []
        drums = False
        for i, track in enumerate(self.file.tracks):
            struck = [m for m in track if m.type == "note_on" and m.velocity > 0]
            notes = [m for m in struck if m.channel != DRUM_CHANNEL]
            drums |= len(notes) != len(struck)
            if notes:
                tracks.append(
                    TrackInfo(
                        i,
                        str(track.name or f"Track {i + 1}"),
                        len(notes),
                        tuple(sorted({m.channel for m in notes})),
                    )
                )
        if drums:
            self.notices.append("Percussion on channel 10 is left out")
        if not tracks:
            raise MidiValidationError("MIDI contains no playable piano notes")
        if self.file.type == 0 and (len(tracks) != 1 or len(tracks[0].channels) != 1):
            raise MidiValidationError("Type 0 must contain one channel / single part; use Type 1")
        self.tracks = tuple(tracks)
        self._tempos, self.time = self._conductor()
        self.notices = list(dict.fromkeys(self.notices))

    def _conductor(self) -> tuple[dict[int, float], TimeSignature]:
        """Collect the tempo changes and the single meter from every track."""
        tempos: dict[int, float] = {0: 120.0}
        time = TimeSignature()
        seen = False
        for track in self.file.tracks:
            tick = 0
            for msg in track:
                tick += msg.time
                if msg.type == "set_tempo":
                    tempos[tick] = 60_000_000 / msg.tempo
                elif msg.type == "time_signature":
                    signature = _meter(msg.numerator, msg.denominator)
                    if seen and signature != time:
                        raise MidiValidationError("Changing time signatures are unsupported")
                    if (msg.numerator, msg.denominator) != (signature.numerator, 4):
                        self.notices.append(
                            f"{msg.numerator}/{msg.denominator} is counted as "
                            f"{signature.numerator} quarter-note beats per bar"
                        )
                    time, seen = signature, True
        return tempos, time

    def timeline(self, assignment: Mapping[int, Hand | None]) -> SongTimeline:
        """Build the song from the tracks assigned to a hand; ``None`` ignores a track.

        A key struck again while it is already sounding ends the earlier note there, and
        a note left open at the end of its track is closed at the track's last event, as
        an instrument would do. Keys of any signature are accepted: imported songs are
        shown as falling notes, so the key signature does not affect what is drawn.
        """
        if any(t.index not in assignment for t in self.tracks):
            raise MidiValidationError("Assign every note track to Right, Left, or Ignore")
        notes: list[SongNote] = []
        ppqn = self.file.ticks_per_beat
        for index, track in enumerate(self.file.tracks):
            hand = assignment.get(index)
            if hand is None:
                continue
            tick = 0
            opened: dict[tuple[int, int], tuple[int, int]] = {}
            spans: list[tuple[tuple[int, int], int, int, int]] = []
            for msg in track:
                tick += msg.time
                if msg.type not in ("note_on", "note_off") or msg.channel == DRUM_CHANNEL:
                    continue
                if not 21 <= msg.note <= 108:
                    raise MidiValidationError("Notes must lie on an 88-key piano (A0 to C8)")
                slot = (msg.channel, msg.note)
                if slot in opened:
                    spans.append((slot, *opened.pop(slot), tick))
                if msg.type == "note_on" and msg.velocity:
                    opened[slot] = (tick, msg.velocity)
            spans.extend(
                (slot, start, velocity, tick) for slot, (start, velocity) in opened.items()
            )
            notes.extend(
                SongNote(
                    MidiPitch(slot[1]),
                    Fraction(start, ppqn),
                    Fraction(end - start, ppqn),
                    hand,
                    velocity,
                    index,
                )
                for slot, start, velocity, end in spans
                if end > start
            )
        if not notes:
            raise MidiValidationError("Assign at least one playable track")
        return SongTimeline(
            self.digest,
            self.title,
            tuple(sorted(notes, key=lambda n: (n.start_beat, n.hand, n.pitch))),
            TempoMap(tuple(TempoPoint(t / ppqn, bpm) for t, bpm in sorted(self._tempos.items()))),
            self.time,
        )


def export_midi(timeline: SongTimeline, path: Path, ppqn: int = 960) -> None:
    """Write a timeline as a Type 1 file with one conductor track and one track per hand."""
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
