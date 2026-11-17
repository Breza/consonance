"""Small display widgets shared by the practice and home screens."""

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from consonance.core.drills.base import Pulse
from consonance.ui import theme

TONES = {
    "": (theme.CARD, theme.RULE, theme.INK),
    "good": (theme.GREEN_SOFT, theme.GREEN, theme.INK),
    "ok": (theme.AMBER_SOFT, theme.AMBER, theme.INK),
    "bad": (theme.RED_SOFT, theme.RED, theme.INK),
    "error": (theme.RED_SOFT, theme.RED, theme.RED),
}


class BeatIndicator(QWidget):
    """A visual metronome: one dot per beat, with numbers during a count-in.

    The piano makes every sound, so this is how the beat is seen when no MIDI output is
    connected, and how a count-in is followed without looking away from the screen.
    """

    def __init__(self) -> None:
        """Create an indicator that shows nothing until a pulse arrives."""
        super().__init__()
        self.pulse: Pulse | None = None
        self.idle_beats = 4
        self.setFixedHeight(44)
        self.setMinimumWidth(250)

    def show_pulse(self, pulse: Pulse | None) -> None:
        """Adopt the current beat position and repaint if it moved."""
        if pulse != self.pulse:
            self.pulse = pulse
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the beats of the bar, swelling the one that is sounding."""
        pulse = self.pulse
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if pulse is None:
            # Resting: faint dots show where the beat will appear.
            painter.setPen(QPen(QColor(theme.RULE), 2))
            for beat in range(self.idle_beats):
                painter.drawEllipse(QPointF(20 + beat * 36, self.height() / 2), 9, 9)
            painter.end()
            return
        self.idle_beats = pulse.beats
        current = int(pulse.position) % pulse.beats
        phase = pulse.position - int(pulse.position)
        accent = QColor(theme.ORANGE if pulse.count_in else theme.TEAL)
        font = QFont("Segoe UI")
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        for beat in range(pulse.beats):
            center = QPointF(20 + beat * 36, self.height() / 2)
            if beat == current:
                radius = 10 + 5 * (1 - phase) ** 2
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
            else:
                radius = 9.0
                painter.setPen(QPen(QColor(theme.MINT_BORDER), 2))
                painter.setBrush(QColor(theme.MINT) if beat < current else Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius, radius)
            if pulse.count_in and beat <= current:
                painter.setPen(QColor("white") if beat == current else QColor(theme.MUTED))
                box = QRectF(center.x() - 12, center.y() - 12, 24, 24)
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, str(beat + 1))
        if pulse.count_in:
            plain = QFont("Segoe UI")
            plain.setPixelSize(13)
            painter.setFont(plain)
            painter.setPen(QColor(theme.MUTED))
            left = 20 + pulse.beats * 36
            painter.drawText(
                QRectF(left, 0, 90, self.height()), Qt.AlignmentFlag.AlignVCenter, "count-in"
            )
        painter.end()


class PromptCard(QWidget):
    """A large, centred text prompt for drills that are not read from a staff."""

    def __init__(self) -> None:
        """Create an empty card."""
        super().__init__()
        self.text = ""
        self.sub = ""
        self.lives: int | None = None
        self.setMinimumHeight(150)

    def show_prompt(self, text: str, sub: str = "", lives: int | None = None) -> None:
        """Adopt new content and repaint only if something changed."""
        if (text, sub, lives) != (self.text, self.sub, self.lives):
            self.text, self.sub, self.lives = text, sub, lives
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the prompt as large as the card allows."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(frame, QColor(theme.SURFACE))
        painter.setPen(QPen(QColor(theme.RULE), 1))
        painter.drawPath(frame)
        size = min(60.0, self.height() * 0.3)
        font = QFont("Segoe UI")
        font.setWeight(QFont.Weight.DemiBold)
        while size > 16:
            font.setPixelSize(round(size))
            if QFontMetricsF(font).horizontalAdvance(self.text) <= self.width() - 60:
                break
            size -= 3
        painter.setFont(font)
        painter.setPen(QColor(theme.INK))
        middle = self.height() / 2 - (14 if self.sub else 0)
        painter.drawText(
            QRectF(0, middle - size, self.width(), size * 2),
            Qt.AlignmentFlag.AlignCenter,
            self.text,
        )
        if self.sub:
            small = QFont("Segoe UI")
            small.setPixelSize(16)
            painter.setFont(small)
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(
                QRectF(20, middle + size * 0.75, self.width() - 40, 28),
                Qt.AlignmentFlag.AlignCenter,
                self.sub,
            )
        if self.lives is not None:
            painter.setPen(QPen(QColor(theme.RED), 2))
            for i in range(3):
                painter.setBrush(QColor(theme.RED) if i < self.lives else Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(self.width() - 30 - i * 24, 26), 7, 7)
        painter.end()


class ChipRow(QWidget):
    """A row of small pills for at-a-glance numbers such as accuracy and streak."""

    def __init__(self) -> None:
        """Create an empty row."""
        super().__init__()
        self._texts: tuple[str, ...] = ()
        self._labels: list[QLabel] = []
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)
        self._row.addStretch(1)

    def show_chips(self, texts: tuple[str, ...]) -> None:
        """Show these chips, reusing labels and touching nothing if they are unchanged."""
        if texts == self._texts:
            return
        self._texts = texts
        while len(self._labels) < len(texts):
            label = QLabel()
            label.setProperty("role", "chip")
            self._labels.append(label)
            self._row.addWidget(label)
        for index, label in enumerate(self._labels):
            label.setVisible(index < len(texts))
            if index < len(texts):
                label.setText(texts[index])


class StatusBanner(QLabel):
    """The one-line result of the last thing that happened, tinted by how it went."""

    def __init__(self) -> None:
        """Create a neutral, empty banner."""
        super().__init__()
        self._tone = "unset"
        self.setWordWrap(True)
        self.setMinimumHeight(44)
        self.show_status("", "")

    def show_status(self, text: str, tone: str) -> None:
        """Show text; restyle only when the tone changes, which keeps repaints cheap."""
        if tone != self._tone:
            self._tone = tone
            background, border, ink = TONES.get(tone, TONES[""])
            self.setStyleSheet(
                f"font-size: 17px; padding: 9px 14px; border-radius: 9px; color: {ink};"
                f" background: {background}; border: 1px solid {border};"
            )
        if text != self.text():
            self.setText(text)


class WeekChart(QWidget):
    """Seven small bars: minutes practised on each of the last seven days."""

    def __init__(self) -> None:
        """Create an empty chart."""
        super().__init__()
        self.days: tuple[tuple[str, float], ...] = ()
        self.setMinimumSize(250, 92)

    def show_days(self, days: tuple[tuple[str, float], ...]) -> None:
        """Adopt (ISO date, minutes) pairs, oldest first."""
        if days != self.days:
            self.days = days
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw one bar per day, with today's bar emphasised."""
        if not self.days:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        painter.setFont(font)
        top = max(10.0, max(minutes for _, minutes in self.days))
        slot = self.width() / len(self.days)
        floor = self.height() - 20
        for index, (day, minutes) in enumerate(self.days):
            x = index * slot + slot * 0.2
            height = max(2.0, (floor - 18) * minutes / top)
            today = index == len(self.days) - 1
            bar = QPainterPath()
            bar.addRoundedRect(QRectF(x, floor - height, slot * 0.6, height), 3, 3)
            painter.fillPath(bar, QColor(theme.TEAL if today else theme.MINT_BORDER))
            painter.setPen(QColor(theme.INK if today else theme.MUTED))
            name = date.fromisoformat(day).strftime("%a")[:2]
            painter.drawText(
                QRectF(index * slot, floor + 3, slot, 16), Qt.AlignmentFlag.AlignCenter, name
            )
            if minutes >= 0.5:
                painter.drawText(
                    QRectF(index * slot, floor - height - 16, slot, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    f"{minutes:.0f}",
                )
        painter.end()
