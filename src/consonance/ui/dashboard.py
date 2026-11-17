"""Home: a useful next step, a piece to return to, and a forgiving view of progress."""

from datetime import datetime, timedelta

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from consonance.core.builtin_scores import BUILTIN_SCORES, score_by_id
from consonance.core.curriculum import (
    ITEMS,
    MODE_TITLES,
    UNITS,
    ItemSchedule,
    item_status,
    recommended_unit,
    unit_progress,
)
from consonance.core.db import AttemptLog
from consonance.core.drills.games import ECHO_LEVELS, RUSH_LEVELS
from consonance.core.home import available_steps, reading_insight
from consonance.core.notation_layout import layout_measures
from consonance.core.plan import Plan, PlanStep, build_plan
from consonance.core.practice_log import local_midnight_utc, summarize_practice
from consonance.ui import theme
from consonance.ui.home_widgets import LessonCalendar
from consonance.ui.staff import GrandStaff
from consonance.ui.widgets import WeekChart

STATUS_COLORS = {
    "new": theme.FAINT,
    "learning": theme.AMBER,
    "due": theme.ORANGE,
    "mastered": theme.GREEN,
}
STATUS_WORDS = {
    "new": "new",
    "learning": "building fluency",
    "due": "ready to review",
    "mastered": "fluent",
}
STEP_WORDS = {"review": "Keep fresh", "new": "Discover", "practice": "Build confidence"}
FOCUS = {
    "keys": "Find your way around the keys",
    "sight": "Read with a little more ease",
    "rhythm": "Find a steady pulse",
    "technique": "Build an even touch",
    "ear": "Bring the sound to your fingers",
    "song": "Return to the music",
}
CHAPTERS = (
    "Landmarks and pulse",
    "Five-finger positions",
    "Steps and skips",
    "Intervals and eighths",
    "Triads and touch",
    "Ledger notes and modes",
    "G and F major",
    "Hands together",
)


def _dot(color: str, filled: bool = True) -> QIcon:
    """Draw a small status dot without relying on icon fonts."""
    pixmap = QPixmap(36, 36)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(color))
    painter.setBrush(QColor(color) if filled else Qt.BrushStyle.NoBrush)
    painter.drawEllipse(9, 9, 18, 18)
    painter.end()
    pixmap.setDevicePixelRatio(3)
    return QIcon(pixmap)


def _label(text: str = "", role: str = "") -> QLabel:
    """Create a wrapping, plain-text label with an optional semantic style."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if role:
        label.setProperty("role", role)
    return label


def _local_time(instant: datetime) -> datetime:
    """Apply Windows local timezone rules at each instant, including historical DST."""
    return instant.astimezone()


def _card(title: str, role: str = "card") -> tuple[QFrame, QVBoxLayout]:
    """Create a surface with a consistent internal rhythm and optional heading."""
    frame = QFrame()
    frame.setProperty("role", role)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 18, 22, 20)
    layout.setSpacing(10)
    if title:
        layout.addWidget(_label(title.upper(), "heading"))
    return frame, layout


class Dashboard(QWidget):
    """A practice invitation first; the complete, unlocked library is one click away."""

    open_step = Signal(object)
    start_step = Signal(object)
    open_item = Signal(str)
    open_game = Signal(str, int)
    open_piece = Signal(str)

    def __init__(self, log: AttemptLog) -> None:
        """Build the desk, preserving the daily plan, free browser, and personal games."""
        super().__init__()
        self.log = log
        self.states: dict[str, ItemSchedule] = {}
        self.plan: Plan | None = None
        self.free_ids: list[str] = []
        self._piano = False
        self._sound = False
        self._suggestions: tuple[PlanStep, ...] = ()
        self._piece_id = ""
        self._piece_practiced = False
        self._wide: bool | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        outer.addWidget(self.scroll_area)
        body = QWidget()
        self.scroll_area.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 26)
        layout.setSpacing(18)
        title_row = QHBoxLayout()
        title_row.addWidget(_label("Your practice desk", "deskTitle"), 1)
        self.explore = QPushButton("Explore all practice")
        self.explore.setCheckable(True)
        self.explore.setProperty("role", "quiet")
        self.explore.toggled.connect(self._show_library)
        title_row.addWidget(self.explore)
        layout.addLayout(title_row)
        layout.addWidget(_label("A little music, at your pace.", "muted"))
        self.welcome, welcome_layout = _card("")
        welcome_layout.addWidget(
            _label(
                "New here? Start with a few familiar notes. Everything is open, and you can "
                "finish after any exercise.",
                "muted",
            )
        )
        layout.addWidget(self.welcome)
        self.main_grid = QGridLayout()
        self.main_grid.setSpacing(18)
        self.hero = self._build_hero()
        self.piece = self._build_piece()
        layout.addLayout(self.main_grid)
        self.plan_detail = QFrame()
        self.plan_detail.setProperty("role", "card")
        details = QVBoxLayout(self.plan_detail)
        details.setContentsMargins(20, 16, 20, 16)
        details.addWidget(_label("OTHER WAYS TO SPEND A FEW MINUTES", "heading"))
        self.plan_rows = QVBoxLayout()
        self.plan_rows.setSpacing(10)
        details.addLayout(self.plan_rows)
        self.plan_detail.hide()
        layout.addWidget(self.plan_detail)
        layout.addWidget(self._build_activity())
        self.insight_card, insight_layout = _card("Something to build on")
        self.insight_title = _label("", "title")
        self.insight_detail = _label("", "muted")
        insight_layout.addWidget(self.insight_title)
        insight_layout.addWidget(self.insight_detail)
        layout.addWidget(self.insight_card)
        layout.addWidget(self._build_journey())
        self.library = self._build_units()
        self.library.hide()
        layout.addWidget(self.library)
        layout.addWidget(self._build_games())
        layout.addStretch(1)
        self.refresh()
        self._reflow()
        self.day_timer = QTimer(self)
        self.day_timer.setInterval(60_000)
        self.day_timer.timeout.connect(self.refresh_for_date)
        self.day_timer.start()

    def _build_hero(self) -> QFrame:
        """Give one suggested activity clear visual priority and an honest reason."""
        card, layout = _card("Your next few minutes", "hero")
        self.hero_title = _label("", "heroTitle")
        self.hero_reason = _label("", "heroBody")
        self.hero_detail = _label("", "heroBody")
        layout.addWidget(self.hero_title)
        layout.addWidget(self.hero_reason)
        layout.addWidget(self.hero_detail)
        layout.addStretch(1)
        self.start_button = QPushButton("Begin practice")
        self.start_button.setProperty("role", "heroAction")
        self.start_button.setMinimumHeight(46)
        self.start_button.clicked.connect(self._start_first)
        layout.addWidget(self.start_button)
        self.plan_summary = _label("", "heroBody")
        layout.addWidget(self.plan_summary)
        self.suggestion_button = QPushButton("See other suggestions")
        self.suggestion_button.setProperty("role", "heroQuiet")
        self.suggestion_button.setCheckable(True)
        self.suggestion_button.toggled.connect(self._show_suggestions)
        layout.addWidget(self.suggestion_button)
        return card

    def _build_piece(self) -> QFrame:
        """Keep an actual musical destination beside the recommended exercise."""
        card, layout = _card("A piece to come back to")
        self.piece_title = _label("", "title")
        self.piece_detail = _label("", "muted")
        layout.addWidget(self.piece_title)
        layout.addWidget(self.piece_detail)
        self.score_preview = GrandStaff()
        self.score_preview.setMinimumHeight(98)
        self.score_preview.setMaximumHeight(116)
        self.score_preview.setAccessibleName("A short preview of the selected piece")
        layout.addWidget(self.score_preview)
        self.piece_hint = _label("", "muted")
        layout.addWidget(self.piece_hint)
        layout.addStretch(1)
        self.piece_button = QPushButton("Explore this piece")
        self.piece_button.clicked.connect(self._open_piece)
        layout.addWidget(self.piece_button)
        return card

    def _build_activity(self) -> QFrame:
        """Show a rolling lesson-day count, plus actual minutes as secondary context."""
        card, layout = _card("Your time with Consonance")
        row = QHBoxLayout()
        row.setSpacing(22)
        count = QVBoxLayout()
        self.lesson_days = _label("", "stat")
        count.addWidget(self.lesson_days)
        count.addWidget(_label("lesson days · past 90 days", "muted"))
        self.lesson_days.setToolTip(
            "A local calendar day counts after a finished exercise, song section, or game. "
            "Assisted work and answers with mistakes count. Multiple completions count once. "
            "Opening the app or abandoning an activity does not count."
        )
        self.today = _label("", "muted")
        self.touched = _label("", "muted")
        count.addWidget(self.today)
        count.addWidget(self.touched)
        count.addStretch(1)
        row.addLayout(count, 2)
        self.calendar = LessonCalendar()
        row.addWidget(self.calendar, 3)
        week = QVBoxLayout()
        week.addWidget(_label("MINUTES THIS WEEK", "heading"))
        self.week = WeekChart()
        self.week.setMinimumWidth(190)
        week.addWidget(self.week)
        row.addLayout(week, 2)
        layout.addLayout(row)
        return card

    def _build_journey(self) -> QFrame:
        """Present curriculum capabilities as open chapters with a suggested next focus."""
        card, layout = _card("Your developing skills")
        self.mastered = _label("", "muted")
        layout.addWidget(self.mastered)
        self.journey = QGridLayout()
        self.journey.setSpacing(8)
        self.unit_buttons: list[QPushButton] = []
        for index, _unit in enumerate(UNITS):
            button = QPushButton()
            button.setMinimumHeight(70)
            button.clicked.connect(lambda checked=False, i=index: self._open_unit(i))
            self.unit_buttons.append(button)
        layout.addLayout(self.journey)
        return card

    def _build_units(self) -> QFrame:
        """Keep the full item library available without overwhelming the first screen."""
        card, layout = _card("Free practice · everything is open")
        top = QHBoxLayout()
        self.units = QComboBox()
        self.units.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.units.addItems([f"{u.number}. {u.title}" for u in UNITS])
        self.units.currentIndexChanged.connect(self.populate_free)
        top.addWidget(self.units, 1)
        open_button = QPushButton("Open selected")
        open_button.clicked.connect(self.launch_free)
        top.addWidget(open_button)
        layout.addLayout(top)
        self.description = _label("", "muted")
        layout.addWidget(self.description)
        self.free = QListWidget()
        self.free.setMinimumHeight(210)
        self.free.setIconSize(QSize(12, 12))
        self.free.setUniformItemSizes(True)
        self.free.itemDoubleClicked.connect(lambda _: self.launch_free())
        layout.addWidget(self.free)
        return card

    def _build_games(self) -> QFrame:
        """Offer optional challenges and personal bests as a change of pace."""
        card, layout = _card("A change of pace")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.rush_button = QPushButton("Note Rush")
        self.rush_button.clicked.connect(lambda: self.open_game.emit("rush", -1))
        self.echo_button = QPushButton("Melody Echo")
        self.echo_button.clicked.connect(lambda: self.open_game.emit("echo", -1))
        self.rush_best = _label("", "muted")
        self.echo_best = _label("", "muted")
        row.addWidget(self.rush_button)
        row.addWidget(self.rush_best, 1)
        row.addWidget(self.echo_button)
        row.addWidget(self.echo_best, 1)
        layout.addLayout(row)
        return card

    def _show_library(self, shown: bool) -> None:
        """Expand the library and bring its controls into view when requested."""
        self.library.setVisible(shown)
        if shown:
            QTimer.singleShot(0, lambda: self.scroll_area.ensureWidgetVisible(self.library))

    def _show_suggestions(self, shown: bool) -> None:
        """Reveal the remaining plan steps without changing the current recommendation."""
        self.plan_detail.setVisible(shown)

    def _open_unit(self, index: int) -> None:
        """Open any curriculum chapter without applying a mastery lock."""
        self.units.setCurrentIndex(index)
        self.explore.setChecked(True)
        self._show_library(True)

    def _clear_plan(self) -> None:
        """Discard old suggestion rows before rebuilding from fresh history."""
        while self.plan_rows.count():
            entry = self.plan_rows.takeAt(0)
            widget = entry.widget() if entry else None
            if widget:
                widget.deleteLater()

    def _show_plan(self, plan: Plan) -> None:
        """Offer a bounded first activity and keep the rest of the daily plan inspectable."""
        self._clear_plan()
        suggestions = available_steps(plan, self._piano, self._sound)
        if not suggestions:
            items = tuple(i for i in UNITS[plan.unit - 1].items if i.mode == "sight")[:3]
            if not items:
                items = tuple(i for i in ITEMS.values() if i.mode == "keys")[:3]
            suggestions = (
                PlanStep(
                    "practice",
                    items[0].mode,
                    "A few familiar notes",
                    "A short reading refresher",
                    tuple(i.item_id for i in items),
                ),
            )
        self._suggestions = suggestions
        first = suggestions[0]
        self.hero_title.setText(FOCUS.get(first.mode, "Pick up a little music"))
        if not self._piano:
            self.hero_reason.setText(
                "Quiet practice for a small break. Use the on-screen keys or A–L / W–P; "
                "no sound is needed."
            )
        elif first.kind == "review":
            self.hero_reason.setText(
                "A short refresher for things you've already met. Keep them familiar, "
                "then return to your music."
            )
        else:
            self.hero_reason.setText(
                f"A small next step in {UNITS[plan.unit - 1].title}. Go slowly; the rest can wait."
            )
        quantity = len(first.item_ids)
        self.hero_detail.setText(
            f"{MODE_TITLES[first.mode]} · {quantity} "
            f"{'exercise' if quantity == 1 else 'exercises'}\n"
            "One small activity. Finish whenever you like."
        )
        self.start_button.setText("Begin review" if first.kind == "review" else "Begin practice")
        self.plan_summary.setText(
            (f"{plan.due_count} due · " if plan.due_count else "Nothing due · ")
            + "all practice stays open"
        )
        for step in plan.steps:
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            text = _label(f"{STEP_WORDS.get(step.kind, 'Practise')} · {step.title}\n{step.detail}")
            line.addWidget(text, 1)
            button = QPushButton("Open")
            button.clicked.connect(lambda checked=False, s=step: self.open_step.emit(s))
            line.addWidget(button)
            self.plan_rows.addWidget(row)

    def first_step(self) -> PlanStep | None:
        """Return the context-appropriate recommendation shown by the primary button."""
        return self._suggestions[0] if self._suggestions else None

    def _start_first(self) -> None:
        """Begin only the chosen activity; subsequent ideas are always optional."""
        step = self.first_step()
        if step:
            self.start_step.emit(step)

    def _open_piece(self) -> None:
        """Open the bookmarked section or the suggested first piece."""
        if self._piece_id:
            self.open_piece.emit(self._piece_id)

    def set_connection(self, piano: bool, sound: bool) -> None:
        """Adjust suggestions when physical input or MIDI prompt playback changes."""
        if (piano, sound) == (self._piano, self._sound):
            return
        self._piano, self._sound = piano, sound
        if self.plan:
            self._show_plan(self.plan)
        self._describe_piece()

    def _refresh_piece(self, unit_number: int) -> None:
        """Prefer the last played piece; otherwise connect the current chapter to a song."""
        saved = self.log.preference_value("home_song", {})
        self._piece_practiced = isinstance(saved, dict) and bool(saved.get("song_id"))
        if self._piece_practiced:
            self._piece_id = str(saved["song_id"])
            self.piece_title.setText(str(saved.get("title", "Your piece")))
        else:
            item = next(
                (
                    i
                    for unit in UNITS[unit_number - 1 :]
                    for i in unit.items
                    if i.mode == "song" and i.hand == "rh"
                ),
                None,
            )
            score = score_by_id(item.song_id) if item else BUILTIN_SCORES[0]
            assert score is not None
            self._piece_id = score.song_id
            self.piece_title.setText(score.title)
        score = score_by_id(self._piece_id)
        self.score_preview.setVisible(score is not None)
        if score:
            try:
                start = max(1, min(len(score.measures), int(saved.get("start_measure", 1))))
            except (AttributeError, TypeError, ValueError):
                start = 1
            measure = score.measures[start - 1]
            self.score_preview.layout_data = layout_measures(
                ((measure.right, measure.left),), score.key, score.time
            )
            self.score_preview.update()
        self._describe_piece()

    def _describe_piece(self) -> None:
        """Explain the saved practice settings and whether the instrument is available."""
        saved = self.log.preference_value("home_song", {})
        if self._piece_practiced and isinstance(saved, dict):
            hands = {"rh": "Right hand", "lh": "Left hand", "both": "Hands together"}
            start, end = saved.get("start_measure", 1), saved.get("end_measure", 0)
            section = f"Measures {start}–{end}" if end else "Whole piece"
            self.piece_detail.setText(
                f"{section} · {hands.get(str(saved.get('hand')), 'Right hand')}\n"
                "Your last selected section and playing settings"
            )
        else:
            self.piece_detail.setText("A musical destination for the skills you're building.")
        self.piece_hint.setText(
            "Your section, hands and tempo are ready to return to."
            if self._piece_practiced
            else "Start with one hand. Take a small phrase at your own pace."
        )
        self.piece_button.setText(
            "Continue this piece" if self._piece_practiced else "Explore this piece"
        )
        if not self._piano:
            self.piece_hint.setText(
                "Keep this piece in mind for your next piano session. "
                "You can still explore its score now."
            )

    def refresh(self) -> None:
        """Refresh the recommendation, real completions, saved piece, and skill evidence."""
        now = datetime.now().astimezone()
        self._shown_date = now.date()
        self.states = self.log.schedule_states()
        since = local_midnight_utc(now)
        self.plan = build_plan(
            self.states, now, self.log.first_seen_since(since), self.log.practiced_since(since)
        )
        self._show_plan(self.plan)
        # Query a spare day so a historical DST offset cannot exclude the first hour.
        first = now - timedelta(days=90)
        completed = self.log.completed_at(local_midnight_utc(first))
        summary = summarize_practice(self.log.sessions(), now, completed, localize=_local_time)
        self.lesson_days.setText(str(summary.lesson_days_90))
        self.calendar.show_days(now.date(), summary.lesson_dates_90)
        self.today.setText(f"{summary.minutes_today:.1f} minutes today")
        self.touched.setText(" · ".join(MODE_TITLES.get(m, m) for m in summary.drills_today))
        self.week.show_days(summary.seven_days)
        progress = unit_progress(self.states)
        done = sum(mastered for mastered, _ in progress)
        self.mastered.setText(
            f"{done} of {len(ITEMS)} practice items fluent · every chapter is yours to explore"
        )
        self.welcome.setVisible(not self.states and not completed)
        recommended = recommended_unit(self.states)
        for index, unit in enumerate(UNITS):
            mastered, total = progress[index]
            suffix = " · Suggested next" if unit.number == recommended else ""
            self.units.setItemText(
                index, f"{unit.number}. {unit.title} · {mastered}/{total} fluent{suffix}"
            )
            button = self.unit_buttons[index]
            button.setText(
                f"{unit.number:02d}  {CHAPTERS[index]}\n{mastered}/{total} fluent{suffix}"
            )
            button.setToolTip(unit.description + " Click to explore; all chapters are open.")
        if not self.free_ids:
            self.units.setCurrentIndex(recommended - 1)
        self.populate_free(self.units.currentIndex())
        self._refresh_piece(recommended)
        insight = reading_insight(self.log.recent_attempts())
        self.insight_title.setText(
            insight.title if insight else "A few notes today. More possibilities tomorrow."
        )
        self.insight_detail.setText(
            insight.detail
            if insight
            else "Your progress is built from finished exercises, including the ones that take "
            "a few tries. As comparable reading answers accumulate, this space will show "
            "what is becoming more familiar."
        )
        bests = self.log.preferences_with_prefix("best:")
        for label, game, levels, unit_word in (
            (self.rush_best, "rush", RUSH_LEVELS, "notes in 60 seconds"),
            (self.echo_best, "echo", ECHO_LEVELS, "notes echoed"),
        ):
            scores = [
                (bests[f"best:{game}:{level}"], levels[level][0].split(" • ")[0])
                for level in range(len(levels))
                if isinstance(bests.get(f"best:{game}:{level}"), int | float)
            ]
            if scores:
                value, name = max(scores)
                label.setText(f"Personal best: {value:.0f} {unit_word} ({name})")
            else:
                label.setText(
                    "A short reading challenge"
                    if game == "rush"
                    else "Listen and echo a growing melody"
                )

    def refresh_for_date(self) -> None:
        """Roll the ninety-day calendar over when the app stays open past local midnight."""
        if datetime.now().astimezone().date() != self._shown_date:
            self.refresh()

    def populate_free(self, index: int) -> None:
        """List one chapter with understandable status labels and preserved selection."""
        if not 0 <= index < len(UNITS):
            return
        now = datetime.now().astimezone()
        unit = UNITS[index]
        self.description.setText(unit.description)
        selected = self.free.currentRow()
        same = self.free_ids == [i.item_id for i in unit.items]
        self.free_ids = [i.item_id for i in unit.items]
        self.free.clear()
        for item in unit.items:
            status = item_status(item.item_id, self.states, now)
            self.free.addItem(
                QListWidgetItem(
                    _dot(STATUS_COLORS[status], status != "new"),
                    f"{item.title}      {MODE_TITLES[item.mode]} · {STATUS_WORDS[status]}",
                )
            )
        if self.free_ids:
            self.free.setCurrentRow(selected if same and selected >= 0 else 0)

    def launch_free(self) -> None:
        """Open the selected exercise without applying curriculum restrictions."""
        row = self.free.currentRow()
        if 0 <= row < len(self.free_ids):
            self.open_item.emit(self.free_ids[row])

    def _reflow(self) -> None:
        """Stack the main cards on smaller laptop windows; keep chapters easy to scan."""
        wide = self.width() >= 1000
        if wide == self._wide:
            return
        self._wide = wide
        self.main_grid.addWidget(self.hero, 0, 0)
        self.main_grid.addWidget(self.piece, 0 if wide else 1, 1 if wide else 0)
        self.main_grid.setColumnStretch(0, 3 if wide else 1)
        self.main_grid.setColumnStretch(1, 2 if wide else 0)
        columns = 4 if wide else 2
        for i, button in enumerate(self.unit_buttons):
            self.journey.addWidget(button, i // columns, i % columns)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Adapt the home layout without changing the learner's selections."""
        super().resizeEvent(event)
        self._reflow()
