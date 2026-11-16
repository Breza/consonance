from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget


class EvennessGraph(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.values: tuple[float, ...] = ()
        self.velocities: tuple[float, ...] = ()
        self.setMinimumHeight(145)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#edf3ef"))
        painter.setPen(QColor("#243c42"))
        painter.drawText(12, 18, "Timing intervals (ms) / touch velocities (0–127)")
        for values, top, high, color in (
            (self.values, 28.0, max(self.values, default=1), "#4b938c"),
            (self.velocities, 88.0, 127.0, "#d0873f"),
        ):
            if not values:
                continue
            width = (self.width() - 40) / len(values)
            for i, value in enumerate(values):
                x = 20 + (i + 0.5) * width
                painter.setPen(QPen(QColor(color), max(2.0, width * 0.5)))
                painter.drawLine(
                    QPointF(x, top + 35), QPointF(x, top + 35 - value / max(1.0, high) * 35)
                )
                painter.setPen(QColor("#243c42"))
                painter.drawText(QPointF(x - 10, top + 49), f"{value:.0f}")
        painter.end()
