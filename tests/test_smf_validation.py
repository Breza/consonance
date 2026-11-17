from fractions import Fraction
from pathlib import Path

import mido
import pytest

from consonance.core.notation import Hand
from consonance.io.smf import MidiImport, MidiValidationError, display_title


def save(path: Path, *tracks: list[mido.Message | mido.MetaMessage], kind: int = 1) -> Path:
    """Write a small MIDI file from lists of messages, one list per track."""
    midi = mido.MidiFile(type=kind, ticks_per_beat=480)
    for messages in tracks:
        track = mido.MidiTrack()
        track.extend(messages)
        midi.tracks.append(track)
    midi.save(path)
    return path


def note(pitch: int, length: int = 480, channel: int = 0, wait: int = 0) -> list[mido.Message]:
    """Return a note-on/note-off pair."""
    return [
        mido.Message("note_on", channel=channel, note=pitch, time=wait),
        mido.Message("note_off", channel=channel, note=pitch, time=length),
    ]


def test_type_two_rejected(tmp_path: Path) -> None:
    """Verify type two rejected."""
    midi = mido.MidiFile(type=2)
    midi.tracks.append(mido.MidiTrack())
    path = tmp_path / "unsupported.mid"
    midi.save(path)
    with pytest.raises(MidiValidationError, match="Type 1"):
        MidiImport(path)


def test_type_zero_multichannel_rejected_and_assignment_required(tmp_path: Path) -> None:
    """Verify type zero multichannel rejected and assignment required."""
    midi = mido.MidiFile(type=0)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for channel in (0, 1):
        track.append(mido.Message("note_on", channel=channel, note=60))
        track.append(mido.Message("note_off", channel=channel, note=60, time=480))
    path = tmp_path / "multi.mid"
    midi.save(path)
    with pytest.raises(MidiValidationError, match="single part"):
        MidiImport(path)
    midi.type = 1
    midi.save(path)
    imported = MidiImport(path)
    with pytest.raises(MidiValidationError, match="Assign every"):
        imported.timeline({})
    assert len(imported.timeline({0: Hand.RIGHT}).notes) == 2


def test_unreadable_and_empty_files_explain_themselves(tmp_path: Path) -> None:
    """Verify unreadable and empty files explain themselves."""
    junk = tmp_path / "junk.mid"
    junk.write_bytes(b"this is not a midi file")
    with pytest.raises(MidiValidationError, match="Cannot read"):
        MidiImport(junk)
    with pytest.raises(MidiValidationError, match="Cannot read"):
        MidiImport(tmp_path / "missing.mid")
    drums = save(tmp_path / "drums.mid", note(36, channel=9))
    with pytest.raises(MidiValidationError, match="no playable piano notes"):
        MidiImport(drums)


def test_percussion_is_left_out_and_any_key_is_accepted(tmp_path: Path) -> None:
    """Verify percussion is left out and any key is accepted."""
    path = save(
        tmp_path / "band.mid",
        [mido.MetaMessage("key_signature", key="Eb"), mido.MetaMessage("set_tempo", tempo=600_000)],
        [mido.MetaMessage("track_name", name="Piano"), *note(63), *note(67)],
        note(38, channel=9),
    )
    imported = MidiImport(path)
    assert [t.name for t in imported.tracks] == ["Piano"] and imported.tracks[0].note_count == 2
    assert imported.notices == ["Percussion on channel 10 is left out"]
    timeline = imported.timeline({1: Hand.RIGHT})
    assert [int(n.pitch) for n in timeline.notes] == [63, 67]
    assert timeline.tempo.points[0].bpm == 100 and timeline.title == "band"
    with pytest.raises(MidiValidationError, match="at least one playable"):
        imported.timeline({1: None})


def test_restruck_and_unfinished_notes_are_closed_like_an_instrument_would(tmp_path: Path) -> None:
    """Verify restruck and unfinished notes are closed like an instrument would."""
    path = save(
        tmp_path / "sloppy.mid",
        [
            mido.Message("note_on", note=60),
            mido.Message("note_on", note=60, time=240),  # struck again while still down
            mido.Message("note_off", note=60, time=240),
            mido.Message("note_on", note=64),  # never released
            mido.MetaMessage("end_of_track", time=960),
        ],
    )
    timeline = MidiImport(path).timeline({0: Hand.LEFT})
    spans = [(int(n.pitch), n.start_beat, n.duration) for n in timeline.notes]
    assert spans == [
        (60, Fraction(0), Fraction(1, 2)),
        (60, Fraction(1, 2), Fraction(1, 2)),
        (64, Fraction(1), Fraction(2)),
    ]


def test_meters_map_onto_quarter_note_bars_or_are_refused(tmp_path: Path) -> None:
    """Verify meters map onto quarter note bars or are refused."""
    six_eight = save(
        tmp_path / "jig.mid",
        [mido.MetaMessage("time_signature", numerator=6, denominator=8), *note(60, 1440)],
    )
    imported = MidiImport(six_eight)
    assert imported.time.numerator == 3
    assert imported.notices == ["6/8 is counted as 3 quarter-note beats per bar"]
    assert imported.timeline({0: Hand.RIGHT}).measure_count == 1
    odd = save(
        tmp_path / "five.mid",
        [mido.MetaMessage("time_signature", numerator=5, denominator=4), *note(60)],
    )
    with pytest.raises(MidiValidationError, match="5/4 time is not supported"):
        MidiImport(odd)
    changing = save(
        tmp_path / "changing.mid",
        [
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            *note(60),
            mido.MetaMessage("time_signature", numerator=3, denominator=4),
            *note(62),
        ],
    )
    with pytest.raises(MidiValidationError, match="Changing time signatures"):
        MidiImport(changing)


def test_notes_off_the_piano_are_refused_and_titles_are_tidied(tmp_path: Path) -> None:
    """Verify notes off the piano are refused and titles are tidied."""
    high = save(tmp_path / "high.mid", note(120))
    with pytest.raises(MidiValidationError, match="88-key piano"):
        MidiImport(high).timeline({0: Hand.RIGHT})
    stored = tmp_path / "0123456789ab_moonlight_sonata.mid"
    assert display_title(stored) == "moonlight sonata"
    assert display_title(tmp_path / "plain.mid") == "plain"
    copy = save(stored, note(60))
    assert MidiImport(copy).timeline({0: Hand.RIGHT}).title == "moonlight sonata"
