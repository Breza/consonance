"""Raw RtMidi arrival timestamps; Mido output. Local input is never echoed."""

import time
from collections.abc import Callable
from typing import Any

import mido
import rtmidi


class MidiPorts:
    def __init__(self) -> None:
        mido.set_backend("mido.backends.rtmidi")
        self.input: Any = None
        self.input_name = ""
        self.output: Any = None

    def names(self) -> tuple[list[str], list[str]]:
        probe = rtmidi.MidiIn()
        inputs = list(probe.get_ports())
        return inputs, list(mido.get_output_names())

    def connect(
        self, input_name: str, output_name: str, receive: Callable[[tuple[int, ...], float], None]
    ) -> None:
        self.close()
        try:
            if output_name:
                self.output = mido.open_output(output_name, autoreset=False)
            if input_name:
                self.input = rtmidi.MidiIn()
                names = list(self.input.get_ports())
                self.input.open_port(names.index(input_name))
                self.input_name = input_name

                def arrived(event: tuple[list[int], float], context: object = None) -> None:
                    timestamp = time.perf_counter()
                    receive(tuple(event[0]), timestamp)

                self.input.ignore_types(sysex=True, timing=True, active_sense=True)
                self.input.set_callback(arrived)
        except Exception:
            self.close()
            raise

    def send_bytes(self, data: tuple[int, ...]) -> None:
        if self.output is not None:
            self.output.send(mido.Message.from_bytes(list(data)))

    def close(self) -> None:
        if self.input is not None:
            self.input.cancel_callback()
            self.input.close_port()
            self.input = None
            self.input_name = ""
        if self.output is not None:
            self.output.close()
            self.output = None
