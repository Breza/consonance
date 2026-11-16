import json
from dataclasses import asdict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QSpinBox, QWidget

from consonance.core.midi_output import Settings


class SettingsPanel(QWidget):
    changed = Signal(object)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.form = QFormLayout(self)
        self.spins: dict[str, QSpinBox] = {}
        for name, label, low, high, value, suffix in (
            (
                "midi_judge_offset_ms",
                "MIDI judge offset",
                -150,
                150,
                settings.midi_judge_offset_ms,
                " ms",
            ),
            ("visual_offset_ms", "Visual offset", -150, 150, settings.visual_offset_ms, " ms"),
            (
                "user_channel",
                "Physical keyboard input channel",
                1,
                16,
                settings.user_channel + 1,
                "",
            ),
            (
                "piano_channel",
                "Computer piano output channel",
                1,
                16,
                settings.piano_channel + 1,
                "",
            ),
            (
                "metronome_channel",
                "Woodblock output channel",
                1,
                16,
                settings.metronome_channel + 1,
                "",
            ),
            ("tempo_bpm", "Practice tempo", 30, 200, settings.tempo_bpm, " BPM"),
        ):
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(value)
            spin.setSuffix(suffix)
            self.form.addRow(label, spin)
            self.spins[name] = spin
        self.voice = QComboBox()
        self.voice.addItems(["Woodblock", "Piano", "Off"])
        self.voice.setCurrentText(settings.metronome)
        self.form.addRow("Metronome", self.voice)
        self.self_paced = QCheckBox("First two notes establish the pace")
        self.self_paced.setChecked(settings.technique_self_paced)
        self.form.addRow("Technique Lab", self.self_paced)
        from PySide6.QtWidgets import QLabel, QPushButton

        self.error = QLabel("")
        self.form.addRow(self.error)
        apply = QPushButton("Save settings")
        apply.clicked.connect(self.save)
        self.form.addRow(apply)

    def save(self) -> None:
        values = {key: spin.value() for key, spin in self.spins.items()}
        try:
            settings = Settings(
                midi_judge_offset_ms=values["midi_judge_offset_ms"],
                visual_offset_ms=values["visual_offset_ms"],
                user_channel=values["user_channel"] - 1,
                piano_channel=values["piano_channel"] - 1,
                metronome_channel=values["metronome_channel"] - 1,
                tempo_bpm=values["tempo_bpm"],
                technique_self_paced=self.self_paced.isChecked(),
                metronome=self.voice.currentText(),
            )
            self.error.setText("Saved")
            self.changed.emit(settings)
        except ValueError as exc:
            self.error.setText(str(exc))


def settings_json(settings: Settings) -> str:
    return json.dumps(asdict(settings))
