"""The practice screen: choose a mode and a set, then read, listen, play, and see how it went."""

import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from consonance.core.curriculum import (
    ITEMS,
    MODE_TITLES,
    UNITS,
    CurriculumItem,
    ItemSchedule,
    StudyConfig,
    items_for,
    recommended_unit,
)
from consonance.core.db import AttemptLog
from consonance.core.drills.games import ECHO_LEVELS, RUSH_LEVELS
from consonance.core.engine import SCENES, Action, Command, GameConfig, RenderSnapshot
from consonance.core.midi_output import Settings
from consonance.core.song_session import SongConfig
from consonance.ui import theme
from consonance.ui.graphs import EvennessGraph
from consonance.ui.icons import icon
from consonance.ui.keyboard import KeyboardWidget
from consonance.ui.song_studio import FallingNotes, SongStudioPanel
from consonance.ui.staff import GrandStaff
from consonance.ui.widgets import BeatIndicator, ChipRow, PromptCard, StatusBanner

STUDY_MODES = ("keys", "sight", "rhythm", "technique", "ear")
MODE_TIPS = {
    "keys": "Find keys and chords by name. Start here if the keyboard is new to you.",
    "sight": "Read notes, intervals and chords from the staff.",
    "rush": "A sixty-second reading sprint for a personal best.",
    "rhythm": "Tap written rhythms against the click.",
    "technique": "Five-finger patterns and scales, measured for evenness.",
    "ear": "Hear a note, interval or chord on the piano and find it.",
    "echo": "A melody that grows by one note each time you echo it.",
    "song": "Learn pieces hand by hand, at your own pace or in tempo.",
}
NAME_SCENES = ("keys", "sight", "rush", "technique", "song")
HINT_SCENES = ("keys", "sight", "rush", "technique", "ear")
TEMPO_SCENES = ("rhythm", "technique")
FEEDBACK_SECONDS = 0.9
STALE_FRAMES = 12  # about 200ms of frames from a mode that is being left


class PracticeView(QWidget):
    """Everything on the Practice tab. It draws snapshots and emits requests; no state of
    the music lives here."""

    submit = Signal(object)
    settings_edited = Signal(object)
    note_on = Signal(int)
    note_off = Signal(int)
    finish_requested = Signal()

    def __init__(self, log: AttemptLog, settings: Settings) -> None:
        """Build the screen; nothing is requested from the engine yet."""
        super().__init__()
        self.log = log
        self.settings = settings
        self.states: dict[str, ItemSchedule] = {}
        self.scene = "sight"
        self.song_config: SongConfig | None = None
        self.prefs: dict[str, Any] = {}
        saved = log.preference_value("ui", {})
        if isinstance(saved, dict):
            self.prefs = saved
        self._running = False
        self._filling = False
        self._leaving: str | None = None
        self._stale_frames = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        outer.addWidget(self.scroll_area)
        body = QWidget()
        self.scroll_area.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(8)
        layout.addLayout(self._build_modes())
        layout.addLayout(self._build_header())
        self.session_note = QWidget()
        self.session_note.setProperty("role", "sessionNote")
        session_row = QHBoxLayout(self.session_note)
        self.session_text = QLabel("")
        self.session_text.setWordWrap(True)
        session_row.addWidget(self.session_text, 1)
        self.finish_button = QPushButton("Finish here")
        self.finish_button.clicked.connect(self.finish_requested.emit)
        session_row.addWidget(self.finish_button)
        self.session_note.hide()
        layout.addWidget(self.session_note)
        self.song_panel = SongStudioPanel(log)
        self.song_panel.configured.connect(self._song_configured)
        self.song_panel.view_changed.connect(self._remember_view)
        layout.addWidget(self.song_panel)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.card = PromptCard()
        layout.addWidget(self.card, 3)
        self.staff = GrandStaff()
        layout.addWidget(self.staff, 4)
        self.roll = FallingNotes()
        layout.addWidget(self.roll, 5)
        self.graph = EvennessGraph()
        layout.addWidget(self.graph, 2)
        feedback = QHBoxLayout()
        self.beats = BeatIndicator()
        feedback.addWidget(self.beats)
        self.status = StatusBanner()
        feedback.addWidget(self.status, 1)
        layout.addLayout(feedback)
        self.keyboard = KeyboardWidget()
        self.keyboard.key_pressed.connect(self.note_on.emit)
        self.keyboard.key_released.connect(self.note_off.emit)
        layout.addWidget(self.keyboard, 2)
        layout.addLayout(self._build_controls())
        view = self.prefs.get("song_view")
        if isinstance(view, str):
            self.song_panel.view.setCurrentText(view)
        # Optional panels must not inflate the initial window before the first snapshot.
        self.show_snapshot(RenderSnapshot(scene="keys"))

    def _build_modes(self) -> QGridLayout:
        """Keep all eight practice modes reachable on smaller laptop windows."""
        row = QGridLayout()
        row.setSpacing(0)
        self.modes = QButtonGroup(self)
        self.mode_buttons: dict[str, QPushButton] = {}
        for index, scene in enumerate(SCENES):
            button = QPushButton(MODE_TITLES[scene])
            button.setCheckable(True)
            button.setProperty("role", "mode")
            button.setToolTip(MODE_TIPS[scene])
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda checked=False, s=scene: self.choose_mode(s))
            self.modes.addButton(button)
            self.mode_buttons[scene] = button
            row.addWidget(button, index // 4, index % 4)
        return row

    def _build_header(self) -> QVBoxLayout:
        """Create the title, set selector, instruction and tally chips."""
        column = QVBoxLayout()
        column.setSpacing(2)
        top = QHBoxLayout()
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setProperty("role", "title")
        top.addWidget(self.title, 1)
        self.set_label = QLabel("SET")
        self.set_label.setProperty("role", "heading")
        top.addWidget(self.set_label)
        self.sets = QComboBox()
        self.sets.setMinimumWidth(330)
        self.sets.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.sets.activated.connect(self._set_chosen)
        top.addWidget(self.sets)
        column.addLayout(top)
        bottom = QHBoxLayout()
        self.instruction = QLabel("")
        self.instruction.setProperty("role", "muted")
        self.instruction.setWordWrap(True)
        bottom.addWidget(self.instruction, 1)
        self.chips = ChipRow()
        bottom.addWidget(self.chips)
        column.addLayout(bottom)
        return column

    def _button(self, text: str, name: str, tip: str, role: str = "") -> QPushButton:
        """Create one transport button with a vector icon."""
        button = QPushButton(text)
        button.setIcon(icon(name, "white" if role == "primary" else theme.INK))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if role:
            button.setProperty("role", role)
        return button

    def _check(self, text: str, tip: str, checked: bool) -> QCheckBox:
        """Create one display option that never takes keyboard focus."""
        box = QCheckBox(text)
        box.setToolTip(tip)
        box.setChecked(checked)
        box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return box

    def _build_controls(self) -> QVBoxLayout:
        """Create the transport buttons, tempo control and display options."""
        column = QVBoxLayout()
        row = QHBoxLayout()
        column.addLayout(row)
        self.play_button = self._button("Play", "play", "Start or pause (Space)", "primary")
        self.play_button.setMinimumWidth(120)
        self.play_button.clicked.connect(self.toggle_play)
        self.again_button = self._button("Again", "again", "Start this one again (R)")
        self.again_button.clicked.connect(lambda: self.submit.emit(Command(Action.REPLAY)))
        self.next_button = self._button("Next", "next", "Move on to the next one (N)")
        self.next_button.clicked.connect(lambda: self.submit.emit(Command(Action.NEXT)))
        self.hint_button = self._button("Hint", "hint", "Show the answer on the keyboard (H)")
        self.hint_button.clicked.connect(lambda: self.submit.emit(Command(Action.HINT)))
        for button in (self.play_button, self.again_button, self.next_button, self.hint_button):
            row.addWidget(button)
        row.addSpacing(12)
        self.tempo_label = QLabel("Tempo")
        row.addWidget(self.tempo_label)
        self.tempo = QSpinBox()
        self.tempo.setRange(30, 200)
        self.tempo.setSuffix(" BPM")
        self.tempo.setValue(self.settings.tempo_bpm)
        self.tempo.setKeyboardTracking(False)
        self.tempo.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.tempo.valueChanged.connect(
            lambda value: self._edit_settings(tempo_bpm=value) if not self._filling else None
        )
        row.addWidget(self.tempo)
        row.addStretch(1)
        options = QHBoxLayout()
        column.addLayout(options)
        self.names = self._check(
            "Note names",
            "Label every note. Answers given with names showing are not counted toward mastery.",
            self.settings.show_names,
        )
        self.names.toggled.connect(lambda on: self._edit_settings(show_names=on))
        self.key_hints = self._check(
            "Key hints",
            "Always light the keys to press. Answers given with hints are not counted "
            "toward mastery.",
            self.settings.key_hints,
        )
        self.key_hints.toggled.connect(lambda on: self._edit_settings(key_hints=on))
        self.guides = self._check(
            "Landmark guides",
            "Tint the G line, the F line and both Middle C positions.",
            bool(self.prefs.get("guides", False)),
        )
        self.guides.toggled.connect(lambda on: self._remember("guides", on))
        self.fingering = self._check(
            "Finger numbers",
            "Show a finger number wherever the hand takes a new position.",
            bool(self.prefs.get("fingering", True)),
        )
        self.fingering.toggled.connect(lambda on: self._remember("fingering", on))
        self.show_call = self._check(
            "Show the piano's notes",
            "Light the keys while the piano plays the melody. Turn off to echo by ear alone.",
            bool(self.prefs.get("show_call", True)),
        )
        self.show_call.toggled.connect(self._show_call_changed)
        for box in (self.names, self.key_hints, self.guides, self.fingering, self.show_call):
            options.addWidget(box)
        options.addStretch(1)
        return column

    def show_session_goal(self, completed: int, total: int) -> None:
        """Offer a satisfying stopping point without imposing a timer or a pass condition."""
        self.session_note.setVisible(total > 0)
        if total:
            prefix = f"{min(completed, total)} of {total} exercises practised. "
            self.session_text.setText(
                prefix
                + (
                    "A good place to finish, or keep exploring."
                    if completed >= total
                    else "One small activity; you can finish whenever you like."
                )
            )

    def _remember(self, key: str, value: Any) -> None:
        """Keep a display preference for next time."""
        self.prefs[key] = value
        self.log.set_preference("ui", json.dumps(self.prefs))

    def _remember_view(self, view: str) -> None:
        """Keep the chosen song view."""
        self._remember("song_view", self.song_panel.view.currentText())

    def _edit_settings(self, **changes: Any) -> None:
        """Apply a settings change made on this screen and tell the application."""
        if self._filling:
            return
        try:
            self.settings = replace(self.settings, **changes)
        except ValueError:
            return
        self.settings_edited.emit(self.settings)

    def adopt_settings(self, settings: Settings) -> None:
        """Reflect settings that were changed elsewhere."""
        self.settings = settings
        self._filling = True
        self.tempo.setValue(settings.tempo_bpm)
        self.names.setChecked(settings.show_names)
        self.key_hints.setChecked(settings.key_hints)
        self._filling = False

    def set_progress(self, states: dict[str, ItemSchedule]) -> None:
        """Adopt the latest review states, used to offer due items and a sensible unit."""
        self.states = states

    def _fill_sets(self, entries: list[tuple[str, Any]], current: int) -> None:
        """Replace the contents of the set selector."""
        self.sets.clear()
        for label, data in entries:
            self.sets.addItem(label, data)
        self.sets.setCurrentIndex(max(0, min(current, len(entries) - 1)))

    def _study_sets(self, scene: str) -> tuple[list[tuple[str, Any]], int]:
        """List the sets a study mode offers and the index of the one to open by default."""
        now = datetime.now().astimezone()
        entries: list[tuple[str, Any]] = []
        due = [
            item.item_id
            for item in items_for(scene)
            if item.item_id in self.states
            and datetime.fromisoformat(self.states[item.item_id].due_at_utc) <= now
        ]
        if due:
            entries.append((f"Due now • {len(due)} to review", due))
        target = recommended_unit(self.states)
        default = -1
        for unit in UNITS:
            ids = [item.item_id for item in unit.items if item.mode == scene]
            if ids:
                if unit.number <= target or default < 0:
                    default = len(entries)
                entries.append((f"Unit {unit.number} • {unit.title} ({len(ids)})", ids))
        everything = [item.item_id for item in items_for(scene)]
        entries.append((f"Everything • all units ({len(everything)})", everything))
        return entries, max(0, default)

    def _enter(self, scene: str) -> None:
        """Note a requested change of mode.

        The engine answers within a few milliseconds; until it does, snapshots still
        describe the mode being left and are not drawn, so the screen never flickers back.
        """
        self.scroll_area.verticalScrollBar().setValue(0)
        if scene != self.scene:
            self._leaving, self._stale_frames = self.scene, STALE_FRAMES
        self.scene = scene

    def choose_mode(self, scene: str) -> None:
        """Switch practice mode, opening the set a learner most likely wants."""
        self._enter(scene)
        self._remember("scene", scene)
        self.keyboard.reset_range()
        if scene == "song":
            try:
                self._song_configured(self.song_panel.current_config())
            except ValueError:
                pass
        elif scene in ("rush", "echo"):
            levels = RUSH_LEVELS if scene == "rush" else ECHO_LEVELS
            saved = self.prefs.get(f"{scene}_level", 1)
            level = saved if isinstance(saved, int) and 0 <= saved < len(levels) else 1
            self._fill_sets([(title, index) for index, (title, _) in enumerate(levels)], level)
            self.submit.emit(GameConfig(scene, level, self.show_call.isChecked()))
        else:
            entries, default = self._study_sets(scene)
            self._fill_sets(entries, default)
            self._set_chosen(default)

    def _set_chosen(self, index: int) -> None:
        """Open the set or game level picked in the selector."""
        data = self.sets.itemData(index)
        if self.scene in ("rush", "echo") and isinstance(data, int):
            self._remember(f"{self.scene}_level", data)
            self.submit.emit(GameConfig(self.scene, data, self.show_call.isChecked()))
        elif isinstance(data, list) and data:
            items = tuple(ITEMS[item_id] for item_id in data if item_id in ITEMS)
            if items:
                self._start_study(items, self.sets.itemText(index))

    def _start_study(self, items: tuple[CurriculumItem, ...], title: str) -> None:
        """Send a study set to the engine; first-unit reading turns the guides on."""
        if items[0].mode == "sight" and all(item.unit == 1 for item in items):
            self.guides.setChecked(True)
        self.submit.emit(StudyConfig(items, title))

    def open_study(self, items: tuple[CurriculumItem, ...], title: str) -> None:
        """Open a specific set chosen on the Home screen."""
        self._enter(items[0].mode)
        self.keyboard.reset_range()
        entries, _ = self._study_sets(self.scene)
        self._fill_sets([(title, [item.item_id for item in items]), *entries], 0)
        self._start_study(items, title)

    def open_song(self, config: SongConfig) -> None:
        """Open a specific piece chosen on the Home screen."""
        self.song_panel.show_config(config)
        self._song_configured(config)

    def _song_configured(self, config: SongConfig) -> None:
        """Load a song configuration into the engine and the falling-notes view."""
        self._enter("song")
        self.song_config = config
        self.roll.show_song(config.timeline, config.hands)
        self.submit.emit(config)

    def _show_call_changed(self, on: bool) -> None:
        """Remember the Melody Echo display choice and restart the game with it."""
        self._remember("show_call", on)
        if self.scene == "echo":
            level = self.sets.currentData()
            self.submit.emit(GameConfig("echo", level if isinstance(level, int) else 1, on))

    def toggle_play(self) -> None:
        """Play when stopped, pause when running."""
        self.submit.emit(Command(Action.PAUSE if self._running else Action.PLAY))

    @property
    def running(self) -> bool:
        """Report the latest published running state for navigation and bookmarking."""
        return self._running

    @staticmethod
    def _visible(widget: QWidget, visible: bool) -> None:
        """Show or hide a widget only when that is a change."""
        if widget.isHidden() == visible:
            widget.setVisible(visible)

    def show_snapshot(self, snapshot: RenderSnapshot) -> None:
        """Draw one snapshot. Widgets repaint only when what they show has changed."""
        scene = snapshot.scene
        if self._leaving is not None:
            if scene == self._leaving and self._stale_frames > 0:
                self._stale_frames -= 1
                return
            self._leaving = None
        song = scene == "song"
        if snapshot.running != self._running or not self.play_button.text():
            self._running = snapshot.running
            self.play_button.setText("Pause" if self._running else "Play")
            self.play_button.setIcon(icon("pause" if self._running else "play", "white"))
        button = self.mode_buttons.get(scene)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        title = snapshot.title or MODE_TITLES.get(scene, "")
        if self.title.text() != title:
            self.title.setText(title)
        if self.instruction.text() != snapshot.instruction:
            self.instruction.setText(snapshot.instruction)
        chips = snapshot.chips
        if snapshot.assisted:
            chips = (*chips, "assist on • not counted toward mastery")
        self.chips.show_chips(chips)

        view = self.song_panel.current_view() if song else ""
        show_roll = song and (view != "Staff" or snapshot.layout is None)
        show_staff = snapshot.layout is not None and not (song and view == "Falling notes")
        for widget, visible in (
            (self.sets, not song),
            (self.set_label, not song),
            (self.song_panel, song),
            (self.progress, snapshot.progress is not None),
            (self.card, snapshot.layout is None and not song),
            (self.staff, show_staff),
            (self.roll, show_roll),
            (self.graph, scene == "technique"),
            (self.beats, scene in ("rhythm", "technique", "song")),
            (self.keyboard, not show_roll),
            (self.tempo, scene in TEMPO_SCENES),
            (self.tempo_label, scene in TEMPO_SCENES),
            (self.names, scene in NAME_SCENES),
            (self.key_hints, scene in ("keys", "sight", "rush")),
            (self.guides, scene in ("sight", "rush", "song")),
            (self.fingering, scene in ("technique", "song")),
            (self.show_call, scene == "echo"),
            (self.hint_button, scene in HINT_SCENES),
            (self.next_button, scene in STUDY_MODES or scene == "rush"),
        ):
            self._visible(widget, visible)
        self.hint_button.setEnabled(snapshot.running)

        lead = self.settings.visual_offset_ms / 1000 * snapshot.beats_per_second
        self.staff.show_state(
            snapshot.layout,
            snapshot.marks,
            None if snapshot.playhead is None else snapshot.playhead + lead,
            snapshot.scrolling,
            self.settings.show_names or (snapshot.reveal and not song),
            self.guides.isChecked() and scene in ("sight", "rush", "song"),
            snapshot.fingering if self.fingering.isChecked() else "off",
        )
        if show_roll:
            self.roll.show_state(
                snapshot.beat + lead, snapshot.held, snapshot.expected, snapshot.allowed, True
            )
        self.card.show_prompt(
            snapshot.prompt_text, "", snapshot.game.lives if snapshot.game else None
        )
        self.graph.show_values(snapshot.graph, snapshot.velocity_graph)
        if snapshot.progress is not None:
            self.progress.setValue(round(snapshot.progress * 1000))
        self.beats.show_pulse(snapshot.pulse)
        if snapshot.error:
            self.status.show_status(snapshot.error, "error")
        else:
            fresh = snapshot.wall_time - snapshot.feedback_at < FEEDBACK_SECONDS
            self.status.show_status(snapshot.status, snapshot.feedback if fresh else "")
        self.keyboard.show_state(
            snapshot.held,
            snapshot.expected,
            snapshot.allowed,
            snapshot.lit,
            snapshot.reveal,
            self.settings.show_names,
        )
