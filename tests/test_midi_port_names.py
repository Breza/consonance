from consonance.io.midi_ports import base_name, match_port, suggest_ports

SYNTH = "Microsoft GS Wavetable Synth 0"


def test_port_names_match_despite_a_changed_index() -> None:
    """Verify port names match despite a changed index."""
    assert base_name("Roland Digital Piano 12") == "Roland Digital Piano"
    assert base_name("FP-30X") == "FP-30X"
    present = [SYNTH, "Roland Digital Piano 2"]
    assert match_port("Roland Digital Piano 1", present) == "Roland Digital Piano 2"
    assert match_port("Roland Digital Piano 2", present) == "Roland Digital Piano 2"
    assert match_port("Some Other Device 1", present) == ""
    assert match_port("", present) == ""


def test_the_piano_is_suggested_and_the_computer_synth_never_is() -> None:
    """Verify the piano is suggested and the computer synth never is."""
    assert suggest_ports(["Roland Digital Piano 0"], [SYNTH, "Roland Digital Piano 1"]) == (
        "Roland Digital Piano 0",
        "Roland Digital Piano 1",
    )
    # A lone unnamed interface is a fair guess; its output must be the same device.
    assert suggest_ports(["USB MIDI Interface 0"], [SYNTH]) == ("USB MIDI Interface 0", "")
    assert suggest_ports(["A 0", "B 1"], [SYNTH]) == ("", "")
    assert suggest_ports(["loopMIDI Port 0", "NUVOLA 1"], ["NUVOLA 2"]) == ("NUVOLA 1", "NUVOLA 2")
    assert suggest_ports([], [SYNTH]) == ("", "")
