from pathlib import Path

import mido
import pytest

from consonance.core.notation import Hand
from consonance.io.smf import MidiImport, MidiValidationError


def test_type_two_rejected(tmp_path: Path) -> None:
    midi = mido.MidiFile(type=2)
    midi.tracks.append(mido.MidiTrack())
    path = tmp_path / "unsupported.mid"
    midi.save(path)
    with pytest.raises(MidiValidationError, match="Type 1"):
        MidiImport(path)


def test_type_zero_multichannel_rejected_and_assignment_required(tmp_path: Path) -> None:
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
