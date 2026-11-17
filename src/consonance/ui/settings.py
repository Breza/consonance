"""Settings: the piano connection, the metronome, timing offsets, and learning aids."""

import json
from dataclasses import asdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from consonance.core.midi_output import Settings
from consonance.io.midi_ports import match_port
from consonance.ui import theme

UNPLUGGED = "Not connected"


def settings_json(settings: Settings) -> str:
    """Encode settings for storage."""
    return json.dumps(asdict(settings))


def _section(title: str, note: str) -> tuple[QFrame, QFormLayout]:
    """Create a titled card with an explanatory line and a form to fill."""
    frame = QFrame()
    frame.setProperty("role", "card")
    column = QVBoxLayout(frame)
    column.setContentsMargins(16, 12, 16, 14)
    heading = QLabel(title.upper())
    heading.setProperty("role", "heading")
    column.addWidget(heading)
    if note:
        text = QLabel(note)
        text.setProperty("role", "muted")
        text.setWordWrap(True)
        column.addWidget(text)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    form.setHorizontalSpacing(18)
    column.addLayout(form)
    return frame, form


class SettingsPanel(QWidget):
    """Every setting takes effect as soon as it is changed and valid."""

    changed = Signal(object)
    connect_requested = Signal(str, str)
    auto_connect_changed = Signal(bool)

    def __init__(self, settings: Settings, auto_connect: bool = True) -> None:
        """Build the panel showing ``settings``."""
        super().__init__()
        self.settings = settings
        self._filling = True
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(12)
        self.spins: dict[str, QSpinBox] = {}
        layout.addWidget(self._build_piano(auto_connect))
        layout.addWidget(self._build_metronome())
        layout.addWidget(self._build_timing())
        layout.addWidget(self._build_help())
        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {theme.RED};")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        layout.addStretch(1)
        self._filling = False

    def _spin(self, name: str, low: int, high: int, value: int, suffix: str = "") -> QSpinBox:
        """Create a number field bound to one setting."""
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        spin.setMaximumWidth(150)
        spin.valueChanged.connect(self.apply)
        self.spins[name] = spin
        return spin

    def _build_piano(self, auto_connect: bool) -> QFrame:
        """Create the MIDI connection and channel controls."""
        card, form = _section(
            "Your piano",
            "The piano makes every sound. Keep Local Control on. Consonance listens to your "
            "keys on one channel and plays its own notes on two others, so it never "
            "interferes with what you play.",
        )
        self.inputs = QComboBox()
        self.outputs = QComboBox()
        for combo in (self.inputs, self.outputs):
            combo.addItem(UNPLUGGED)
        form.addRow("MIDI in (from the piano)", self.inputs)
        form.addRow("MIDI out (to the piano)", self.outputs)
        row = QHBoxLayout()
        connect = QPushButton("Connect")
        connect.setProperty("role", "primary")
        connect.clicked.connect(self._connect)
        disconnect = QPushButton("Disconnect")
        disconnect.clicked.connect(lambda: self.connect_requested.emit("", ""))
        self.auto = QCheckBox("Connect automatically when the piano appears")
        self.auto.setChecked(auto_connect)
        self.auto.toggled.connect(self.auto_connect_changed.emit)
        row.addWidget(connect)
        row.addWidget(disconnect)
        row.addWidget(self.auto)
        row.addStretch(1)
        form.addRow("", row)
        self.link = QLabel("")
        self.link.setWordWrap(True)
        form.addRow("Status", self.link)
        s = self.settings
        form.addRow(
            "Your keys arrive on channel", self._spin("user_channel", 1, 16, s.user_channel + 1)
        )
        form.addRow(
            "Computer piano plays on channel",
            self._spin("piano_channel", 1, 16, s.piano_channel + 1),
        )
        form.addRow(
            "Woodblock click plays on channel",
            self._spin("metronome_channel", 1, 16, s.metronome_channel + 1),
        )
        return card

    def _build_metronome(self) -> QFrame:
        """Create the click voice, default tempo, and Technique Lab pacing controls."""
        card, form = _section(
            "Click and tempo",
            "The click is played by the piano: a woodblock on the percussion channel, or two "
            "short high piano notes. A beat display on the practice screen always shows it too.",
        )
        self.voice = QComboBox()
        self.voice.addItems(["Woodblock", "Piano", "Off"])
        self.voice.setCurrentText(self.settings.metronome)
        self.voice.setMaximumWidth(150)
        self.voice.currentIndexChanged.connect(self.apply)
        form.addRow("Click sound", self.voice)
        form.addRow(
            "Tempo for rhythm and technique",
            self._spin("tempo_bpm", 30, 200, self.settings.tempo_bpm, " BPM"),
        )
        self.self_paced = QCheckBox("Let my first two notes set the pace (no count-in)")
        self.self_paced.setChecked(self.settings.technique_self_paced)
        self.self_paced.toggled.connect(self.apply)
        form.addRow("Technique Lab", self.self_paced)
        return card

    def _build_timing(self) -> QFrame:
        """Create the two independent latency offsets."""
        card, form = _section(
            "Timing",
            "Leave these alone unless timing feels consistently off. If Rhythm Sniper always "
            "reports you late by a similar amount while you feel on the beat, enter that "
            "amount as the judging offset.",
        )
        form.addRow(
            "Judging offset (subtracted from your key times)",
            self._spin(
                "midi_judge_offset_ms", -150, 150, self.settings.midi_judge_offset_ms, " ms"
            ),
        )
        form.addRow(
            "Display offset (moves only what is drawn)",
            self._spin("visual_offset_ms", -150, 150, self.settings.visual_offset_ms, " ms"),
        )
        return card

    def _build_help(self) -> QFrame:
        """Create the learning-aid controls."""
        card, form = _section(
            "Help while learning",
            "After this many wrong keys on one prompt the answer lights up on the keyboard. "
            "The attempt already counts as a miss, so the hint costs nothing extra.",
        )
        form.addRow(
            "Light the answer after (0 = never)",
            self._spin("auto_hint_misses", 0, 9, self.settings.auto_hint_misses, " misses"),
        )
        return card

    def _connect(self) -> None:
        """Ask for the ports chosen in the two selectors."""
        self.connect_requested.emit(self.chosen(self.inputs), self.chosen(self.outputs))

    @staticmethod
    def chosen(combo: QComboBox) -> str:
        """Return the port a selector points at, or an empty string for none."""
        return combo.currentText() if combo.currentIndex() > 0 else ""

    def show_ports(self, inputs: list[str], outputs: list[str]) -> None:
        """Refresh the port lists, keeping each selection if that port still exists."""
        for combo, names in ((self.inputs, inputs), (self.outputs, outputs)):
            if [combo.itemText(i) for i in range(1, combo.count())] == names:
                continue
            current = self.chosen(combo)
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([UNPLUGGED, *names])
            match = match_port(current, names)
            combo.setCurrentIndex(names.index(match) + 1 if match else 0)
            combo.blockSignals(False)

    def select_ports(self, input_name: str, output_name: str) -> None:
        """Point the selectors at particular ports, if they are present."""
        for combo, name in ((self.inputs, input_name), (self.outputs, output_name)):
            index = combo.findText(name) if name else 0
            combo.setCurrentIndex(max(0, index))

    def show_link(self, text: str, good: bool) -> None:
        """Describe the connection in words."""
        self.link.setStyleSheet(f"color: {theme.GREEN if good else theme.MUTED};")
        self.link.setText(text)

    def adopt(self, settings: Settings) -> None:
        """Show settings that were changed elsewhere, without re-announcing them."""
        self.settings = settings
        self._filling = True
        values = asdict(settings)
        for name, spin in self.spins.items():
            spin.setValue(values[name] + (1 if name.endswith("_channel") else 0))
        self.voice.setCurrentText(settings.metronome)
        self.self_paced.setChecked(settings.technique_self_paced)
        self._filling = False

    def apply(self) -> None:
        """Validate the controls and announce the result, or explain what is wrong."""
        if self._filling:
            return
        values = {name: spin.value() for name, spin in self.spins.items()}
        try:
            settings = Settings(
                midi_judge_offset_ms=values["midi_judge_offset_ms"],
                visual_offset_ms=values["visual_offset_ms"],
                user_channel=values["user_channel"] - 1,
                piano_channel=values["piano_channel"] - 1,
                metronome_channel=values["metronome_channel"] - 1,
                metronome=self.voice.currentText(),
                tempo_bpm=values["tempo_bpm"],
                technique_self_paced=self.self_paced.isChecked(),
                auto_hint_misses=values["auto_hint_misses"],
                show_names=self.settings.show_names,
                key_hints=self.settings.key_hints,
            )
        except ValueError as exc:
            self.error.setText(f"{exc} • not applied yet")
            return
        self.error.setText("")
        self.settings = settings
        self.changed.emit(settings)

    def save(self) -> None:
        """Apply the current values (kept for callers that used an explicit save)."""
        self.apply()
