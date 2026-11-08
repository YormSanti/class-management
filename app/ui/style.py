"""Colours, text helpers and the card frame shared by the pages, in light and dark themes."""

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.models import AttendanceStatus

# (light theme, dark theme) colours for statuses; neutrals come from the palette.
COLORS = {
    "accent": ("#2F6B4F", "#6FBF97"),
    "warn": ("#B7791F", "#E0A84A"),
    "danger": ("#B9412E", "#E57A66"),
    "info": ("#3F659C", "#7FA3D9"),
}
STATUS_COLOR = {
    AttendanceStatus.PRESENT.value: "accent",
    AttendanceStatus.LATE.value: "warn",
    AttendanceStatus.ABSENT.value: "danger",
    AttendanceStatus.EXCUSED.value: "info",
}


def is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


def color(widget: QWidget, name: str) -> QColor:
    light, dark = COLORS[name]
    return QColor(dark if is_dark(widget) else light)


def soft(widget: QWidget, name: str) -> QColor:
    """The status colour washed into the background, for pills and avatars."""
    washed = color(widget, name)
    washed.setAlpha(40)
    return washed


def mix(a: QColor, b: QColor, amount: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
    )


def border(widget: QWidget) -> QColor:
    """The hairline colour of cards and dividers."""
    palette = widget.palette()
    return mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text), 0.14)


def on_color(widget: QWidget) -> str:
    """Text colour for filled buttons and badges."""
    return "#10241A" if is_dark(widget) else "white"


def card_stylesheet(widget: QWidget) -> str:
    """Rules for Panel cards, #Divider lines and the #Primary button."""
    line = border(widget).name()
    accent = color(widget, "accent")
    return f"""
        #Panel {{ background: palette(base); border: 1px solid {line}; border-radius: 10px; }}
        #Panel QLabel {{ background: transparent; }}
        #Divider {{ background: {line}; }}
        QPushButton#Primary {{
            background: {accent.name()}; color: {on_color(widget)};
            border: none; border-radius: 6px; padding: 7px 16px; font-weight: 600;
        }}
        QPushButton#Primary:hover {{ background: {accent.darker(115).name()}; }}
        QPushButton#Primary:disabled {{ background: {mix(accent, widget.palette().color(QPalette.ColorRole.Base), 0.6).name()}; }}
    """


def label(text: str = "", size: float = 1.0, bold: bool = False, muted: bool = False) -> QLabel:
    result = QLabel(text)
    font = result.font()
    font.setPointSizeF(font.pointSizeF() * size)
    font.setBold(bold)
    result.setFont(font)
    if muted:
        result.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    return result


def caption(text: str) -> QLabel:
    """Small uppercase heading, e.g. table column names."""
    result = label(text.upper(), 0.78, bold=True, muted=True)
    font = result.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
    result.setFont(font)
    return result


def set_color(text: QLabel, value: QColor) -> None:
    palette = text.palette()
    palette.setColor(QPalette.ColorRole.WindowText, value)
    text.setPalette(palette)
    text.setForegroundRole(QPalette.ColorRole.WindowText)


class Panel(QFrame):
    """A bordered card with an optional title row."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(12)
        if title:
            self.header = QHBoxLayout()
            titles = QVBoxLayout()
            titles.setSpacing(2)
            titles.addWidget(label(title, 1.15, bold=True))
            if subtitle:
                sub = label(subtitle, 0.85, muted=True)
                sub.setWordWrap(True)
                titles.addWidget(sub)
            self.header.addLayout(titles, stretch=1)
            self.body.addLayout(self.header)
