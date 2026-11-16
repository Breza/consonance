"""Original, fixed vector music glyphs. Coordinates are staff-space units.

No music fonts, SVG assets, Unicode music characters, or platform font metrics.
Stroke outlines are expanded once so all consumers use the same filled paths.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker, QTransform


def _stroke(points: tuple[tuple[float, float], ...], width: float = 0.18) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


def _curve(path: QPainterPath, width: float = 0.18) -> QPainterPath:
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    return stroker.createStroke(path)


def _build() -> dict[str, QPainterPath]:
    glyphs: dict[str, QPainterPath] = {}
    p = QPainterPath()
    p.moveTo(0.65, 3.2)
    p.cubicTo(2.0, 3.6, 0.0, -4.8, 1.3, -4.3)
    p.cubicTo(2.6, -3.5, -0.6, -0.8, -0.1, 0.7)
    p.cubicTo(0.5, 2.5, 3.0, 1.3, 2.1, -0.2)
    p.cubicTo(1.2, -1.5, -0.2, 0.0, 0.9, 0.7)
    glyphs["TrebleClef"] = _curve(p, 0.22)
    p = QPainterPath()
    p.moveTo(0.0, 0.2)
    p.cubicTo(-0.1, -1.8, 2.8, -1.4, 1.9, 0.7)
    p.cubicTo(1.5, 1.7, 0.5, 2.4, -0.1, 2.7)
    p = _curve(p, 0.23)
    for x, y, radius in ((0.25, -0.2, 0.3), (2.5, -0.5, 0.14), (2.5, 0.5, 0.14)):
        p.addEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))
    glyphs["BassClef"] = p
    p = _stroke(((0.2, -1.5), (0.2, 1.4)), 0.12)
    p.addPath(_stroke(((0.85, -1.7), (0.85, 1.2)), 0.12))
    for y in (-0.45, 0.45):
        p.addPath(_stroke(((-0.2, y + 0.2), (1.2, y - 0.2)), 0.26))
    glyphs["Sharp"] = p
    p = _stroke(((0.15, -2), (0.15, 0.65)), 0.14)
    q = QPainterPath()
    q.moveTo(0.15, -0.25)
    q.cubicTo(1.45, -1.2, 1.35, 0.0, 0.15, 0.65)
    p.addPath(_curve(q, 0.18))
    glyphs["Flat"] = p
    p = _stroke(((0.15, -1.6), (0.15, 0.5), (0.85, 0.2), (0.85, -1.0)), 0.14)
    p.addPath(_stroke(((0.15, -0.5), (0.85, -0.8), (0.85, 1.5)), 0.14))
    glyphs["Natural"] = p
    for name, y in (("WholeRest", -1), ("HalfRest", -0.5)):
        p = QPainterPath()
        p.addRect(QRectF(-0.6, y, 1.3, 0.5))
        glyphs[name] = p
    glyphs["QuarterRest"] = _stroke(
        ((0.0, -1.5), (0.6, -0.7), (-0.1, 0.0), (0.65, 0.75), (0.0, 0.45), (-0.2, 1.0), (0.2, 1.5)),
        0.27,
    )
    p = _stroke(((0.65, -0.8), (0.1, 1.5)), 0.15)
    p.addEllipse(QRectF(-0.35, -0.9, 0.75, 0.65))
    p.addPath(_stroke(((0.0, -0.5), (0.65, -0.8)), 0.16))
    glyphs["EighthRest"] = p
    p = QPainterPath()
    p.moveTo(0, 0)
    p.cubicTo(0.1, 1.0, 2.1, 1.0, 0.65, 3.1)
    p.cubicTo(1.3, 1.6, 0.15, 1.6, 0, 1.1)
    p.closeSubpath()
    glyphs["EighthFlag"] = p
    glyphs["EighthFlagDown"] = QTransform().scale(-1, -1).map(p)
    glyphs["2"] = _stroke(
        ((0, -0.6), (0.3, -0.9), (0.85, -0.9), (1.1, -0.55), (0.9, -0.15), (0, 0.8), (1.1, 0.8)),
        0.22,
    )
    glyphs["3"] = _stroke(
        ((0, -0.8), (0.8, -0.9), (1, -0.6), (0.6, 0), (1, 0.4), (0.8, 0.8), (0, 0.8)), 0.22
    )
    glyphs["4"] = _stroke(((0.7, -1), (0, 0.3), (1.2, 0.3)), 0.22)
    glyphs["4"].addPath(_stroke(((0.85, -0.9), (0.85, 0.9)), 0.22))
    return glyphs


GLYPHS = _build()


def notehead(hollow: bool = False, whole: bool = False) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(-0.64 if not whole else -0.8, -0.43, 1.28 if not whole else 1.6, 0.86))
    if hollow:
        hole = QPainterPath()
        hole.addEllipse(QRectF(-0.42, -0.23, 0.84, 0.46))
        path = path.subtracted(hole)
    return QTransform().rotate(-22).map(path)
