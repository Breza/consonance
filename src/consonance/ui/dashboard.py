from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from consonance.core.curriculum import ITEMS, UNITS, ItemSchedule, recommended_unit
from consonance.core.db import AttemptLog
from consonance.core.practice_log import summarize_practice


class Dashboard(QWidget):
    open_item = Signal(str)

    def __init__(self, log: AttemptLog) -> None:
        super().__init__()
        self.log = log
        self.due_ids: list[str] = []
        self.free_ids: list[str] = []
        layout = QVBoxLayout(self)
        title = QLabel("A little practice. A little more music.")
        title.setStyleSheet("font-size: 24px; font-weight: 600; padding: 14px;")
        layout.addWidget(title)
        self.log_label = QLabel("")
        self.log_label.setWordWrap(True)
        self.log_label.setStyleSheet("font-size: 16px; padding: 14px; background: #deebe5;")
        layout.addWidget(self.log_label)
        row = QHBoxLayout()
        self.badge = QLabel("")
        self.badge.setStyleSheet("font-size: 20px; padding: 12px;")
        row.addWidget(self.badge, 1)
        refresh = QPushButton("Refresh practice log")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)
        layout.addWidget(
            QLabel("Two minutes or forty-five: choose any due item and stop whenever you like.")
        )
        self.due = QListWidget()
        self.due.setMaximumHeight(140)
        self.due.itemDoubleClicked.connect(lambda _: self.launch_due())
        layout.addWidget(self.due)
        start = QPushButton("Play selected review")
        start.clicked.connect(self.launch_due)
        layout.addWidget(start)
        layout.addWidget(QLabel("FREE PRACTICE • every unit, drill, and piece is open"))
        self.units = QComboBox()
        self.units.addItems([f"{u.number}. {u.title}" for u in UNITS])
        self.units.currentIndexChanged.connect(self.populate_free)
        layout.addWidget(self.units)
        self.description = QLabel("")
        layout.addWidget(self.description)
        self.free = QListWidget()
        self.free.itemDoubleClicked.connect(lambda _: self.launch_free())
        layout.addWidget(self.free, 1)
        open_button = QPushButton("Open selected drill or song")
        open_button.clicked.connect(self.launch_free)
        layout.addWidget(open_button)
        self.refresh()

    def refresh(self) -> None:
        now = datetime.now().astimezone()
        schedules = self.log.schedules()
        states = {sid: ItemSchedule(sid, *values) for sid, values in schedules.items()}
        recommendation = recommended_unit(states)
        for index, unit in enumerate(UNITS):
            self.units.setItemText(
                index,
                f"{unit.number}. {unit.title}"
                + ("  • Recommended" if unit.number == recommendation else ""),
            )
        self.due_ids = sorted(
            (
                sid
                for sid, state in states.items()
                if datetime.fromisoformat(state.due_at_utc) <= now and sid in ITEMS
            ),
            key=lambda sid: states[sid].due_at_utc,
        )
        self.due.clear()
        self.due.addItems([f"{ITEMS[sid].title}  • Box {states[sid].box}" for sid in self.due_ids])
        self.badge.setText(f"Daily Due Queue   {len(self.due_ids)} due")
        if self.due_ids:
            self.due.setCurrentRow(0)
        else:
            self.due.addItem("All caught up • explore a new drill in Free Practice below")
        summary = summarize_practice(self.log.sessions(), now)
        bars = "  ·  ".join(f"{day[5:]} {minutes:.0f}m" for day, minutes in summary.seven_days)
        self.log_label.setText(
            f"Today {summary.minutes_today:.1f} minutes   •   "
            f"{summary.streak}-day streak\n{bars}\n"
            f"Drills touched: {', '.join(summary.drills_today) or 'Your next note starts today'}"
        )
        self.populate_free(self.units.currentIndex())

    def populate_free(self, index: int) -> None:
        unit = UNITS[index]
        self.description.setText(unit.description)
        self.free_ids = [i.item_id for i in unit.items]
        self.free.clear()
        self.free.addItems([i.title for i in unit.items])
        if self.free_ids:
            self.free.setCurrentRow(0)

    def launch_due(self) -> None:
        row = self.due.currentRow()
        if 0 <= row < len(self.due_ids):
            self.open_item.emit(self.due_ids[row])

    def launch_free(self) -> None:
        row = self.free.currentRow()
        if 0 <= row < len(self.free_ids):
            self.open_item.emit(self.free_ids[row])
