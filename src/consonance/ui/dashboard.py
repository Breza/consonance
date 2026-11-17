"""The Home screen: today's plan, the practice log, every unit, and the games."""

from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

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
from consonance.core.plan import NEW_PER_DAY, Plan, PlanStep, build_plan
from consonance.core.practice_log import local_midnight_utc, summarize_practice
from consonance.ui import theme
from consonance.ui.widgets import WeekChart

STATUS_COLORS = {
    "new": theme.FAINT,
    "learning": theme.AMBER,
    "due": theme.ORANGE,
    "mastered": theme.GREEN,
}
STATUS_WORDS = {"new": "new", "learning": "learning", "due": "due now", "mastered": "mastered"}
STEP_WORDS = {"review": "Review", "new": "New", "practice": "Practise"}


def _dot(color: str, filled: bool = True) -> QIcon:
    """Draw a small status dot."""
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


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Create a titled card and return it with the layout to fill."""
    frame = QFrame()
    frame.setProperty("role", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(8)
    if title:
        heading = QLabel(title.upper())
        heading.setProperty("role", "heading")
        layout.addWidget(heading)
    return frame, layout


class Dashboard(QWidget):
    """Answer "what should I do now?" first, then offer everything else."""

    open_step = Signal(object)
    open_item = Signal(str)
    open_game = Signal(str, int)

    def __init__(self, log: AttemptLog) -> None:
        """Build the screen and fill it from the practice log."""
        super().__init__()
        self.log = log
        self.states: dict[str, ItemSchedule] = {}
        self.plan: Plan | None = None
        self.free_ids: list[str] = []
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
        title = QLabel("A little practice. A little more music.")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)
        layout.addLayout(self._build_log())
        self.welcome, welcome_layout = _card("Getting started")
        steps = QLabel(
            "1.  Connect your piano by USB and switch it on. Consonance finds it by itself; "
            "the indicator at the top right turns green.\n"
            "2.  No piano to hand? Click the on-screen keys, or use the computer keyboard: "
            "A S D F G H J K L are the white keys from C, and W E T Y U are the black keys.\n"
            "3.  Press Start below. The piano makes every sound, and two minutes is a real "
            "practice."
        )
        steps.setWordWrap(True)
        welcome_layout.addWidget(steps)
        layout.addWidget(self.welcome)
        plan_card, self.plan_layout = _card("")
        head = QHBoxLayout()
        heading = QLabel("TODAY'S PLAN")
        heading.setProperty("role", "heading")
        head.addWidget(heading)
        self.plan_summary = QLabel("")
        self.plan_summary.setProperty("role", "muted")
        head.addWidget(self.plan_summary, 1)
        self.plan_layout.addLayout(head)
        self.plan_rows = QVBoxLayout()
        self.plan_rows.setSpacing(6)
        self.plan_layout.addLayout(self.plan_rows)
        layout.addWidget(plan_card)
        layout.addWidget(self._build_units(), 1)
        layout.addWidget(self._build_games())
        self.refresh()

    def _build_log(self) -> QHBoxLayout:
        """Create the three practice-log cards: today, this week, and progress."""
        row = QHBoxLayout()
        row.setSpacing(12)
        today, today_layout = _card("Today")
        self.today = QLabel("")
        self.today.setStyleSheet("font-size: 26px; font-weight: 600;")
        today_layout.addWidget(self.today)
        self.touched = QLabel("")
        self.touched.setProperty("role", "muted")
        self.touched.setWordWrap(True)
        today_layout.addWidget(self.touched)
        today_layout.addStretch(1)
        row.addWidget(today, 2)
        week, week_layout = _card("Minutes, last seven days")
        self.week = WeekChart()
        week_layout.addWidget(self.week)
        row.addWidget(week, 3)
        progress, progress_layout = _card("Progress")
        self.streak = QLabel("")
        self.streak.setStyleSheet("font-size: 26px; font-weight: 600;")
        progress_layout.addWidget(self.streak)
        self.mastered = QLabel("")
        self.mastered.setProperty("role", "muted")
        self.mastered.setWordWrap(True)
        progress_layout.addWidget(self.mastered)
        progress_layout.addStretch(1)
        row.addWidget(progress, 2)
        return row

    def _build_units(self) -> QFrame:
        """Create the free-practice browser: every unit and every item, always open."""
        card, layout = _card("Free practice • every unit, drill and piece is open")
        top = QHBoxLayout()
        self.units = QComboBox()
        self.units.addItems([f"{u.number}. {u.title}" for u in UNITS])
        self.units.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.units.currentIndexChanged.connect(self.populate_free)
        top.addWidget(self.units, 1)
        open_button = QPushButton("Open selected")
        open_button.clicked.connect(self.launch_free)
        top.addWidget(open_button)
        layout.addLayout(top)
        self.description = QLabel("")
        self.description.setProperty("role", "muted")
        layout.addWidget(self.description)
        self.free = QListWidget()
        self.free.setMinimumHeight(190)
        self.free.setIconSize(QSize(12, 12))
        self.free.setUniformItemSizes(True)
        self.free.itemDoubleClicked.connect(lambda _: self.launch_free())
        layout.addWidget(self.free, 1)
        return card

    def _build_games(self) -> QFrame:
        """Create the games card with each game's personal best."""
        card, layout = _card("Games")
        row = QHBoxLayout()
        self.rush_button = QPushButton("Note Rush")
        self.rush_button.clicked.connect(lambda: self.open_game.emit("rush", -1))
        self.echo_button = QPushButton("Melody Echo")
        self.echo_button.clicked.connect(lambda: self.open_game.emit("echo", -1))
        self.rush_best = QLabel("")
        self.rush_best.setProperty("role", "muted")
        self.echo_best = QLabel("")
        self.echo_best.setProperty("role", "muted")
        row.addWidget(self.rush_button)
        row.addWidget(self.rush_best, 1)
        row.addWidget(self.echo_button)
        row.addWidget(self.echo_best, 1)
        layout.addLayout(row)
        return card

    def _clear_plan(self) -> None:
        """Remove the previous plan's rows."""
        while self.plan_rows.count():
            entry = self.plan_rows.takeAt(0)
            widget = entry.widget() if entry is not None else None
            if widget is not None:
                widget.deleteLater()

    def _show_plan(self, plan: Plan) -> None:
        """List the suggested steps, each with a button that starts it."""
        self._clear_plan()
        parts = [f"{plan.due_count} due" if plan.due_count else "nothing due"]
        parts.append(
            f"up to {plan.new_left} new today"
            if plan.new_left
            else f"today's {NEW_PER_DAY} new things are met"
        )
        self.plan_summary.setText(" • ".join(parts))
        if not plan.steps:
            done = QLabel("All caught up. Explore any unit below, or play a game.")
            done.setProperty("role", "muted")
            self.plan_rows.addWidget(done)
            return
        for number, step in enumerate(plan.steps):
            row = QWidget()
            row.setObjectName("planRow")
            row.setStyleSheet("#planRow { background: transparent; }")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            badge = QLabel(STEP_WORDS.get(step.kind, "Practise"))
            badge.setProperty("role", "chip")
            badge.setFixedWidth(74)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            line.addWidget(badge)
            detail = f"<span style='color:{theme.MUTED}'>{step.detail}</span>"
            text = QLabel(f"<b>{step.title}</b>&nbsp;&nbsp;{detail}")
            text.setTextFormat(Qt.TextFormat.RichText)
            line.addWidget(text, 1)
            start = QPushButton("Start")
            if number == 0:
                start.setProperty("role", "primary")
            start.setMinimumWidth(96)
            start.clicked.connect(lambda checked=False, s=step: self.open_step.emit(s))
            line.addWidget(start)
            self.plan_rows.addWidget(row)

    def refresh(self) -> None:
        """Re-read the practice log and redraw every part of the screen."""
        now = datetime.now().astimezone()
        self.states = self.log.schedule_states()
        since = local_midnight_utc(now)
        practiced = self.log.practiced_since(since)
        self.plan = build_plan(self.states, now, self.log.first_seen_since(since), practiced)
        self._show_plan(self.plan)
        sessions = self.log.sessions()
        summary = summarize_practice(sessions, now)
        minutes = summary.minutes_today
        self.today.setText(f"{minutes:.0f} min" if minutes >= 1 else "Not yet today")
        drills = ", ".join(MODE_TITLES.get(mode, mode) for mode in summary.drills_today)
        self.touched.setText(drills or "Your next note starts today.")
        self.week.show_days(summary.seven_days)
        day = "day" if summary.streak == 1 else "days"
        self.streak.setText(f"{summary.streak} {day} in a row" if summary.streak else "Day one")
        progress = unit_progress(self.states)
        done = sum(mastered for mastered, _ in progress)
        self.mastered.setText(
            f"{done} of {len(ITEMS)} items mastered • {len(self.states)} met so far"
        )
        self.welcome.setVisible(not self.states and not any(s[1] > 0 for s in sessions))
        recommended = recommended_unit(self.states)
        for index, unit in enumerate(UNITS):
            mastered, total = progress[index]
            suffix = "   •   Recommended" if unit.number == recommended else ""
            self.units.setItemText(
                index, f"{unit.number}. {unit.title}   •   {mastered}/{total} mastered{suffix}"
            )
        if not self.free_ids:
            self.units.setCurrentIndex(recommended - 1)
        self.populate_free(self.units.currentIndex())
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
                label.setText(f"Best: {value:.0f} {unit_word} ({name})")
            else:
                label.setText("No score yet")

    def populate_free(self, index: int) -> None:
        """List a unit's items with a status dot and what that status means."""
        if not 0 <= index < len(UNITS):
            return
        now = datetime.now().astimezone()
        unit = UNITS[index]
        self.description.setText(unit.description)
        selected = self.free.currentRow()
        same_unit = self.free_ids == [i.item_id for i in unit.items]
        self.free_ids = [i.item_id for i in unit.items]
        self.free.clear()
        for item in unit.items:
            status = item_status(item.item_id, self.states, now)
            state = self.states.get(item.item_id)
            words = STATUS_WORDS[status]
            if state is not None and status != "mastered":
                words += f" • box {state.box}"
            entry = QListWidgetItem(
                _dot(STATUS_COLORS[status], status != "new"),
                f"{item.title}      {MODE_TITLES[item.mode]} • {words}",
            )
            self.free.addItem(entry)
        if self.free_ids:
            self.free.setCurrentRow(selected if same_unit and selected >= 0 else 0)

    def launch_free(self) -> None:
        """Open the item selected in the unit browser."""
        row = self.free.currentRow()
        if 0 <= row < len(self.free_ids):
            self.open_item.emit(self.free_ids[row])

    def first_step(self) -> PlanStep | None:
        """Return the first suggested step of today's plan, if there is one."""
        return self.plan.steps[0] if self.plan and self.plan.steps else None
