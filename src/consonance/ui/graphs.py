"""The Technique Lab's evenness chart: timing gaps beside key velocities."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from consonance.ui import theme


class EvennessGraph(QWidget):
    """Bars for each gap between notes and each note's velocity, with their averages.

    Perfect evenness is every bar the same height, so the dashed average line makes the
    uneven notes easy to spot.
    """

    def __init__(self) -> None:
        """Create an empty chart."""
        super().__init__()
        self.values: tuple[float, ...] = ()
        self.velocities: tuple[float, ...] = ()
        self.setMinimumHeight(132)

    def show_values(self, values: tuple[float, ...], velocities: tuple[float, ...]) -> None:
        """Adopt new measurements and repaint only if they changed."""
        if (values, velocities) != (self.values, self.velocities):
            self.values, self.velocities = values, velocities
            self.update()

    def _bars(
        self,
        painter: QPainter,
        values: tuple[float, ...],
        area: QRectF,
        ceiling: float,
        color: str,
        title: str,
    ) -> None:
        """Draw one labelled row of bars with a dashed line at their average."""
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(QPointF(area.left(), area.top() - 6), title)
        if not values:
            return
        slot = area.width() / len(values)
        for index, value in enumerate(values):
            height = max(2.0, area.height() * min(1.0, value / max(1.0, ceiling)))
            left = area.left() + index * slot
            bar = QPainterPath()
            bar.addRoundedRect(
                QRectF(left + slot * 0.2, area.bottom() - height, slot * 0.6, height), 2, 2
            )
            painter.fillPath(bar, QColor(color))
            painter.setPen(QColor(theme.INK))
            label = QRectF(left, area.bottom() + 1, slot, 14)
            painter.drawText(label, Qt.AlignmentFlag.AlignCenter, f"{value:.0f}")
        average = sum(values) / len(values)
        y = area.bottom() - area.height() * min(1.0, average / max(1.0, ceiling))
        painter.setPen(QPen(QColor(theme.INK), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw both rows, or an invitation to play when there is nothing to show."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
        painter.fillPath(frame, QColor(theme.CARD))
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        painter.setFont(font)
        if not self.values and not self.velocities:
            painter.setPen(QColor(theme.MUTED))
            hint = "Play the pattern to see how even your timing and touch were"
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, hint)
            painter.end()
            return
        half = (self.width() - 60) / 2
        height = self.height() - 54.0
        ceiling = max(self.values, default=1.0) * 1.15
        timing = QRectF(20, 32, half, height)
        touch = QRectF(40 + half, 32, half, height)
        self._bars(
            painter,
            self.values,
            timing,
            ceiling,
            theme.TEAL,
            "Gap between notes (ms) • even is flat",
        )
        self._bars(
            painter, self.velocities, touch, 127.0, theme.ORANGE, "Touch of each note (velocity)"
        )
        painter.end()
