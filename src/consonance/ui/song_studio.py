import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from consonance.core.builtin_scores import BUILTIN_SCORES
from consonance.core.db import AttemptLog
from consonance.core.notation import Hand
from consonance.core.song import SongTimeline
from consonance.core.song_session import SongConfig
from consonance.io.paths import data_dir
from consonance.io.smf import MidiImport


class TrackAssignmentDialog(QDialog):
    def __init__(self, imported: MidiImport, saved: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Assign MIDI tracks to hands")
        layout = QFormLayout(self)
        layout.addRow(QLabel("Assign each piano part. Type 0 is treated as one complete part."))
        prior = json.loads(saved) if saved else {}
        self.choices: dict[int, QComboBox] = {}
        for track in imported.tracks:
            combo = QComboBox()
            combo.addItems(["Choose…", "Right", "Left", "Ignore"])
            combo.setCurrentText(prior.get(str(track.index), "Choose…"))
            layout.addRow(f"{track.name} • {track.note_count} notes", combo)
            self.choices[track.index] = combo
        self.error = QLabel("")
        layout.addRow(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def validate(self) -> None:
        if any(c.currentIndex() == 0 for c in self.choices.values()):
            self.error.setText("Choose Right, Left, or Ignore for every track")
            return
        self.accept()

    def assignment(self) -> dict[int, Hand | None]:
        return {
            i: Hand.RIGHT
            if c.currentText() == "Right"
            else Hand.LEFT
            if c.currentText() == "Left"
            else None
            for i, c in self.choices.items()
        }

    def saved_json(self) -> str:
        return json.dumps({str(i): c.currentText() for i, c in self.choices.items()})


class FallingNotes(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.timeline: SongTimeline | None = None
        self.beat = 0.0
        self.held: frozenset[int] = frozenset()
        self.setMinimumHeight(140)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#172e35"))
        width = self.width() / 88
        strike = self.height() - 42
        for pitch in range(21, 109):
            black = pitch % 12 in (1, 3, 6, 8, 10)
            painter.fillRect(
                QRectF((pitch - 21) * width, strike, width - 1, 40),
                QColor("#d0873f" if pitch in self.held else "#2d444b" if black else "#edece3"),
            )
        if self.timeline:
            for note in self.timeline.notes:
                delta = float(note.start_beat) - self.beat
                end = float(note.start_beat + note.duration) - self.beat
                if end < -1 or delta > 8:
                    continue
                y = strike - end * 35
                painter.fillRect(
                    QRectF(
                        (note.pitch - 21) * width + 1,
                        y,
                        max(2.0, width - 2),
                        max(4.0, float(note.duration) * 35 - 2),
                    ),
                    QColor("#64b9a9" if note.hand == Hand.RIGHT else "#d6a969"),
                )
        painter.setPen(QColor("#faf8e9"))
        painter.drawLine(QPointF(0, strike), QPointF(self.width(), strike))
        painter.end()


class SongStudioPanel(QWidget):
    configured = Signal(object)
    view_changed = Signal(str)
    seek_requested = Signal(float)

    def __init__(self, log: AttemptLog) -> None:
        super().__init__()
        self.log = log
        self.timelines = [s.compile() for s in BUILTIN_SCORES]
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.songs = QComboBox()
        self.songs.addItems([s.title for s in BUILTIN_SCORES])
        row.addWidget(self.songs, 2)
        imported = QPushButton("Import MIDI…")
        imported.clicked.connect(self.import_file)
        row.addWidget(imported)
        self.view = QComboBox()
        self.view.addItems(["Split", "Staff", "Falling Notes"])
        self.view.currentTextChanged.connect(self.view_changed.emit)
        row.addWidget(self.view)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Wait", "Tempo"])
        self.hands = QComboBox()
        self.hands.addItems(["Right", "Left", "Both"])
        self.scale = QSpinBox()
        self.scale.setRange(25, 125)
        self.scale.setValue(70)
        self.scale.setSuffix(" %")
        self.a = QSpinBox()
        self.b = QSpinBox()
        for spin in (self.a, self.b):
            spin.setRange(1, 999)
        self.b.setValue(len(BUILTIN_SCORES[0].measures))
        self.loop = QCheckBox("A–B loop")
        self.ramp = QCheckBox("Auto-Ramp (+5%)")
        for widget in (
            self.mode,
            self.hands,
            self.scale,
            QLabel("A"),
            self.a,
            QLabel("B"),
            self.b,
            self.loop,
            self.ramp,
        ):
            row.addWidget(widget)
        layout.addLayout(row)
        self.error = QLabel("Choose a piece and click Load. All pieces are available.")
        layout.addWidget(self.error)
        load = QPushButton("Load selection")
        load.clicked.connect(self.configure)
        buttons = QHBoxLayout()
        buttons.addWidget(load)
        seek = QPushButton("Seek to measure A")
        seek.clicked.connect(
            lambda: self.seek_requested.emit(
                float((self.a.value() - 1) * self.timelines[self.songs.currentIndex()].time.beats)
            )
        )
        buttons.addWidget(seek)
        layout.addLayout(buttons)
        self.songs.currentIndexChanged.connect(self.song_changed)
        custom = data_dir() / "songs" / "custom"
        if custom.exists():
            for path in sorted(
                p for p in custom.iterdir() if p.suffix.lower() in (".mid", ".midi")
            ):
                try:
                    restored = MidiImport(path)
                    saved = self.log.preference(f"track_assignment:{restored.digest}")
                    if not saved:
                        continue
                    labels = json.loads(saved)
                    assignment = {
                        int(i): Hand.RIGHT
                        if value == "Right"
                        else Hand.LEFT
                        if value == "Left"
                        else None
                        for i, value in labels.items()
                    }
                    self.timelines.append(restored.timeline(assignment))
                    self.songs.addItem(path.stem)
                except (ValueError, OSError):
                    continue

    def show_config(self, config: SongConfig) -> None:
        index = next(
            (i for i, t in enumerate(self.timelines) if t.song_id == config.timeline.song_id), None
        )
        if index is None:
            self.timelines.append(config.timeline)
            self.songs.addItem(config.timeline.title)
            index = len(self.timelines) - 1
        self.songs.setCurrentIndex(index)
        self.mode.setCurrentText(config.mode)
        self.hands.setCurrentText(
            "Both" if len(config.hands) == 2 else "Right" if Hand.RIGHT in config.hands else "Left"
        )
        self.scale.setValue(round(config.tempo_scale * 100))
        self.a.setValue(config.start_measure)
        self.b.setValue(
            config.end_measure
            or max(
                1, int((config.timeline.end_beat - 0.00001) // config.timeline.time.numerator) + 1
            )
        )
        self.loop.setChecked(config.loop)
        self.ramp.setChecked(config.auto_ramp)

    def song_changed(self, index: int) -> None:
        timeline = self.timelines[index]
        self.a.setValue(1)
        self.b.setValue(max(1, int((timeline.end_beat - 0.00001) // timeline.time.numerator) + 1))
        if index >= len(BUILTIN_SCORES):
            self.view.setCurrentText("Falling Notes")

    def configure(self) -> None:
        try:
            hands = (
                frozenset({Hand.RIGHT}),
                frozenset({Hand.LEFT}),
                frozenset({Hand.RIGHT, Hand.LEFT}),
            )[self.hands.currentIndex()]
            config = SongConfig(
                self.timelines[self.songs.currentIndex()],
                self.mode.currentText(),
                hands,
                self.scale.value() / 100,
                self.a.value(),
                self.b.value(),
                self.loop.isChecked(),
                self.ramp.isChecked(),
            )
            self.configured.emit(config)
            self.error.setText(f"Loaded {config.timeline.title} • press Play")
        except ValueError as exc:
            self.error.setText(str(exc))

    def import_file(self) -> None:
        folder = Path.cwd() / "songs" / "custom"
        folder.mkdir(parents=True, exist_ok=True)
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import piano MIDI", str(folder), "Standard MIDI (*.mid *.midi)"
        )
        if not filename:
            return
        try:
            imported = MidiImport(Path(filename))
            key = f"track_assignment:{imported.digest}"
            dialog = TrackAssignmentDialog(imported, self.log.preference(key))
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            timeline = imported.timeline(dialog.assignment())
            self.log.set_preference(key, dialog.saved_json())
            destination = folder / f"{imported.digest[:12]}_{Path(filename).name}"
            destination.write_bytes(Path(filename).read_bytes())
            # Also retain custom content under the data override for installed deployments.
            custom = data_dir() / "songs" / "custom"
            custom.mkdir(parents=True, exist_ok=True)
            (custom / destination.name).write_bytes(destination.read_bytes())
            self.timelines.append(timeline)
            self.songs.addItem(timeline.title)
            self.songs.setCurrentIndex(len(self.timelines) - 1)
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
