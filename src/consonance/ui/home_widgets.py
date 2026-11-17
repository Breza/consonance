"""Quiet visual context for Home: completed lesson days, without streaks or targets."""

from datetime import date, timedelta

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from consonance.ui import theme


class LessonCalendar(QWidget):
    """Show exactly ninety dates; a filled square means a completed learning activity."""

    def __init__(self) -> None:
        """Create an accessible calendar with neutral unfilled days."""
        super().__init__()
        self.days: tuple[tuple[date, bool], ...] = ()
        self._cells: list[tuple[QRectF, date, bool]] = []
        self.setMinimumSize(220, 140)
        self.setMouseTracking(True)
        self.setAccessibleName("Lesson days in the past ninety days")

    def show_days(self, today: date, completed: tuple[str, ...]) -> None:
        """Adopt local completion dates, ordered through today inclusive."""
        done = set(completed)
        first = today - timedelta(days=89)
        self.days = tuple(
            (first + timedelta(days=i), (first + timedelta(days=i)).isoformat() in done)
            for i in range(90)
        )
        count = sum(active for _, active in self.days)
        self.setAccessibleDescription(
            f"{count} days with a completed lesson out of 90 calendar days."
        )
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw Monday-aligned weeks and a small date range label."""
        if not self.days:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        offset = self.days[0][0].weekday()
        columns = (offset + 89) // 7 + 1
        cell = min(17.0, (self.width() - 8) / columns - 4, (self.height() - 30) / 7 - 4)
        self._cells = []
        for i, (day, active) in enumerate(self.days):
            x = 4 + ((i + offset) // 7) * (cell + 4)
            y = 4 + ((i + offset) % 7) * (cell + 4)
            rect = QRectF(x, y, cell, cell)
            painter.setPen(QColor(theme.TEAL if active else theme.RULE))
            painter.setBrush(QColor(theme.TEAL if active else theme.PAPER))
            painter.drawRoundedRect(rect, 3, 3)
            self._cells.append((rect, day, active))
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(
            4,
            self.height() - 3,
            f"{self.days[0][0]:%d %b} — {self.days[-1][0]:%d %b}  ·  each square is one day",
        )
        painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Explain a date without attaching a negative meaning to an unfilled square."""
        for rect, day, active in self._cells:
            if rect.contains(event.position()):
                self.setToolTip(
                    f"{day:%A, %d %B}: "
                    + ("completed a lesson" if active else "no lesson recorded")
                )
                return
        self.setToolTip("")
