"""Small vector icons drawn with painter paths, so they stay crisp at any scale."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from consonance.ui import theme


def _play() -> QPainterPath:
    """A right-pointing triangle."""
    path = QPainterPath(QPointF(6, 4))
    path.lineTo(19, 12)
    path.lineTo(6, 20)
    path.closeSubpath()
    return path


def _pause() -> QPainterPath:
    """Two upright bars."""
    path = QPainterPath()
    path.addRoundedRect(QRectF(5.5, 4, 4.5, 16), 1, 1)
    path.addRoundedRect(QRectF(14, 4, 4.5, 16), 1, 1)
    return path


def _next() -> QPainterPath:
    """A triangle meeting a bar: skip to the next one."""
    path = QPainterPath(QPointF(4, 4.5))
    path.lineTo(15, 12)
    path.lineTo(4, 19.5)
    path.closeSubpath()
    path.addRoundedRect(QRectF(16.5, 4.5, 3.5, 15), 1, 1)
    return path


def _again(painter: QPainter, color: QColor) -> None:
    """An open ring with an arrowhead: go round again."""
    painter.setPen(QPen(color, 2.6, c=Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(5, 5, 14, 14), 60 * 16, 290 * 16)
    head = QPainterPath(QPointF(13.2, 1.6))
    head.lineTo(19.4, 5.6)
    head.lineTo(13.0, 9.2)
    head.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(head)


def _hint(painter: QPainter, color: QColor) -> None:
    """A light bulb: show me."""
    painter.setPen(QPen(color, 2.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(6, 3, 12, 12))
    painter.setPen(QPen(color, 2.0, c=Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(9.5, 17.5), QPointF(14.5, 17.5))
    painter.drawLine(QPointF(10.5, 20.5), QPointF(13.5, 20.5))


def icon(name: str, color: str = theme.INK, size: int = 20) -> QIcon:
    """Return a named icon: ``play``, ``pause``, ``next``, ``again`` or ``hint``."""
    scale = 3
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size * scale / 24, size * scale / 24)
    tint = QColor(color)
    if name == "again":
        _again(painter, tint)
    elif name == "hint":
        _hint(painter, tint)
    else:
        painter.fillPath({"play": _play, "pause": _pause, "next": _next}[name](), tint)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)
