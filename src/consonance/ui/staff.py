"""Grand-staff view: cached vector paths, a pinned clef header, and coloured note states."""

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from consonance.core.notation_layout import STAFF_LINES, StaffLayout
from consonance.ui import theme
from consonance.ui.music_glyphs import GLYPHS, notehead

BRACE = 3.0  # staff spaces reserved left of the opening barline for the brace
TAIL = 2.6  # staff spaces reserved right of the system for guide labels
MAX_SCALE = 21.0
MAX_SCROLL_SCALE = 15.0
_HEAD_SHAPES = {
    (False, False): notehead(False, False),
    (True, False): notehead(True, False),
    (True, True): notehead(True, True),
    (False, True): notehead(False, True),
}


@dataclass
class _Paths:
    """Painter paths built once per layout; painting a frame only replays them."""

    lines: dict[float, QPainterPath] = field(default_factory=dict)
    glyphs: QPainterPath = field(default_factory=QPainterPath)
    heads: QPainterPath = field(default_factory=QPainterPath)
    dots: QPainterPath = field(default_factory=QPainterPath)
    header: QPainterPath = field(default_factory=QPainterPath)
    head_paths: list[QPainterPath] = field(default_factory=list)
    by_mark: dict[tuple[int, int], list[int]] = field(default_factory=dict)


def _build(data: StaffLayout) -> _Paths:
    """Convert a layout into filled and stroked painter paths."""
    paths = _Paths()
    paths.glyphs.setFillRule(Qt.FillRule.WindingFill)
    paths.header.setFillRule(Qt.FillRule.WindingFill)
    for line in data.lines:
        path = paths.lines.setdefault(line.width, QPainterPath())
        path.moveTo(line.x1, line.y1)
        path.lineTo(line.x2, line.y2)
    for glyph in data.glyphs:
        paths.glyphs.addPath(GLYPHS[glyph.name].translated(glyph.x, glyph.y))
    for glyph in data.header:
        paths.header.addPath(GLYPHS[glyph.name].translated(glyph.x, glyph.y))
    for number, head in enumerate(data.heads):
        shape = _HEAD_SHAPES[(head.hollow, head.whole)].translated(head.x, head.y)
        paths.head_paths.append(shape)
        paths.heads.addPath(shape)
        paths.by_mark.setdefault((head.staff, head.index), []).append(number)
    for x, y in data.dots:
        paths.dots.addEllipse(QPointF(x, y), 0.16, 0.16)
    return paths


def _brace() -> QPainterPath:
    """Build the brace that joins the two staves, as one filled vector shape."""
    path = QPainterPath(QPointF(-0.9, 0))
    path.cubicTo(-2.6, 1.2, -0.7, 5.6, -2.3, 7)
    path.cubicTo(-0.7, 8.4, -2.6, 12.8, -0.9, 14)
    path.cubicTo(-2.0, 12.6, -0.2, 8.6, -1.85, 7)
    path.cubicTo(-0.2, 5.4, -2.0, 1.4, -0.9, 0)
    return path


class GrandStaff(QWidget):
    """Draw a :class:`StaffLayout`, optionally scrolling it under a pinned header."""

    def __init__(self) -> None:
        """Create an empty staff view."""
        super().__init__()
        self.layout_data: StaffLayout | None = None
        self.show_names = False
        self.guides = False
        self.fingering = "starts"
        self.playhead: float | None = None
        self.scrolling = False
        self.marks: tuple[tuple[int, int, str], ...] = ()
        self._cached_for: StaffLayout | None = None
        self._paths = _Paths()
        self._brace = _brace()
        self.setMinimumHeight(170)

    def show_state(
        self,
        layout: StaffLayout | None,
        marks: tuple[tuple[int, int, str], ...],
        playhead: float | None,
        scrolling: bool,
        names: bool,
        guides: bool,
        fingering: str,
    ) -> None:
        """Adopt what to draw, repainting only if something actually changed."""
        state = (marks, playhead, scrolling, names, guides, fingering)
        current = (
            self.marks,
            self.playhead,
            self.scrolling,
            self.show_names,
            self.guides,
            self.fingering,
        )
        if layout is self.layout_data and state == current:
            return
        self.layout_data = layout
        self.marks, self.playhead, self.scrolling = marks, playhead, scrolling
        self.show_names, self.guides, self.fingering = names, guides, fingering
        self.update()

    def _geometry(self, data: StaffLayout) -> tuple[float, float, float, float]:
        """Return scale, the screen position of the layout origin, and the scroll offset."""
        height_units = data.bottom - data.top
        fit_height = (self.height() - 12) / height_units
        if self.scrolling:
            scale = max(3.0, min(fit_height, MAX_SCROLL_SCALE))
            x0 = BRACE * scale + 6
        else:
            fit_width = (self.width() - 16) / (data.width + BRACE + TAIL)
            scale = max(3.0, min(fit_height, fit_width, MAX_SCALE))
            x0 = (self.width() - (data.width + BRACE + TAIL) * scale) / 2 + BRACE * scale
        y0 = (self.height() - height_units * scale) / 2 - data.top * scale
        scroll = 0.0
        if self.scrolling and self.playhead is not None:
            visible = (self.width() - x0) / scale
            anchor = data.header_width + (visible - data.header_width) * 0.28
            limit = max(0.0, data.width + 1.5 - visible)
            scroll = min(max(0.0, data.x_at(self.playhead) - anchor), limit)
        return scale, x0, y0, scroll

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the staff, its notes, any coloured note states, and the playhead."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))
        data = self.layout_data
        if data is None:
            painter.end()
            return
        if self._cached_for is not data:
            self._paths = _build(data)
            self._cached_for = data
        paths = self._paths
        scale, x0, y0, scroll = self._geometry(data)
        ink = QColor(theme.INK)
        visible = (self.width() - x0) / scale
        painter.translate(x0, y0)
        painter.scale(scale, scale)

        painter.save()
        if self.scrolling:
            painter.setClipRect(QRectF(data.header_width, data.top - 2, visible, 30))
        painter.translate(-scroll, 0)
        marked = [
            (number, state)
            for staff, index, state in self.marks
            for key in (((staff, index),) if staff >= 0 else ((0, index), (1, index)))
            for number in paths.by_mark.get(key, ())
        ]
        for number, state in marked:
            if state == "current":
                x = data.heads[number].x
                painter.fillRect(QRectF(x - 1.5, -1.6, 3.0, 17.2), QColor(208, 135, 63, 34))
        if self.guides:
            self._draw_guides(painter, data, scroll, visible)
        for width, path in paths.lines.items():
            painter.strokePath(path, QPen(ink, width, c=Qt.PenCapStyle.FlatCap))
        painter.fillPath(paths.glyphs, ink)
        painter.fillPath(paths.heads, ink)
        painter.fillPath(paths.dots, ink)
        for number, state in marked:
            painter.fillPath(
                paths.head_paths[number], QColor(theme.MARK_COLORS.get(state, theme.INK))
            )
        if self.playhead is not None:
            x = data.x_at(self.playhead)
            painter.setPen(QPen(QColor(theme.ORANGE), 0.22, c=Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x, -1.8), QPointF(x, 15.8))
        painter.restore()

        # The header is drawn last so scrolled music passes underneath it.
        if self.scrolling:
            painter.fillRect(
                QRectF(-BRACE - 2, data.top - 2, data.header_width + BRACE + 2, 30),
                QColor(theme.SURFACE),
            )
            pen = QPen(ink, 0.10, c=Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            for y in STAFF_LINES:
                painter.drawLine(QPointF(0, y), QPointF(data.header_width, y))
            painter.setPen(QPen(ink, 0.16, c=Qt.PenCapStyle.FlatCap))
            painter.drawLine(QPointF(0, 0), QPointF(0, 14))
        painter.fillPath(paths.header, ink)
        painter.fillPath(self._brace, ink)
        painter.resetTransform()
        self._draw_text(painter, data, scale, x0, y0, scroll)
        painter.end()

    def _draw_guides(
        self, painter: QPainter, data: StaffLayout, scroll: float, visible: float
    ) -> None:
        """Tint the landmark lines: treble G, bass F, and both homes of middle C."""
        left = data.header_width + scroll
        right = scroll + visible if self.scrolling else data.width
        soft = QColor(theme.TEAL_SOFT)
        soft.setAlpha(150)
        painter.setPen(QPen(soft, 0.34, c=Qt.PenCapStyle.FlatCap))
        for y in (3.0, 11.0):
            painter.drawLine(QPointF(left, y), QPointF(right, y))
        dashed = QPen(soft, 0.16, Qt.PenStyle.DashLine, Qt.PenCapStyle.FlatCap)
        painter.setPen(dashed)
        for y in (5.0, 9.0):
            painter.drawLine(QPointF(left, y), QPointF(right, y))

    def _draw_text(
        self,
        painter: QPainter,
        data: StaffLayout,
        scale: float,
        x0: float,
        y0: float,
        scroll: float,
    ) -> None:
        """Draw ordinary text in device pixels so it stays crisp at any staff size."""
        left_limit = x0 + (data.header_width * scale if self.scrolling else -1e9)
        font = QFont("Segoe UI")
        font.setPixelSize(round(max(9.0, min(19.0, scale * 1.3))))
        painter.setFont(font)
        painter.setPen(QColor(theme.INK))
        for head in data.heads:
            if self.show_names:
                text = head.label
            elif (
                head.finger is not None
                and self.fingering != "off"
                and (self.fingering == "all" or head.finger_start)
            ):
                text = str(head.finger)
            else:
                continue
            x = x0 + (head.x - scroll) * scale
            if left_limit <= x <= self.width() + 20:
                y = y0 + head.text_y * scale
                painter.drawText(QRectF(x - 40, y - 14, 80, 28), Qt.AlignmentFlag.AlignCenter, text)
        small = QFont("Segoe UI")
        small.setPixelSize(round(max(8.0, min(13.0, scale * 0.95))))
        painter.setFont(small)
        painter.setPen(QColor(theme.MUTED))
        for label in data.labels:
            x = x0 + (label.x - scroll) * scale
            if left_limit <= x <= self.width():
                y = y0 + label.y * scale
                painter.drawText(QPointF(x, y), label.text)
        if self.guides and not self.scrolling:
            painter.setPen(QColor(theme.TEAL))
            x = x0 + (data.width + 0.6) * scale
            for y, text in ((3.0, "G"), (5.0, "C"), (9.0, "C"), (11.0, "F")):
                painter.drawText(
                    QRectF(x, y0 + y * scale - 12, 40, 24),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    text,
                )
