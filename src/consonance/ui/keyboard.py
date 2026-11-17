"""A realistic piano keyboard: shared key geometry and a widget that shows key states."""

from collections.abc import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import QWidget

from consonance.core.notation import MIDDLE_C, PIANO_HIGH, PIANO_LOW, is_black_key
from consonance.ui import theme

BASE_RANGE = (36, 84)  # C2..C6 covers every drill; the view widens only when it has to
BLACK_WIDTH = 0.62
BLACK_HEIGHT = 0.62
LETTERS = "C D EF G A B"


def fit_range(pitches: Iterable[int], base: tuple[int, int] = BASE_RANGE) -> tuple[int, int]:
    """Return a keyboard range, snapped to whole octaves, that shows every given pitch."""
    low, high = base
    for pitch in pitches:
        low, high = min(low, pitch), max(high, pitch)
    low = max(PIANO_LOW, (low // 12) * 12)
    high = min(PIANO_HIGH, -(-high // 12) * 12)
    return low, high


class KeyGeometry:
    """Where each key of a keyboard range sits horizontally.

    The same geometry places both the drawn keys and the falling notes above them, so a
    note always lands on the key it belongs to.
    """

    def __init__(self, low: int, high: int, x: float, width: float) -> None:
        """Lay out the white keys of ``low..high`` evenly across ``width`` from ``x``."""
        while is_black_key(low):
            low -= 1
        while is_black_key(high):
            high += 1
        self.low, self.high = low, high
        self.whites = [p for p in range(low, high + 1) if not is_black_key(p)]
        self.blacks = [p for p in range(low, high + 1) if is_black_key(p)]
        self.x = x
        self.white_width = width / len(self.whites)
        self._index = {pitch: i for i, pitch in enumerate(self.whites)}

    def contains(self, pitch: int) -> bool:
        """Report whether a pitch is inside the drawn range."""
        return self.low <= pitch <= self.high

    def span(self, pitch: int) -> tuple[float, float]:
        """Return the left edge and width of a key."""
        if not is_black_key(pitch):
            return self.x + self._index[pitch] * self.white_width, self.white_width
        width = self.white_width * BLACK_WIDTH
        left = self.x + (self._index[pitch - 1] + 1) * self.white_width - width / 2
        return left, width

    def lane(self, pitch: int) -> tuple[float, float]:
        """Return the column a falling note for this key occupies."""
        left, width = self.span(pitch)
        inset = 0.0 if is_black_key(pitch) else width * 0.17
        return left + inset, width - 2 * inset

    def pitch_at(self, x: float, y: float, height: float) -> int | None:
        """Return the key under a point, preferring black keys where they overlap."""
        if y < height * BLACK_HEIGHT:
            for pitch in self.blacks:
                left, width = self.span(pitch)
                if left <= x <= left + width:
                    return pitch
        index = int((x - self.x) // self.white_width)
        return self.whites[index] if 0 <= index < len(self.whites) else None


def paint_keys(
    painter: QPainter,
    geometry: KeyGeometry,
    top: float,
    height: float,
    fills: dict[int, QColor],
    name_all: bool = False,
) -> None:
    """Draw a keyboard; ``fills`` overrides the colour of individual keys."""
    painter.setPen(Qt.PenStyle.NoPen)
    for pitch in geometry.whites:
        left, width = geometry.span(pitch)
        path = QPainterPath()
        path.addRoundedRect(QRectF(left + 0.5, top, width - 1, height), 2.5, 2.5)
        painter.fillPath(path, fills.get(pitch, QColor(theme.IVORY)))
    for pitch in geometry.blacks:
        left, width = geometry.span(pitch)
        path = QPainterPath()
        path.addRoundedRect(QRectF(left, top, width, height * BLACK_HEIGHT), 2, 2)
        painter.fillPath(path, fills.get(pitch, QColor(theme.EBONY)))
    font = QFont("Segoe UI")
    font.setPixelSize(round(max(8.0, min(12.0, geometry.white_width * 0.42))))
    painter.setFont(font)
    for pitch in geometry.whites:
        if pitch % 12 and not name_all:
            continue
        left, width = geometry.span(pitch)
        text = f"C{pitch // 12 - 1}" if pitch % 12 == 0 else LETTERS[pitch % 12]
        painter.setPen(QColor(theme.MUTED))
        box = QRectF(left, top + height - 18, width, 16)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        if pitch == MIDDLE_C:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ORANGE))
            painter.drawEllipse(QPointF(left + width / 2, top + height - 24), 2.6, 2.6)
            painter.setBrush(Qt.BrushStyle.NoBrush)


def key_fills(
    held: frozenset[int],
    expected: frozenset[int],
    allowed: frozenset[int],
    lit: frozenset[int],
    reveal: bool,
) -> dict[int, QColor]:
    """Choose a colour for every key that is not in its resting state.

    A held key is green when it is wanted, red when it is not, and orange when nothing is
    being asked. Keys the computer is sounding are blue, and wanted keys glow teal when
    the answer is being shown.
    """
    fills: dict[int, QColor] = {}
    if reveal:
        for pitch in expected:
            fills[pitch] = QColor(theme.TEAL_SOFT if is_black_key(pitch) else theme.HINT_WHITE)
    for pitch in lit:
        fills[pitch] = QColor(theme.COMPUTER)
    for pitch in held:
        if not expected:
            fills[pitch] = QColor(theme.ORANGE)
        elif pitch in expected:
            fills[pitch] = QColor(theme.GREEN)
        elif pitch in allowed:
            fills[pitch] = QColor(theme.AMBER)
        else:
            fills[pitch] = QColor(theme.RED)
    return fills


class KeyboardWidget(QWidget):
    """Show the piano keyboard with held, wanted, and computer-played keys coloured.

    The keys can also be clicked, which is a silent way to answer without a piano.
    """

    key_pressed = Signal(int)
    key_released = Signal(int)

    def __init__(self) -> None:
        """Create a keyboard over the default four-octave range."""
        super().__init__()
        self.low, self.high = BASE_RANGE
        self.held: frozenset[int] = frozenset()
        self.expected: frozenset[int] = frozenset()
        self.allowed: frozenset[int] = frozenset()
        self.lit: frozenset[int] = frozenset()
        self.reveal = False
        self.name_all = False
        self._mouse_pitch: int | None = None
        self.setMinimumHeight(84)
        self.setMaximumHeight(118)

    def geometry_now(self) -> KeyGeometry:
        """Return the key layout for the widget's current size and range."""
        return KeyGeometry(self.low, self.high, 0.0, float(self.width()))

    def show_state(
        self,
        held: frozenset[int],
        expected: frozenset[int],
        allowed: frozenset[int],
        lit: frozenset[int],
        reveal: bool,
        name_all: bool,
    ) -> None:
        """Adopt new key states, widening the range if a key would be off the edge."""
        state = (held, expected, allowed, lit, reveal, name_all)
        if state == (self.held, self.expected, self.allowed, self.lit, self.reveal, self.name_all):
            return
        self.held, self.expected, self.allowed, self.lit, self.reveal, self.name_all = state
        shown = held | lit | (expected if len(expected) <= 12 else frozenset())
        low, high = fit_range(shown, (self.low, self.high))
        self.low, self.high = low, high
        self.update()

    def reset_range(self) -> None:
        """Return to the default range, for example when a new drill starts."""
        if (self.low, self.high) != BASE_RANGE:
            self.low, self.high = BASE_RANGE
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the keys in their current states."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.NIGHT))
        fills = key_fills(self.held, self.expected, self.allowed, self.lit, self.reveal)
        paint_keys(painter, self.geometry_now(), 3.0, self.height() - 3.0, fills, self.name_all)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Press the key under the pointer."""
        position = event.position()
        pitch = self.geometry_now().pitch_at(position.x(), position.y() - 3, self.height() - 3)
        if pitch is not None and event.button() == Qt.MouseButton.LeftButton:
            self._mouse_pitch = pitch
            self.key_pressed.emit(pitch)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Release the key that the pointer pressed."""
        if self._mouse_pitch is not None:
            self.key_released.emit(self._mouse_pitch)
            self._mouse_pitch = None
