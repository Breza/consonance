"""The application window: header, tabs, the realtime worker, and keyboard input."""

import atexit
import json
import logging
import random
import sys
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from consonance.core.builtin_scores import score_by_id
from consonance.core.curriculum import ITEMS, UNITS, StudyConfig
from consonance.core.db import AttemptLog, utc_now
from consonance.core.engine import SCENES, Action, Command, GameConfig
from consonance.core.home import restore_song, song_bookmark
from consonance.core.midi_output import Settings
from consonance.core.notation import Hand, pitch_name
from consonance.core.plan import PlanStep
from consonance.core.song_session import SongConfig
from consonance.io.midi_ports import MidiPorts, base_name, match_port, suggest_ports
from consonance.io.paths import database_path, log_path
from consonance.io.session_worker import ConnectPorts, RealtimeSessionWorker, Request
from consonance.ui import theme
from consonance.ui.dashboard import Dashboard, _dot
from consonance.ui.practice import PracticeView
from consonance.ui.settings import SettingsPanel, settings_json
from consonance.ui.text_font import ensure_text_font

logger = logging.getLogger("consonance")
WHITE = dict(zip("ASDFGHJKL", (0, 2, 4, 5, 7, 9, 11, 12, 14), strict=True))
BLACK = dict(zip("WETYUOP", (1, 3, 6, 8, 10, 13, 15), strict=True))
NOTE_KEYS = WHITE | BLACK
COMMAND_KEYS = {"R": Action.REPLAY, "N": Action.NEXT, "H": Action.HINT}
PORT_POLL_MS = 2000

__all__ = ["BLACK", "SCENES", "WHITE", "MainWindow", "main"]


class MainWindow(QMainWindow):
    """Own the worker and the three screens, and translate input into worker requests."""

    def __init__(self, *, start_worker: bool = True) -> None:
        """Build the window; with ``start_worker`` false nothing realtime is started."""
        super().__init__()
        ensure_text_font()
        self.setWindowTitle("Consonance • Piano practice")
        self.octave = 4
        self.key_pitches: dict[str, int] = {}
        self.log = AttemptLog(database_path())
        self.log.ensure_schedule_current()
        self.settings = Settings.from_json(self.log.preference("settings"))
        self.worker = RealtimeSessionWorker(database_path(), rng=random.Random())
        self.ports = MidiPorts()
        self._worker_started = start_worker
        self._link_shown: tuple[str, str, str, int] | None = None
        self._hint_shown: int | None = None
        self._last_attempt: tuple[str, str] | None = None
        self._user_disconnected = False
        self._saved_seen = 0
        self._focus_started: str | None = None
        self._focus_items: frozenset[str] = frozenset()
        link = self.log.preference_value("midi", {})
        self.link_prefs: dict[str, Any] = link if isinstance(link, dict) else {}
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(self._build_header())
        self.banner = self._build_banner()
        layout.addWidget(self.banner)
        self.tabs = QTabWidget()
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setExpanding(False)
        self.dashboard = Dashboard(self.log)
        self.dashboard.open_item.connect(self.open_item)
        self.dashboard.open_step.connect(self.open_step)
        self.dashboard.start_step.connect(self.start_step)
        self.dashboard.open_piece.connect(self.continue_piece)
        self.dashboard.open_game.connect(self.open_game)
        self.tabs.addTab(self.dashboard, "Home")
        self.practice = PracticeView(self.log, self.settings)
        self.practice.submit.connect(self._submit_practice)
        self.practice.settings_edited.connect(self.save_settings)
        self.practice.note_on.connect(lambda pitch: self._send_note(pitch, True))
        self.practice.note_off.connect(lambda pitch: self._send_note(pitch, False))
        self.practice.finish_requested.connect(lambda: self.tabs.setCurrentWidget(self.dashboard))
        self.tabs.addTab(self.practice, "Practice")
        self.settings_panel = SettingsPanel(
            self.settings, bool(self.link_prefs.get("auto_connect", True))
        )
        self.settings_panel.changed.connect(self.save_settings)
        self.settings_panel.connect_requested.connect(self._manual_connect)
        self.settings_panel.auto_connect_changed.connect(self._auto_connect_changed)
        self.tabs.addTab(self.settings_panel, "Settings")
        self._active_tab: QWidget | None = self.tabs.currentWidget()
        self.tabs.currentChanged.connect(self.tab_changed)
        layout.addWidget(self.tabs, 1)
        self.setStyleSheet(theme.STYLE)
        self._size_to_screen()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.render_snapshot)
        self.port_timer = QTimer(self)
        self.port_timer.setInterval(PORT_POLL_MS)
        self.port_timer.timeout.connect(self.poll_ports)
        self.practice.set_progress(self.dashboard.states)
        scene = self.practice.prefs.get("scene")
        self.practice.choose_mode(scene if scene in SCENES else "keys")
        if start_worker:
            self.worker.start()
            self.worker.submit(self.settings)
            atexit.register(self.worker.close)
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.worker.close)
                app.installEventFilter(self)
            self.timer.start()
            self.port_timer.start()
            self.poll_ports()
        self.render_snapshot()

    def _build_header(self) -> QHBoxLayout:
        """Create the title, the connection indicator, and the panic button."""
        top = QHBoxLayout()
        top.setContentsMargins(18, 10, 14, 6)
        title = QLabel("Consonance")
        title.setStyleSheet("font-size: 28px; font-weight: 600;")
        top.addWidget(title, 1)
        self.link_button = QPushButton("")
        self.link_button.setProperty("role", "quiet")
        self.link_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.link_button.setToolTip("Open the MIDI settings")
        self.link_button.clicked.connect(lambda: self.tabs.setCurrentWidget(self.settings_panel))
        top.addWidget(self.link_button)
        panic = QPushButton("MIDI Panic")
        panic.setProperty("role", "quiet")
        panic.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        panic.setToolTip(
            "Silence every note and pedal on all channels, including notes you are holding, "
            "and forget any key the app believes is stuck down."
        )
        panic.clicked.connect(self._panic)
        top.addWidget(panic)
        return top

    def _build_banner(self) -> QFrame:
        """Create the hidden banner that offers to fix a channel mismatch."""
        banner = QFrame()
        banner.setProperty("role", "banner")
        row = QHBoxLayout(banner)
        row.setContentsMargins(14, 6, 14, 6)
        self.banner_text = QLabel("")
        self.banner_text.setWordWrap(True)
        row.addWidget(self.banner_text, 1)
        self.banner_button = QPushButton("")
        self.banner_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.banner_button.clicked.connect(self._use_hinted_channel)
        row.addWidget(self.banner_button)
        banner.setVisible(False)
        return banner

    def _size_to_screen(self) -> None:
        """Open at the size last used, or a comfortable one, never larger than the screen."""
        saved = self.log.preference_value("window", None)
        wanted = (1180, 900)
        if isinstance(saved, list) and len(saved) == 2 and all(isinstance(v, int) for v in saved):
            wanted = (max(900, saved[0]), max(640, saved[1]))
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(*wanted)
            return
        area = screen.availableGeometry()
        self.resize(min(wanted[0], area.width() - 40), min(wanted[1], area.height() - 60))

    def tab_changed(self, index: int) -> None:
        """Bring the screen being shown up to date."""
        current = self.tabs.widget(index)
        if self._active_tab is self.practice and current is not self.practice:
            self._submit_practice(Command(Action.PAUSE))
        self._active_tab = current
        if self.tabs.widget(index) is self.dashboard:
            self.dashboard.refresh()
        self.practice.set_progress(self.log.schedule_states())
        self._release_keys()

    def open_item(self, item_id: str) -> None:
        """Open one curriculum item for practice, with its unit-mates queued behind it."""
        item = ITEMS[item_id]
        if item.mode == "song":
            score = score_by_id(item.song_id)
            if score is None:
                return
            hands = frozenset(Hand) if item.hand == "both" else frozenset({Hand(item.hand)})
            self.practice.open_song(SongConfig(score.compile(), hands=hands))
        else:
            unit = UNITS[item.unit - 1]
            others = tuple(i for i in unit.items if i.mode == item.mode and i.item_id != item_id)
            self.practice.open_study((item, *others), f"Unit {unit.number} • {unit.title}")
        self.tabs.setCurrentWidget(self.practice)

    def open_step(self, step: PlanStep) -> None:
        """Open one step of today's plan."""
        items = tuple(ITEMS[item_id] for item_id in step.item_ids if item_id in ITEMS)
        if not items:
            return
        if step.mode == "song":
            self.open_item(items[0].item_id)
            return
        self.practice.open_study(items, f"Today's plan • {step.title}")
        self.tabs.setCurrentWidget(self.practice)

    def open_game(self, game: str, level: int = -1) -> None:
        """Open Note Rush or Melody Echo at its last-used level."""
        self.practice.choose_mode(game)
        self.tabs.setCurrentWidget(self.practice)

    def _submit_practice(self, request: Request) -> None:
        """Remember the piece actually played, then pass the typed request to the worker."""
        if isinstance(request, StudyConfig | SongConfig | GameConfig):
            self._focus_started = None
            self._focus_items = frozenset()
            self.practice.show_session_goal(0, 0)
        if (
            isinstance(request, Command)
            and (
                request.action in (Action.PLAY, Action.REPLAY)
                or request.action == Action.PAUSE
                and self.practice.running
            )
            and self.practice.scene == "song"
            and self.practice.song_config is not None
        ):
            self.log.set_preference(
                "home_song", json.dumps(song_bookmark(self.practice.song_config))
            )
        self.worker.submit(request)

    def start_step(self, step: PlanStep) -> None:
        """Prepare one suggested activity and begin it with its normal drill/count-in rules."""
        self.open_step(step)
        if step.mode != "song":
            self._focus_started = utc_now()
            self._focus_items = frozenset(step.item_ids)
            self.practice.show_session_goal(0, len(self._focus_items))
        self._submit_practice(Command(Action.PLAY))

    def continue_piece(self, song_id: str) -> None:
        """Restore the last played section, hands and tempo, including imported pieces."""
        timelines = self.practice.song_panel.timelines
        config = restore_song(self.log.preference_value("home_song"), timelines)
        if config is None or config.timeline.song_id != song_id:
            timeline = next((t for t in timelines if t.song_id == song_id), None)
            if timeline is None:
                self.practice.choose_mode("song")
                self.tabs.setCurrentWidget(self.practice)
                self.practice.song_panel.message.setText(
                    "That imported piece is no longer available. "
                    "Choose another piece or import it again."
                )
                return
            config = SongConfig(timeline)
        self.practice.open_song(config)
        self.tabs.setCurrentWidget(self.practice)

    def save_settings(self, settings: Settings) -> None:
        """Store new settings and hand them to the worker and both screens."""
        self.settings = settings
        self.log.set_preference("settings", settings_json(settings))
        self.worker.submit(settings)
        self.practice.adopt_settings(settings)
        self.settings_panel.adopt(settings)

    def _panic(self) -> None:
        """Silence everything and forget any key believed to be held."""
        self.key_pitches.clear()
        self.worker.submit(Command(Action.PANIC))

    def _use_hinted_channel(self) -> None:
        """Listen on the channel the piano is actually sending on."""
        channel = self._hint_shown
        if channel is None:
            return
        spare = [c for c in range(16) if c not in (channel, 9)]
        piano = self.settings.piano_channel
        click = self.settings.metronome_channel
        if piano == channel:
            piano = next(c for c in spare if c != click)
        if click == channel:
            click = next(c for c in spare if c != piano)
        try:
            self.save_settings(
                replace(
                    self.settings,
                    user_channel=channel,
                    piano_channel=piano,
                    metronome_channel=click,
                )
            )
        except ValueError:
            logger.exception("Could not switch to channel %s", channel + 1)

    def _remember_link(self, **values: Any) -> None:
        """Keep connection preferences for the next launch."""
        self.link_prefs.update(values)
        self.log.set_preference("midi", json.dumps(self.link_prefs))

    def _manual_connect(self, input_name: str, output_name: str) -> None:
        """Connect or disconnect because the player asked for it."""
        self._user_disconnected = not input_name and not output_name
        self._last_attempt = (input_name, output_name)
        self._release_keys()
        self.worker.submit(ConnectPorts(input_name, output_name))

    def _auto_connect_changed(self, on: bool) -> None:
        """Remember whether to connect on sight, and try straight away if so."""
        self._remember_link(auto_connect=on)
        self._user_disconnected = False
        self._last_attempt = None
        if on and self._worker_started:
            self.poll_ports()

    def poll_ports(self) -> None:
        """Notice ports appearing and disappearing; this never runs on the MIDI thread.

        A connected port that vanishes is closed at once. When nothing is connected and
        automatic connection is on, the remembered piano (or the only plausible one) is
        connected as soon as it appears, once per appearance.
        """
        try:
            inputs, outputs = self.ports.names()
        except Exception as exc:
            self.settings_panel.show_link(f"MIDI is unavailable on this computer • {exc}", False)
            return
        self.settings_panel.show_ports(inputs, outputs)
        latest = self.worker.latest
        lost_in = latest.midi_in and latest.midi_in not in inputs
        lost_out = latest.midi_out and latest.midi_out not in outputs
        if lost_in or lost_out:
            self._last_attempt = None
            self._release_keys()
            self.worker.submit(ConnectPorts("", ""))
            return
        if latest.midi_in or self._user_disconnected:
            return
        if not self.link_prefs.get("auto_connect", True):
            return
        wanted_in = match_port(str(self.link_prefs.get("input", "")), inputs)
        wanted_out = match_port(str(self.link_prefs.get("output", "")), outputs)
        if not wanted_in:
            wanted_in, guessed_out = suggest_ports(inputs, outputs)
            wanted_out = wanted_out or guessed_out
        if not wanted_in:
            self._last_attempt = None
        elif (wanted_in, wanted_out) != self._last_attempt:
            self._last_attempt = (wanted_in, wanted_out)
            self.settings_panel.select_ports(wanted_in, wanted_out)
            self.worker.submit(ConnectPorts(wanted_in, wanted_out))

    def _show_link(self, midi_in: str, midi_out: str, error: str) -> None:
        """Describe the connection in the header and on the Settings screen."""
        state = (midi_in, midi_out, error, self.octave)
        if state == self._link_shown:
            return
        self._link_shown = state
        if midi_in:
            name = base_name(midi_in)
            text = f"Piano connected • {name}"
            if not midi_out:
                text += " (listening only)"
            detail = f"Listening to {midi_in}" + (
                f" and playing through {midi_out}."
                if midi_out
                else ". No MIDI out is open, "
                "so the piano cannot play accompaniment, clicks or ear prompts."
            )
            self.link_button.setIcon(_dot(theme.GREEN))
            self._remember_link(input=midi_in, output=midi_out)
        else:
            home = pitch_name(12 * (self.octave + 1))
            text = f"No piano connected • computer keys play from {home}"
            detail = (
                "Nothing is connected. Switch the piano on and it will be found automatically, "
                "or choose its ports above and press Connect. Meanwhile the on-screen keys and "
                "the computer keyboard (A S D F G H J K L, with Z and X to change octave) work "
                "silently."
            )
            self.link_button.setIcon(_dot(theme.FAINT, filled=False))
        self.link_button.setText(text)
        self.settings_panel.show_link(error or detail, bool(midi_in) and not error)

    def _show_hint(self, channel: int | None) -> None:
        """Offer to switch input channel when notes arrive on an unexpected one."""
        if channel == self._hint_shown:
            return
        self._hint_shown = channel
        self.banner.setVisible(channel is not None)
        if channel is not None:
            self.banner_text.setText(
                f"Your piano is sending notes on MIDI channel {channel + 1}, but Consonance is "
                f"listening on channel {self.settings.user_channel + 1}, so they are being ignored."
            )
            self.banner_button.setText(f"Listen on channel {channel + 1}")

    def render_snapshot(self) -> None:
        """Draw the worker's latest snapshot and keep the header in step with it."""
        snapshot = self.worker.latest
        self.practice.show_snapshot(snapshot)
        self._show_link(snapshot.midi_in, snapshot.midi_out, snapshot.error)
        self.dashboard.set_connection(bool(snapshot.midi_in), bool(snapshot.midi_out))
        self._show_hint(snapshot.channel_hint)
        if self.worker.saved != self._saved_seen:
            self._saved_seen = self.worker.saved
            if self._focus_started:
                done = self.log.completed_items_since(self._focus_started) & self._focus_items
                self.practice.show_session_goal(len(done), len(self._focus_items))
            if self.tabs.currentWidget() is self.dashboard:
                self.dashboard.refresh()

    def _send_note(self, pitch: int, down: bool) -> None:
        """Feed a silent note from the computer keyboard or on-screen keys to the engine."""
        status = (0x90 if down else 0x80) | self.settings.user_channel
        self.worker.receive((status, pitch, 80 if down else 0))

    def _release_keys(self) -> None:
        """Let go of every computer-keyboard note, so none can be left stuck down."""
        for pitch in self.key_pitches.values():
            self._send_note(pitch, False)
        self.key_pitches.clear()

    def _keys_active(self) -> bool:
        """Report whether typing should play notes and drive the transport right now."""
        return (
            self.isActiveWindow()
            and self.tabs.currentWidget() is self.practice
            and QApplication.activePopupWidget() is None
            and QApplication.activeModalWidget() is None
        )

    def _handle_key(self, event: QKeyEvent, pressed: bool) -> bool:
        """Act on a practice key; return True if the event was one of ours."""
        blocked = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if event.modifiers() & blocked:
            return False
        code = event.key()
        key = " " if code == Qt.Key.Key_Space else chr(code) if 0x41 <= code <= 0x5A else ""
        if not key or key not in (" ", "Z", "X", *COMMAND_KEYS, *NOTE_KEYS):
            return False
        if event.isAutoRepeat():
            return True
        if not pressed:
            pitch = self.key_pitches.pop(key, None)
            if pitch is not None:
                self._send_note(pitch, False)
            return True
        if key == " ":
            self.practice.toggle_play()
        elif key in COMMAND_KEYS:
            self.worker.submit(Command(COMMAND_KEYS[key]))
        elif key in ("Z", "X"):
            self._release_keys()
            self.octave = max(1, min(7, self.octave + (1 if key == "X" else -1)))
        elif key not in self.key_pitches:
            pitch = 12 * (self.octave + 1) + NOTE_KEYS[key]
            if 21 <= pitch <= 108:
                self.key_pitches[key] = pitch
                self._send_note(pitch, True)
        return True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Catch practice keys wherever focus is, so a focused dropdown cannot eat them."""
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and isinstance(event, QKeyEvent):
            if self._keys_active() and self._handle_key(event, kind == QEvent.Type.KeyPress):
                return True
        elif kind == QEvent.Type.WindowDeactivate and watched is self:
            self._release_keys()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Translate non-repeating laptop key presses into silent practice input."""
        practising = self.tabs.currentWidget() is self.practice
        if not (practising and self._handle_key(event, True)):
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Release a laptop practice key, ignoring auto-repeat."""
        if not self._handle_key(event, False):
            super().keyReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop the worker and close owned resources before accepting the close."""
        self.timer.stop()
        self.port_timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.worker.close()
        self.ports.close()
        if not self.isMaximized() and not self.isFullScreen():
            self.log.set_preference("window", json.dumps([self.width(), self.height()]))
        self.log.close()
        event.accept()


def _configure_logging() -> None:
    """Send warnings and errors to a small rotating file in the data folder."""
    handler = RotatingFileHandler(log_path(), maxBytes=512_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("consonance")
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def report(kind: type[BaseException], value: BaseException, trace: Any) -> None:
        """Log an uncaught exception before the default handler prints it."""
        logger.error("Uncaught exception", exc_info=(kind, value, trace))
        sys.__excepthook__(kind, value, trace)

    sys.excepthook = report


def main() -> int:
    """Create the Qt application and run its desktop event loop."""
    _configure_logging()
    # Let the MIDI thread take the interpreter from a busy paint within a millisecond.
    sys.setswitchinterval(0.001)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
