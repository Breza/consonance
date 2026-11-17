"""Raw RtMidi arrival timestamps; Mido output. Local input is never echoed."""

import re
import time
from collections.abc import Callable, Sequence
from typing import Any

import mido
import rtmidi

_INDEX = re.compile(r"\s+\d+$")
_PIANO_WORDS = ("roland", "nuvola", "piano", "yamaha", "kawai", "casio", "korg", "keyboard")
_NOT_INSTRUMENTS = ("wavetable", "midi mapper", "through", "thru", "loopmidi")


def base_name(name: str) -> str:
    """Strip the port index Windows appends, which changes as devices come and go."""
    return _INDEX.sub("", name).strip()


def match_port(wanted: str, available: Sequence[str]) -> str:
    """Find a remembered port among those present, tolerating a changed index."""
    if not wanted:
        return ""
    if wanted in available:
        return wanted
    target = base_name(wanted).lower()
    return next((name for name in available if base_name(name).lower() == target), "")


def suggest_ports(inputs: Sequence[str], outputs: Sequence[str]) -> tuple[str, str]:
    """Guess which ports are the piano; never pick the computer's own synthesiser.

    The input must look like an instrument, or be the only real candidate. The output is
    offered only when it belongs to the same device as the chosen input.
    """
    real_inputs = [n for n in inputs if not any(w in n.lower() for w in _NOT_INSTRUMENTS)]
    named = [n for n in real_inputs if any(w in n.lower() for w in _PIANO_WORDS)]
    chosen = named[0] if named else (real_inputs[0] if len(real_inputs) == 1 else "")
    if not chosen:
        return "", ""
    output = match_port(chosen, [n for n in outputs if "wavetable" not in n.lower()])
    return chosen, output


class MidiPorts:
    """Open one MIDI input and one MIDI output and move raw bytes through them."""

    def __init__(self) -> None:
        """Select the RtMidi backend; no port is opened yet."""
        mido.set_backend("mido.backends.rtmidi")
        self.input: Any = None
        self.input_name = ""
        self.output: Any = None
        self.output_name = ""

    def names(self) -> tuple[list[str], list[str]]:
        """Return the names of the input and output ports currently present."""
        probe = rtmidi.MidiIn()
        try:
            inputs = list(probe.get_ports())
        finally:
            probe.delete()
        return inputs, list(mido.get_output_names())

    def connect(
        self, input_name: str, output_name: str, receive: Callable[[tuple[int, ...], float], None]
    ) -> None:
        """Open the named ports; an empty name leaves that direction unplugged.

        Each incoming message is stamped with ``time.perf_counter()`` on RtMidi's own
        thread, the moment it arrives, before being handed to ``receive``.
        """
        self.close()
        try:
            if output_name:
                self.output = mido.open_output(output_name, autoreset=False)
                self.output_name = output_name
            if input_name:
                self.input = rtmidi.MidiIn()
                names = list(self.input.get_ports())
                if input_name not in names:
                    raise OSError(f"MIDI input '{input_name}' is not available")
                self.input.open_port(names.index(input_name))
                self.input_name = input_name

                def arrived(event: tuple[list[int], float], context: object = None) -> None:
                    """Timestamp one incoming message and pass it on."""
                    timestamp = time.perf_counter()
                    receive(tuple(event[0]), timestamp)

                self.input.ignore_types(sysex=True, timing=True, active_sense=True)
                self.input.set_callback(arrived)
        except Exception:
            self.close()
            raise

    def send_bytes(self, data: tuple[int, ...]) -> None:
        """Send one raw MIDI message, if an output is open."""
        if self.output is not None:
            self.output.send(mido.Message.from_bytes(list(data)))

    def close(self) -> None:
        """Close whichever ports are open."""
        if self.input is not None:
            try:
                self.input.cancel_callback()
                self.input.close_port()
            finally:
                self.input = None
                self.input_name = ""
        if self.output is not None:
            try:
                self.output.close()
            finally:
                self.output = None
                self.output_name = ""
