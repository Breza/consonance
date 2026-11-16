from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPen, QTransform
from PySide6.QtWidgets import QWidget

from consonance.core.notation_layout import StaffLayout
from consonance.ui.music_glyphs import GLYPHS, notehead


class GrandStaff(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.layout_data: StaffLayout | None = None
        self.show_names = False
        self.guides = False
        self.playhead_x: float | None = None
        self.scroll_x = 0.0
        self.viewport_width: float | None = None
        self.setMinimumHeight(200)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fcfaf3"))
        data = self.layout_data
        if data is None:
            painter.end()
            return
        scale = min(
            (self.width() - 60) / (self.viewport_width or data.width), (self.height() - 75) / 21
        )
        painter.translate(30, max(40.0, (self.height() - 14 * scale) / 2))
        painter.scale(scale, scale)
        painter.translate(-self.scroll_x, 0)
        color = QColor("#243c42")
        for line in data.lines:
            painter.setPen(QPen(color, line.width))
            path = QPainterPath(QPointF(line.x1, line.y1))
            path.lineTo(line.x2, line.y2)
            painter.drawPath(path)
        # A brace is a single vector curve, like every other musical symbol.
        brace = QPainterPath(QPointF(-1.2, 0))
        brace.cubicTo(-3, 1, -1, 6, -2.6, 7)
        brace.cubicTo(-1, 8, -3, 13, -1.2, 14)
        painter.setPen(QPen(color, 0.20))
        painter.drawPath(brace)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for glyph in data.glyphs:
            painter.drawPath(QTransform().translate(glyph.x, glyph.y).map(GLYPHS[glyph.name]))
        for head in data.heads:
            painter.drawPath(
                QTransform().translate(head.x, head.y).map(notehead(head.hollow, head.whole))
            )
            if head.finger is not None or self.show_names:
                painter.save()
                painter.setPen(color)
                font = QFont("Segoe UI")
                font.setPointSizeF(1.2)
                painter.setFont(font)
                text = head.label if self.show_names else str(head.finger)
                painter.drawText(QPointF(head.x - 0.5, head.y - 4.5), text)
                painter.restore()
        for x, y in data.dots:
            path = QPainterPath()
            path.addEllipse(QPointF(x, y), 0.16, 0.16)
            painter.drawPath(path)
        if self.playhead_x is not None:
            painter.setPen(QPen(QColor("#d0873f"), 0.2))
            painter.drawLine(QPointF(self.playhead_x, -2), QPointF(self.playhead_x, 16))
        if self.guides:
            painter.setPen(QPen(QColor("#53a7a2"), 0.18))
            for y in (3.0, 11.0, 6.0):
                painter.drawLine(QPointF(9, y), QPointF(data.width, y))
        painter.end()
