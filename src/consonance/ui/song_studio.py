"""Song Studio: track assignment for imports, the falling-notes view, and the song controls."""

import json
from bisect import bisect_left, bisect_right
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPen
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

from consonance.core.builtin_scores import ALL_SCORES
from consonance.core.db import AttemptLog
from consonance.core.notation import Hand
from consonance.core.song import SongTimeline
from consonance.core.song_session import SongConfig
from consonance.io.paths import custom_songs_dir
from consonance.io.smf import MidiImport
from consonance.ui import theme
from consonance.ui.keyboard import KeyGeometry, fit_range, key_fills, paint_keys

HANDS = {"Right": frozenset({Hand.RIGHT}), "Left": frozenset({Hand.LEFT}), "Both": frozenset(Hand)}
_RIGHT_WORDS = ("right", "rh", "treble", "upper", "melody")
_LEFT_WORDS = ("left", "lh", "bass", "lower")


def _assignment(labels: dict[str, str]) -> dict[int, Hand | None]:
    """Turn saved Right/Left/Ignore labels into a track-to-hand mapping."""
    hands = {"Right": Hand.RIGHT, "Left": Hand.LEFT}
    return {int(index): hands.get(label) for index, label in labels.items()}


class TrackAssignmentDialog(QDialog):
    """Ask which hand plays each track of an imported file; nothing is guessed from notes."""

    def __init__(self, imported: MidiImport, saved: str | None = None) -> None:
        """Build one choice per note track, restoring an earlier answer for this file."""
        super().__init__()
        self.setWindowTitle("Assign MIDI tracks to hands")
        layout = QFormLayout(self)
        intro = QLabel(
            "Choose which hand plays each part. A single-track file is treated as one part.\n"
            "Ignored tracks are neither shown nor played."
        )
        layout.addRow(intro)
        prior = json.loads(saved) if saved else {}
        self.choices: dict[int, QComboBox] = {}
        for track in imported.tracks:
            combo = QComboBox()
            combo.addItems(["Choose…", "Right", "Left", "Ignore"])
            name = track.name.lower()
            # A track that names its own hand is a statement by the file, not a guess.
            named = (
                "Right"
                if any(word in name.split() for word in _RIGHT_WORDS)
                else "Left"
                if any(word in name.split() for word in _LEFT_WORDS)
                else "Choose…"
            )
            combo.setCurrentText(prior.get(str(track.index), named))
            layout.addRow(f"{track.name} • {track.note_count} notes", combo)
            self.choices[track.index] = combo
        for notice in imported.notices:
            note = QLabel(notice)
            note.setProperty("role", "muted")
            layout.addRow(note)
        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {theme.RED};")
        layout.addRow(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def validate(self) -> None:
        """Accept only when every track has an explicit choice and one is playable."""
        if any(c.currentIndex() == 0 for c in self.choices.values()):
            self.error.setText("Choose Right, Left, or Ignore for every track")
            return
        if all(c.currentText() == "Ignore" for c in self.choices.values()):
            self.error.setText("Give at least one track to a hand")
            return
        self.accept()

    def assignment(self) -> dict[int, Hand | None]:
        """Return the chosen hand for each track; None means ignore."""
        return _assignment({str(i): c.currentText() for i, c in self.choices.items()})

    def saved_json(self) -> str:
        """Return the choices as JSON, to be remembered against the file's digest."""
        return json.dumps({str(i): c.currentText() for i, c in self.choices.items()})


class FallingNotes(QWidget):
    """Notes fall toward a realistic keyboard, zoomed to the range the song uses.

    The hands being practised are drawn solid; the hand the computer plays is dimmed.
    Bar lines and bar numbers scroll with the notes so position in the piece is visible.
    """

    def __init__(self) -> None:
        """Create an empty view."""
        super().__init__()
        self.timeline: SongTimeline | None = None
        self.hands: frozenset[Hand] = frozenset(Hand)
        self.beat = 0.0
        self.held: frozenset[int] = frozenset()
        self.expected: frozenset[int] = frozenset()
        self.allowed: frozenset[int] = frozenset()
        self.reveal = False
        self._starts: list[float] = []
        self._longest = 0.0
        self._range = (48, 72)
        self.setMinimumHeight(190)

    def show_song(self, timeline: SongTimeline | None, hands: frozenset[Hand]) -> None:
        """Adopt a song and the hands being practised, and zoom to the song's range."""
        if hands != self.hands:
            self.hands = hands
            self.update()
        if timeline is self.timeline:
            return
        self.timeline = timeline
        notes = timeline.notes if timeline else ()
        self._starts = [float(n.start_beat) for n in notes]
        self._longest = max((float(n.duration) for n in notes), default=0.0)
        low, high = timeline.pitch_range if timeline else (60, 60)
        self._range = fit_range((low - 2, high + 2), (55, 65))
        self.update()

    def show_state(
        self,
        beat: float,
        held: frozenset[int],
        expected: frozenset[int],
        allowed: frozenset[int],
        reveal: bool,
    ) -> None:
        """Adopt the song position and key states, repainting only on change."""
        state = (beat, held, expected, allowed, reveal)
        if state != (self.beat, self.held, self.expected, self.allowed, self.reveal):
            self.beat, self.held, self.expected, self.allowed, self.reveal = state
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the grid, the falling notes, and the keyboard they land on."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.NIGHT))
        keys = KeyGeometry(*self._range, 0.0, float(self.width()))
        key_height = min(96.0, max(58.0, self.height() * 0.3))
        strike = self.height() - key_height
        per_beat = max(30.0, min(64.0, strike / 5.5))
        painter.setPen(QPen(QColor(theme.NIGHT_LINE), 1))
        for pitch in keys.whites:
            if pitch % 12 in (0, 5):
                x = keys.span(pitch)[0]
                painter.drawLine(QPointF(x, 0), QPointF(x, strike))
        timeline = self.timeline
        if timeline is not None:
            painter.setClipRect(QRectF(0, 0, self.width(), strike))
            self._grid(painter, timeline, strike, per_beat)
            self._notes(painter, timeline, keys, strike, per_beat)
            painter.setClipping(False)
        fills = key_fills(self.held, self.expected, self.allowed, frozenset(), self.reveal)
        paint_keys(painter, keys, strike + 2, key_height - 2, fills)
        painter.setPen(QPen(QColor("#faf8e9"), 2))
        painter.drawLine(QPointF(0, strike), QPointF(self.width(), strike))
        painter.end()

    def _grid(
        self, painter: QPainter, timeline: SongTimeline, strike: float, per_beat: float
    ) -> None:
        """Draw beat lines, stronger bar lines, and bar numbers."""
        bar = timeline.time.numerator
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        painter.setFont(font)
        first = max(0, int(self.beat))
        for beat in range(first, int(self.beat + strike / per_beat) + 2):
            y = strike - (beat - self.beat) * per_beat
            downbeat = beat % bar == 0
            painter.setPen(QPen(QColor("#3d5d66" if downbeat else theme.NIGHT_LINE), 1))
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
            if downbeat:
                painter.setPen(QColor("#8fb0b5"))
                painter.drawText(QPointF(6, y - 4), str(beat // bar + 1))

    def _notes(
        self,
        painter: QPainter,
        timeline: SongTimeline,
        keys: KeyGeometry,
        strike: float,
        per_beat: float,
    ) -> None:
        """Draw each visible note as a rounded bar above its key."""
        horizon = self.beat + strike / per_beat
        low = bisect_left(self._starts, self.beat - self._longest)
        high = bisect_right(self._starts, horizon)
        painter.setPen(Qt.PenStyle.NoPen)
        for note in timeline.notes[low:high]:
            start, length = float(note.start_beat), float(note.duration)
            if start + length < self.beat or not keys.contains(note.pitch):
                continue
            left, width = keys.lane(note.pitch)
            bottom = strike - (start - self.beat) * per_beat
            height = max(6.0, length * per_beat - 3)
            color = QColor(theme.RIGHT_HAND if note.hand == Hand.RIGHT else theme.LEFT_HAND)
            if note.hand not in self.hands:
                color.setAlpha(80)
            elif start <= self.beat:
                color = color.lighter(125)
            path = QPainterPath()
            path.addRoundedRect(QRectF(left, bottom - height, width, height), 3.5, 3.5)
            painter.fillPath(path, color)


def _field(caption: str, widget: QWidget) -> QVBoxLayout:
    """Stack a small caption above a control."""
    column = QVBoxLayout()
    column.setSpacing(2)
    label = QLabel(caption.upper())
    label.setProperty("role", "heading")
    column.addWidget(label)
    column.addWidget(widget)
    return column


class SongStudioPanel(QWidget):
    """Choose a piece and how to practise it; every change takes effect immediately."""

    configured = Signal(object)
    view_changed = Signal(str)

    def __init__(self, log: AttemptLog) -> None:
        """Build the controls and restore previously imported songs."""
        super().__init__()
        self.log = log
        self.timelines: list[SongTimeline] = [score.compile() for score in ALL_SCORES]
        self.builtin_count = len(self.timelines)
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        first = QHBoxLayout()
        self.songs = QComboBox()
        for index, score in enumerate(ALL_SCORES):
            self.songs.addItem(score.title)
            self.songs.setItemData(index, score.description, Qt.ItemDataRole.ToolTipRole)
        first.addLayout(_field("Piece", self.songs), 3)
        self.hands = QComboBox()
        self.hands.addItems(list(HANDS))
        self.hands.setToolTip("The hand you play. The piano plays the other hand for you.")
        first.addLayout(_field("You play", self.hands), 1)
        self.mode = QComboBox()
        self.mode.addItems(["Wait", "Tempo"])
        self.mode.setToolTip(
            "Wait: the music follows you and nothing is timed.\n"
            "Tempo: a count-in, then every attack is graded against the beat."
        )
        first.addLayout(_field("Mode", self.mode), 1)
        self.scale = QSpinBox()
        self.scale.setRange(25, 125)
        self.scale.setSingleStep(5)
        self.scale.setValue(70)
        self.scale.setSuffix(" %")
        self.scale.setToolTip("Playback speed as a percentage of the written tempo.")
        first.addLayout(_field("Speed", self.scale), 1)
        self.view = QComboBox()
        self.view.addItems(["Split", "Staff", "Falling notes"])
        first.addLayout(_field("View", self.view), 1)
        layout.addLayout(first)
        second = QHBoxLayout()
        self.a = QSpinBox()
        self.b = QSpinBox()
        second.addWidget(QLabel("Measures"))
        second.addWidget(self.a)
        second.addWidget(QLabel("to"))
        second.addWidget(self.b)
        self.loop = QCheckBox("Loop this section")
        self.ramp = QCheckBox("Auto-ramp")
        self.ramp.setToolTip(
            "In Tempo mode, three passes in a row at 95% or better raise the speed by 5%."
        )
        second.addSpacing(10)
        second.addWidget(self.loop)
        second.addWidget(self.ramp)
        second.addStretch(1)
        imported = QPushButton("Import MIDI…")
        imported.setProperty("role", "quiet")
        imported.clicked.connect(self.import_file)
        second.addWidget(imported)
        layout.addLayout(second)
        self.message = QLabel("")
        self.message.setProperty("role", "muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        for widget in (self.songs, self.hands, self.mode, self.view, self.a, self.b, self.scale):
            widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        for check in (self.loop, self.ramp):
            check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._restore_imports()
        self._set_measures(self.timelines[0])
        self.songs.currentIndexChanged.connect(self._song_changed)
        self.view.currentTextChanged.connect(self.view_changed.emit)
        for combo in (self.hands, self.mode):
            combo.currentIndexChanged.connect(self._apply)
        for spin in (self.scale, self.a, self.b):
            spin.valueChanged.connect(self._apply)
        for check in (self.loop, self.ramp):
            check.toggled.connect(self._apply)
        self._describe()

    def has_staff(self, timeline: SongTimeline | None = None) -> bool:
        """Report whether a song has engraved notation (imports are falling notes only)."""
        chosen = timeline or self.timelines[self.songs.currentIndex()]
        return any(chosen.song_id == score.song_id for score in ALL_SCORES)

    def _restore_imports(self) -> None:
        """Reload stored imports whose track assignment was saved."""
        for path in sorted(
            p for p in custom_songs_dir().iterdir() if p.suffix.lower() in (".mid", ".midi")
        ):
            try:
                restored = MidiImport(path)
                saved = self.log.preference(f"track_assignment:{restored.digest}")
                if saved:
                    self._add(restored.timeline(_assignment(json.loads(saved))))
            except (ValueError, OSError):
                continue

    def _add(self, timeline: SongTimeline) -> int:
        """Add a song to the list unless it is already there; return its index."""
        for index, existing in enumerate(self.timelines):
            if existing.song_id == timeline.song_id:
                return index
        self.timelines.append(timeline)
        self.songs.addItem(f"{timeline.title} (imported)")
        return len(self.timelines) - 1

    def _set_measures(self, timeline: SongTimeline) -> None:
        """Offer the whole piece as the section to practise."""
        total = timeline.measure_count
        for spin in (self.a, self.b):
            spin.setRange(1, total)
        self.a.setValue(1)
        self.b.setValue(total)

    def _describe(self) -> None:
        """Explain the chosen mode in a sentence, including what mastery asks for."""
        if self.mode.currentText() == "Wait":
            text = "Wait mode • the music follows you, so take your time and get the notes right."
        else:
            text = (
                "Tempo mode • play with the click after the count-in. A piece is mastered in "
                "Tempo mode at 80% speed or faster with 90% of its notes on time."
            )
        if not self.has_staff():
            text += " Imported songs are shown as falling notes."
        self.message.setStyleSheet("")
        self.message.setText(text)

    def _song_changed(self, index: int) -> None:
        """Reset the section for the newly chosen piece, then apply it."""
        if self._loading:
            return  # show_config is filling the controls and will finish the job itself
        self._loading = True
        self._set_measures(self.timelines[index])
        self._loading = False
        self.view_changed.emit(self.current_view())
        self._apply()

    def current_view(self) -> str:
        """Return the view to use; a song without notation is always falling notes."""
        return self.view.currentText() if self.has_staff() else "Falling notes"

    def current_config(self) -> SongConfig:
        """Build a configuration from the controls; raises ValueError if they conflict."""
        return SongConfig(
            self.timelines[self.songs.currentIndex()],
            self.mode.currentText(),
            HANDS[self.hands.currentText()],
            self.scale.value() / 100,
            self.a.value(),
            self.b.value(),
            self.loop.isChecked(),
            self.ramp.isChecked(),
        )

    def _apply(self) -> None:
        """Send the current choices to the engine, or explain why they cannot be used."""
        if self._loading:
            return
        try:
            config = self.current_config()
        except ValueError as exc:
            self.message.setStyleSheet(f"color: {theme.RED};")
            self.message.setText(str(exc))
            return
        self._describe()
        self.configured.emit(config)

    def show_config(self, config: SongConfig) -> None:
        """Make the controls reflect a configuration chosen elsewhere, without re-sending it."""
        self._loading = True
        index = self._add(config.timeline)
        self.songs.setCurrentIndex(index)
        self._set_measures(config.timeline)
        self.mode.setCurrentText(config.mode)
        self.hands.setCurrentText({"rh": "Right", "lh": "Left", "both": "Both"}[config.hand_name])
        self.scale.setValue(round(config.tempo_scale * 100))
        self.a.setValue(config.start_measure)
        self.b.setValue(config.end_measure or config.timeline.measure_count)
        self.loop.setChecked(config.loop)
        self.ramp.setChecked(config.auto_ramp)
        self._loading = False
        self._describe()
        self.view_changed.emit(self.current_view())

    def import_file(self) -> None:
        """Import a MIDI file: assign its tracks to hands and keep a copy for next time."""
        start = str(self.log.preference_value("import_dir", str(Path.home())))
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import piano MIDI", start, "Standard MIDI (*.mid *.midi)"
        )
        if not filename:
            return
        source = Path(filename)
        try:
            self.log.set_preference("import_dir", json.dumps(str(source.parent)))
            imported = MidiImport(source)
            key = f"track_assignment:{imported.digest}"
            dialog = TrackAssignmentDialog(imported, self.log.preference(key))
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            timeline = imported.timeline(dialog.assignment())
            self.log.set_preference(key, dialog.saved_json())
            copy = custom_songs_dir() / f"{imported.digest[:12]}_{source.name}"
            if not copy.exists():
                copy.write_bytes(source.read_bytes())
            index = self._add(timeline)
            if self.songs.currentIndex() == index:
                self._apply()
            else:
                self.songs.setCurrentIndex(index)
        except (ValueError, OSError) as exc:
            self.message.setStyleSheet(f"color: {theme.RED};")
            self.message.setText(f"Could not import {source.name} • {exc}")
