"""One palette and one stylesheet so every screen reads as the same instrument."""

PAPER = "#f5f5ee"
SURFACE = "#fcfaf3"
CARD = "#fffdf8"
INK = "#243c42"
MUTED = "#5d7378"
FAINT = "#8a9a9c"
RULE = "#dcdccd"
MINT = "#deebe5"
MINT_HOVER = "#c9e0d5"
MINT_BORDER = "#b4cbc3"
TEAL = "#2f7f79"
TEAL_DARK = "#256862"
TEAL_SOFT = "#53a7a2"
ORANGE = "#d0873f"
GREEN = "#3f9b6c"
GREEN_SOFT = "#dff0e4"
AMBER = "#c9962b"
AMBER_SOFT = "#f7ecd0"
RED = "#c8553d"
RED_SOFT = "#f6ddd6"
NIGHT = "#172e35"
NIGHT_LINE = "#28444c"
IVORY = "#edece3"
EBONY = "#2d444b"
RIGHT_HAND = "#64b9a9"
LEFT_HAND = "#d6a969"
COMPUTER = "#6fa8c9"
HINT_WHITE = "#bfe3df"

# Note states published by the engine, mapped to the colour a view should use.
MARK_COLORS = {
    "current": ORANGE,
    "hit": GREEN,
    "done": GREEN,
    "near": AMBER,
    "miss": RED,
}

STYLE = f"""
QMainWindow, QWidget {{ background: {PAPER}; color: {INK}; font-family: 'Segoe UI';
                        font-size: 14px; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {INK}; color: {CARD}; border: none; padding: 6px 8px; }}
QPushButton {{ background: {MINT}; border: 1px solid {MINT_BORDER}; border-radius: 7px;
               padding: 8px 16px; }}
QPushButton:hover {{ background: {MINT_HOVER}; }}
QPushButton:pressed {{ background: {MINT_BORDER}; }}
QPushButton:disabled {{ color: {FAINT}; background: {PAPER}; border-color: {RULE}; }}
QPushButton[role="primary"] {{ background: {TEAL}; color: white; border: 1px solid {TEAL_DARK};
                               font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background: {TEAL_DARK}; }}
QPushButton[role="quiet"] {{ background: transparent; border: 1px solid {RULE}; }}
QPushButton[role="quiet"]:hover {{ background: {MINT}; }}
QPushButton[role="danger"] {{ background: {RED_SOFT}; border: 1px solid {RED}; color: {RED}; }}
QPushButton[role="mode"] {{ background: transparent; border: none; border-radius: 0;
                            border-bottom: 3px solid transparent; padding: 9px 12px;
                            color: {MUTED}; font-size: 15px; }}
QPushButton[role="mode"]:hover {{ color: {INK}; background: {MINT}; }}
QPushButton[role="mode"]:checked {{ color: {INK}; border-bottom: 3px solid {TEAL};
                                    font-weight: 600; }}
QComboBox, QSpinBox {{ padding: 5px 8px; background: {CARD}; border: 1px solid {RULE};
                       border-radius: 6px; min-height: 22px; max-height: 22px; }}
QComboBox:focus, QSpinBox:focus {{ border-color: {TEAL_SOFT}; }}
QComboBox QAbstractItemView {{ background: {CARD}; selection-background-color: {MINT};
                               selection-color: {INK}; border: 1px solid {RULE}; }}
QCheckBox {{ spacing: 7px; background: transparent; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {MINT_BORDER};
                        border-radius: 4px; background: {CARD}; }}
QCheckBox::indicator:hover {{ border-color: {TEAL_SOFT}; }}
QCheckBox::indicator:checked {{ background: {TEAL}; border: 1px solid {TEAL_DARK}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {RULE}; }}
QTabBar::tab {{ padding: 10px 24px; background: transparent; border: none; min-width: 64px;
                border-bottom: 3px solid transparent; color: {MUTED}; font-size: 15px; }}
QTabBar::tab:selected {{ color: {INK}; border-bottom: 3px solid {ORANGE}; }}
QTabBar::tab:hover {{ color: {INK}; }}
QListWidget {{ background: {CARD}; border: 1px solid {RULE}; border-radius: 8px; padding: 4px;
               outline: none; }}
QListWidget::item {{ padding: 0px 8px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {MINT}; color: {INK}; }}
QListWidget::item:hover {{ background: {PAPER}; }}
QFrame[role="card"] {{ background: {CARD}; border: 1px solid {RULE}; border-radius: 10px; }}
QFrame[role="banner"] {{ background: {AMBER_SOFT}; border: 1px solid {AMBER}; border-radius: 8px; }}
QLabel[role="title"] {{ font-size: 22px; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: 12px; font-weight: 600; color: {MUTED}; letter-spacing: 1px; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="chip"] {{ background: {MINT}; border-radius: 10px; padding: 3px 10px; color: {INK}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {MINT_BORDER}; border-radius: 4px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QProgressBar {{ background: {MINT}; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {TEAL}; border-radius: 4px; }}
"""
