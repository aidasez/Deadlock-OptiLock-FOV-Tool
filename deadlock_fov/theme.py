"""Theming: palette, monospace font, and the live info panel.

archey3 renders one line per row as ``{colour}Title:{reset} value``. We keep
that typography and colour semantics, but draw it with QPainter so the columns
are pixel-exact, and the logo is behind the ``SHOW_LOGO`` switch in ``logo.py``.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .logo import LOGO, SHOW_LOGO

PADDING = 8
LINE_SPACING = 1.08
RADIUS = 7

# Shadcn-inspired zinc palette: neutral surfaces, subtle borders, and a clear
# primary action. Status colours remain semantic.
PALETTE: dict[str, str] = {
    "window": "#09090b",
    "card": "#0f0f12",
    "panel": "#0f0f12",
    "border": "#27272a",
    "border_soft": "#27272a",
    "title": "#e4e4e7",
    "logo1": "#4fc97e",      # bold tone
    "logo2": "#2a6b45",      # non-bold tone
    "fg": "#fafafa",
    "dim": "#a1a1aa",
    "ok": "#4ade80",
    "warn": "#facc15",
    "err": "#f87171",
    "accent": "#fafafa",
    "input_bg": "#09090b",
    "input_border": "#3f3f46",
    "hover": "#18181b",
    "pressed": "#27272a",
    "log_bg": "#08080a",
}

MONO_CANDIDATES = (
    "Cascadia Mono",
    "Cascadia Code",
    "Consolas",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Courier New",
)

_RADIUS_SM = 6


def mono_family() -> str:
    available = set(QFontDatabase.families())
    for family in MONO_CANDIDATES:
        if family in available:
            return family
    return "monospace"


def mono_font(point_size: int = 10, bold: bool = False) -> QFont:
    font = QFont(mono_family(), point_size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setBold(bold)
    return font


def ui_family() -> str:
    return "Segoe UI" if "Segoe UI" in set(QFontDatabase.families()) else "sans-serif"


def ui_font(point_size: int = 9, bold: bool = False) -> QFont:
    font = QFont(ui_family(), point_size)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setBold(bold)
    return font


def _art() -> tuple[tuple[str, int], ...]:
    return LOGO if SHOW_LOGO else ()


class ArcheyPanel(QWidget):
    """``Title: value`` rows, optionally beside the logo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info: list[tuple[str, str, str]] = []
        self._font = ui_font(9)
        self._title_font = ui_font(9, bold=True)
        self.setFont(self._font)
        # Fixed height: the panel must never be squashed, or rows get clipped.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # -- content -----------------------------------------------------------

    def set_info(self, info: list[tuple[str, str, str]]) -> None:
        """``info`` is a list of ``(title, value, colour_key)``."""
        self._info = list(info)
        _, _, _, _, height = self._layout_metrics()
        self.setMinimumHeight(height)
        self.updateGeometry()
        self.update()

    def value_for(self, title: str) -> str:
        wanted = title.lower()
        for line_title, value, _ in self._info:
            if line_title.lower() == wanted:
                return value
        return ""

    def titles(self) -> list[str]:
        return [title for title, _, _ in self._info]

    # -- geometry ----------------------------------------------------------

    def _layout_metrics(self) -> tuple[QFontMetrics, float, int, int, int]:
        metrics = QFontMetrics(self._font)
        title_metrics = QFontMetrics(self._title_font)
        logo_width = self._logo_columns() * self._cell_width(metrics)
        gap = metrics.horizontalAdvance("   ") if logo_width else 0
        info_width = 0
        for title, value, _ in self._info:
            value_metrics = title_metrics if title.lower() == "status" else metrics
            info_width = max(
                info_width,
                title_metrics.horizontalAdvance(f"{title}: ")
                + value_metrics.horizontalAdvance(value),
            )
        # The install path gets a full-width row; the remaining summary fields
        # are paired to keep the status card short.
        info_rows = 1 + (max(0, len(self._info) - 1) + 1) // 2
        rows = max(len(_art()), info_rows, 1)
        line_height = self._line_height(metrics)
        width = PADDING * 2 + int(logo_width) + gap + info_width
        height = PADDING * 2 + line_height * rows
        return metrics, logo_width, gap, width, height

    @staticmethod
    def _logo_columns() -> int:
        return max((len(row) for row, _ in _art()), default=0)

    @staticmethod
    def _cell_width(metrics: QFontMetrics) -> float:
        """One art cell. The block glyph's own advance keeps the art's aspect."""
        if not _art():
            return 0.0
        advance = metrics.horizontalAdvance("█")
        return float(advance) if advance > 0 else metrics.height() * 0.6

    @staticmethod
    def _line_height(metrics: QFontMetrics) -> int:
        return int(metrics.lineSpacing() * LINE_SPACING)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        _, _, _, width, height = self._layout_metrics()
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.sizeHint()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        metrics, logo_width, gap, _, _ = self._layout_metrics()
        line_height = self._line_height(metrics)
        cell_width = self._cell_width(metrics)
        art = _art()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        painter.setPen(QPen(QColor(PALETTE["border"]), 1))
        painter.setBrush(QColor(PALETTE["panel"]))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), RADIUS, RADIUS)

        baseline = PADDING + metrics.ascent()
        info_x = PADDING + int(logo_width) + gap
        available_width = max(1, self.width() - info_x - PADDING)
        column_width = available_width // 2

        # The logo is filled rectangles, not text: U+2588 is inset inside its
        # cell in most fonts, so glyphs leave seams and the shape breaks up.
        if art:
            painter.setPen(Qt.PenStyle.NoPen)
            for row, (art_row, tone) in enumerate(art):
                top = round(PADDING + row * line_height)
                bottom = round(PADDING + (row + 1) * line_height)
                colour = QColor(PALETTE["logo1" if tone == 1 else "logo2"])
                for column, glyph in enumerate(art_row):
                    if glyph != "█":
                        continue
                    left = round(PADDING + column * cell_width)
                    right = round(PADDING + (column + 1) * cell_width)
                    painter.fillRect(left, top, right - left, bottom - top, colour)

        for index, (title, value, tone) in enumerate(self._info):
            if index == 0:
                row = 0
                x = info_x
                text_width = available_width
            else:
                pair_index = index - 1
                row = 1 + pair_index // 2
                x = info_x + (pair_index % 2) * column_width
                text_width = column_width - 6
            y = baseline + row * line_height
            painter.setFont(self._title_font)
            painter.setPen(QColor(PALETTE["title"]))
            painter.drawText(x, y, f"{title}:")
            title_metrics = QFontMetrics(self._title_font)
            offset = title_metrics.horizontalAdvance(f"{title}: ")
            # The status line is the one row people glance at, so keep it bold.
            is_status = title.lower() == "status"
            painter.setFont(self._title_font if is_status else self._font)
            painter.setPen(QColor(PALETTE.get(tone, PALETTE["fg"])))
            value_width = max(0, int(text_width - offset))
            shown_value = metrics.elidedText(value, Qt.TextElideMode.ElideRight, value_width)
            painter.drawText(x + offset, y, shown_value)

        painter.end()


def stylesheet() -> str:
    """Softer take on the terminal look: cards, rounded corners, quiet hovers."""
    p = PALETTE
    return f"""
    QMainWindow, QMainWindow > QWidget {{
        background: {p["window"]};
    }}
    QWidget {{
        background: transparent;
        color: {p["fg"]};
        font-family: "{ui_family()}";
        font-size: 9pt;
    }}
    QToolTip {{
        background: {p["card"]};
        color: {p["fg"]};
        border: 1px solid {p["border"]};
        padding: 5px 7px;
    }}

    QGroupBox {{
        background: {p["card"]};
        border: 1px solid {p["border_soft"]};
        border-radius: {RADIUS}px;
        margin-top: 9px;
        padding: 5px 8px 4px 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 8px;
        padding: 0 5px;
        color: {p["title"]};
        background: {p["window"]};
    }}

    QLabel {{
        background: transparent;
        color: {p["dim"]};
    }}
    QLabel#value {{
        color: {p["fg"]};
    }}
    QCheckBox {{
        background: transparent;
        spacing: 5px;
        color: {p["fg"]};
        padding: 1px 0;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {p["input_border"]};
        border-radius: 4px;
        background: {p["input_bg"]};
    }}
    QCheckBox::indicator:hover {{
        border: 1px solid {p["title"]};
    }}
    QCheckBox::indicator:checked {{
        background: {p["title"]};
        border: 1px solid {p["title"]};
    }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {p["input_bg"]};
        border: 1px solid {p["input_border"]};
        border-radius: {_RADIUS_SM}px;
        padding: 2px 6px;
        min-height: 16px;
        color: {p["fg"]};
        selection-background-color: {p["title"]};
        selection-color: #09090b;
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
        border: 1px solid #52525b;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 1px solid {p["title"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        width: 8px;
        height: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {p["card"]};
        border: 1px solid {p["border"]};
        border-radius: 8px;
        padding: 4px;
        color: {p["fg"]};
        selection-background-color: {p["pressed"]};
        selection-color: #ffffff;
        outline: none;
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        background: transparent;
        border: none;
        width: 15px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
        background: {p["hover"]};
        border-radius: 3px;
    }}

    QPushButton {{
        background: {p["input_bg"]};
        border: 1px solid {p["input_border"]};
        border-radius: {_RADIUS_SM}px;
        color: {p["accent"]};
        padding: 3px 9px;
        min-height: 14px;
    }}
    QPushButton:hover {{
        background: {p["hover"]};
        border: 1px solid #52525b;
        color: #ffffff;
    }}
    QPushButton:pressed {{
        background: {p["pressed"]};
        color: #ffffff;
    }}
    QPushButton:default {{
        border: 1px solid {p["title"]};
        background: {p["title"]};
        color: #09090b;
    }}
    QPushButton:default:hover {{
        background: #d4d4d8;
    }}
    QPushButton:disabled {{
        color: #52525b;
        border: 1px solid {p["border_soft"]};
        background: {p["input_bg"]};
    }}

    QPlainTextEdit {{
        background: {p["log_bg"]};
        border: 1px solid {p["border_soft"]};
        border-radius: {RADIUS}px;
        color: {p["dim"]};
        padding: 6px 8px;
        selection-background-color: {p["pressed"]};
        selection-color: #ffffff;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 9px;
        margin: 4px 2px 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p["input_border"]};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #52525b;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    """
