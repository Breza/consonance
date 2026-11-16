import atexit
import json
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from consonance.core.builtin_scores import BUILTIN_SCORES, COORDINATION_SCORE
from consonance.core.curriculum import ITEMS, UNITS, StudyConfig
from consonance.core.db import AttemptLog
from consonance.core.engine import Action, Command
from consonance.core.midi_output import Settings
from consonance.core.notation import Hand
from consonance.core.song_session import SongConfig
from consonance.io.midi_ports import MidiPorts
from consonance.io.paths import data_dir
from consonance.io.session_worker import ConnectPorts, RealtimeSessionWorker
from consonance.ui.dashboard import Dashboard
from consonance.ui.graphs import EvennessGraph
from consonance.ui.settings import SettingsPanel, settings_json
from consonance.ui.song_studio import FallingNotes, SongStudioPanel
from consonance.ui.staff import GrandStaff
from consonance.ui.text_font import ensure_text_font

WHITE = dict(zip("ASDFGHJKL", (0, 2, 4, 5, 7, 9, 11, 12, 14), strict=True))
BLACK = dict(zip("WETYUOP", (1, 3, 6, 8, 10, 13, 15), strict=True))
SCENES = ("sight", "rhythm", "technique", "ear", "song")


class MainWindow(QMainWindow):
    def __init__(self, *, start_worker: bool = True) -> None:
        super().__init__()
        ensure_text_font()
        self.setWindowTitle("Consonance • Piano practice")
        self.resize(1150, 900)
        self.octave = 4
        self.key_pitches: dict[str, int] = {}
        self.log = AttemptLog(data_dir() / "practice.sqlite3")
        raw_settings = self.log.preference("settings")
        try:
            self.settings = Settings(**json.loads(raw_settings)) if raw_settings else Settings()
        except (ValueError, TypeError):
            self.settings = Settings()
        self.worker = RealtimeSessionWorker(data_dir() / "practice.sqlite3")
        self.ports = MidiPorts()
        self._worker_started = start_worker
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        title = QLabel("Consonance")
        title.setStyleSheet("font-size: 30px; font-weight: 600; padding: 14px;")
        top.addWidget(title, 1)
        panic = QPushButton("MIDI Panic")
        panic.clicked.connect(lambda: self.worker.submit(Command(Action.PANIC)))
        top.addWidget(panic)
        layout.addLayout(top)
        row = QHBoxLayout()
        self.inputs = QComboBox()
        self.outputs = QComboBox()
        row.addWidget(QLabel("MIDI In"))
        row.addWidget(self.inputs, 1)
        row.addWidget(QLabel("MIDI Out"))
        row.addWidget(self.outputs, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_ports)
        connect = QPushButton("Connect")
        connect.clicked.connect(self.connect_ports)
        row.addWidget(refresh)
        row.addWidget(connect)
        layout.addLayout(row)
        self.tabs = QTabWidget()
        self.dashboard = Dashboard(self.log)
        self.dashboard.open_item.connect(self.open_item)
        self.tabs.addTab(self.dashboard, "Home")
        self.practice = QWidget()
        practice_layout = QVBoxLayout(self.practice)
        self.scenes = QComboBox()
        self.scenes.addItems(
            ["Sight-Reader", "Rhythm Sniper", "Technique Lab", "Ear Trainer", "Song Studio"]
        )
        self.scenes.currentIndexChanged.connect(self.switch_scene)
        practice_layout.addWidget(self.scenes)
        self.song_panel = SongStudioPanel(self.log)
        self.song_panel.configured.connect(self.configure_song)
        self.song_panel.view_changed.connect(lambda _: self.render_snapshot())
        self.song_panel.seek_requested.connect(
            lambda beat: self.worker.submit(Command(Action.SEEK, value=beat))
        )
        practice_layout.addWidget(self.song_panel)
        self.staff = GrandStaff()
        practice_layout.addWidget(self.staff, 1)
        self.roll = FallingNotes()
        self.roll.timeline = self.song_panel.timelines[0]
        practice_layout.addWidget(self.roll, 1)
        self.ear_hint = QLabel(
            "Listen on the piano. Find the sound, then press Play for the next prompt."
        )
        practice_layout.addWidget(self.ear_hint)
        self.graph = EvennessGraph()
        practice_layout.addWidget(self.graph)
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 17px; padding: 14px;")
        practice_layout.addWidget(self.status)
        self.held_label = QLabel("")
        practice_layout.addWidget(self.held_label)
        controls = QHBoxLayout()
        for action in (Action.PLAY, Action.PAUSE, Action.REPLAY):
            button = QPushButton(action.value)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda checked=False, a=action: self.worker.submit(Command(a)))
            controls.addWidget(button)
        names = QCheckBox("Show note names")
        names.toggled.connect(self.set_names)
        guides = QCheckBox("Landmark guides")
        guides.toggled.connect(self.set_guides)
        controls.addWidget(names)
        controls.addWidget(guides)
        practice_layout.addLayout(controls)
        practice_layout.addWidget(QLabel("Silent dev keys: A–L / W–P • Z/X octave • R replay"))
        self.tabs.addTab(self.practice, "Practice")
        self.settings_panel = SettingsPanel(self.settings)
        self.settings_panel.changed.connect(self.save_settings)
        self.tabs.addTab(self.settings_panel, "Settings")
        self.tabs.currentChanged.connect(self.tab_changed)
        layout.addWidget(self.tabs)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f5f5ee; color: #243c42; font-family: 'Segoe UI'; }
            QPushButton { background: #deebe5; border: 1px solid #b4cbc3;
                          border-radius: 6px; padding: 9px 16px; }
            QPushButton:hover { background: #c1ded1; }
            QComboBox, QSpinBox { padding: 7px; background: #fffdf8; }
            QTabBar::tab { padding: 10px 22px; }
        """)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.render_snapshot)
        if start_worker:
            self.worker.start()
            self.worker.submit(self.settings)
            atexit.register(self.worker.close)
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.worker.close)
            self.timer.start()
            self.refresh_ports()
        self.render_snapshot()

    def tab_changed(self, index: int) -> None:
        if index == 0:
            self.dashboard.refresh()

    def open_item(self, item_id: str) -> None:
        item = ITEMS[item_id]
        index = SCENES.index(item.mode)
        self.scenes.blockSignals(True)
        self.scenes.setCurrentIndex(index)
        self.scenes.blockSignals(False)
        self.worker.submit(Command(Action.SWITCH_SCENE, item.mode))
        if item.mode == "song":
            sid = item_id.split(":")[1] if item.kind == "song" else "coordination"
            score = next(s for s in (*BUILTIN_SCORES, COORDINATION_SCORE) if s.song_id == sid)
            hands = (
                frozenset(Hand)
                if item.hand == "both" or item.kind == "coordination"
                else (frozenset({Hand.RIGHT if item.hand == "rh" else Hand.LEFT}))
            )
            config = SongConfig(score.compile(), hands=hands, item_id=item_id)
            self.configure_song(config)
        else:
            siblings = tuple(
                i
                for i in UNITS[item.unit - 1].items
                if i.mode == item.mode and i.item_id != item_id
            )
            self.worker.submit(StudyConfig((item, *siblings)))
        self.staff.guides = item.unit == 1
        self.tabs.setCurrentWidget(self.practice)
        self.setFocus()

    def save_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.log.set_preference("settings", settings_json(settings))
        self.worker.submit(settings)

    def configure_song(self, config: SongConfig) -> None:
        self.song_panel.show_config(config)
        self.roll.timeline = config.timeline
        self.worker.submit(config)
        self.setFocus()

    def switch_scene(self, index: int) -> None:
        self.worker.submit(Command(Action.SWITCH_SCENE, SCENES[index]))
        self.setFocus()

    def set_names(self, value: bool) -> None:
        self.staff.show_names = value

    def set_guides(self, value: bool) -> None:
        self.staff.guides = value

    def refresh_ports(self) -> None:
        try:
            inputs, outputs = self.ports.names()
            self.inputs.clear()
            self.outputs.clear()
            self.inputs.addItems(["Unplugged", *inputs])
            self.outputs.addItems(["Unplugged", *outputs])
        except Exception as exc:
            self.status.setText(f"MIDI unavailable: {exc}")

    def connect_ports(self) -> None:
        self.worker.submit(
            ConnectPorts(
                self.inputs.currentText() if self.inputs.currentIndex() else "",
                self.outputs.currentText() if self.outputs.currentIndex() else "",
            )
        )
        self.setFocus()

    def render_snapshot(self) -> None:
        snapshot = self.worker.latest
        self.scenes.blockSignals(True)
        self.scenes.setCurrentIndex(SCENES.index(snapshot.scene))
        self.scenes.blockSignals(False)
        song_view = self.song_panel.view.currentText()
        self.song_panel.setVisible(snapshot.scene == "song")
        self.roll.setVisible(snapshot.scene == "song" and song_view != "Staff")
        # Display compensation affects only these coordinates, never the worker clock.
        bpm = self.roll.timeline.tempo.points[0].bpm if self.roll.timeline else 72
        self.roll.beat = snapshot.beat + (
            self.settings.visual_offset_ms / 1000 * bpm / 60 * snapshot.tempo_scale
        )
        self.roll.held = snapshot.held
        self.roll.update()
        self.staff.layout_data = snapshot.layout
        self.staff.playhead_x = 11 + snapshot.prompt_index * 12.5
        self.staff.setVisible(
            snapshot.scene != "ear"
            and not (snapshot.scene == "song" and song_view == "Falling Notes")
        )
        self.staff.viewport_width = 64 if snapshot.scene == "song" else None
        self.staff.scroll_x = 0
        if snapshot.scene == "song":
            beats = self.roll.timeline.time.numerator if self.roll.timeline else 4
            self.staff.scroll_x = (
                int(self.roll.beat / beats) * 48 + (self.roll.beat % beats) / beats * 34
            )
            self.staff.playhead_x = 11 + self.staff.scroll_x
        self.ear_hint.setVisible(snapshot.scene == "ear")
        self.graph.setVisible(snapshot.scene == "technique")
        self.graph.values = snapshot.graph
        self.graph.velocities = snapshot.velocity_graph
        self.graph.update()
        self.staff.update()
        self.status.setText(f"{snapshot.error or snapshot.status}   •   {snapshot.completed} saved")
        self.held_label.setText("Keys held: " + " ".join(str(p) for p in sorted(snapshot.held)))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        key = event.text().upper()
        if key == "R":
            self.worker.submit(Command(Action.REPLAY))
        elif key in ("Z", "X"):
            self.octave = max(1, min(7, self.octave + (1 if key == "X" else -1)))
        elif key in WHITE | BLACK and key not in self.key_pitches:
            pitch = 12 * (self.octave + 1) + (WHITE | BLACK)[key]
            if 21 <= pitch <= 108:
                self.key_pitches[key] = pitch
                self.worker.receive((0x90 | self.settings.user_channel, pitch, 80))
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        pitch = self.key_pitches.pop(event.text().upper(), None)
        if pitch is not None:
            self.worker.receive((0x80 | self.settings.user_channel, pitch, 0))
        else:
            super().keyReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.timer.stop()
        self.worker.close()
        self.ports.close()
        self.log.close()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
