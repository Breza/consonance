from consonance.core.input_and_grading import (
    ControlChange,
    HoldRelease,
    NoteOff,
    NoteOn,
    PianoStateTracker,
    SoftPedalTap,
    normalize,
)
from consonance.core.notation import MidiPitch


def test_velocity_zero_and_ignored_messages() -> None:
    assert normalize((0x90, 60, 0), 1) == NoteOff(MidiPitch(60), 1)
    assert normalize((0xFE,), 1) is None
    assert normalize((0xF0, 1, 2), 1) is None


def test_damper_release() -> None:
    state = PianoStateTracker()
    state.process(NoteOn(MidiPitch(60), 90, 0))
    state.process(ControlChange(64, 70, 0.1))
    assert not state.process(NoteOff(MidiPitch(60), 0.5))
    assert not state.physically_held and state.sounding
    assert state.process(ControlChange(64, 63, 1)) == (HoldRelease(MidiPitch(60), 0, 1),)


def test_soft_pedal_edges_and_debounce() -> None:
    state = PianoStateTracker()
    assert state.process(ControlChange(67, 64, 0)) == (SoftPedalTap(0),)
    assert not state.process(ControlChange(67, 127, 0.5))
    state.process(ControlChange(67, 0, 0.51))
    assert state.process(ControlChange(67, 64, 0.52)) == (SoftPedalTap(0.52),)
    state.process(ControlChange(67, 0, 0.6))
    assert not state.process(ControlChange(67, 64, 0.7))


def test_repeated_note_under_damper_retains_each_effective_hold() -> None:
    state = PianoStateTracker()
    state.process(NoteOn(MidiPitch(60), 80, 0))
    state.process(ControlChange(64, 127, 0.1))
    assert not state.process(NoteOff(MidiPitch(60), 0.2))
    state.process(NoteOn(MidiPitch(60), 80, 0.3))
    assert state.process(ControlChange(64, 0, 0.6)) == (HoldRelease(MidiPitch(60), 0, 0.6),)
    assert state.process(NoteOff(MidiPitch(60), 0.8)) == (HoldRelease(MidiPitch(60), 0.3, 0.8),)
