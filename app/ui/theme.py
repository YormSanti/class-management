"""Light, dark or the system's look for the whole app.

Light and dark use the Fusion style with a fixed palette, so they look the same on
every platform; "system" puts back the platform's own style and palette. The pages
already redraw on palette changes, and pick their colours from the palette.
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from app.config import THEMES

THEME_LABELS = dict(zip(THEMES, ("Match the system", "Light", "Dark"), strict=True))

_Role, _Group = QPalette.ColorRole, QPalette.ColorGroup
_COLORS = {
    # role: (light, dark)
    _Role.Window: ("#F3F3F1", "#202322"),
    _Role.WindowText: ("#1D1F1E", "#E6E8E7"),
    _Role.Base: ("#FFFFFF", "#2A2E2C"),
    _Role.AlternateBase: ("#F6F7F6", "#303432"),
    _Role.Text: ("#1D1F1E", "#E6E8E7"),
    _Role.PlaceholderText: ("#6E7471", "#9AA19D"),
    _Role.Button: ("#F7F7F6", "#333735"),
    _Role.ButtonText: ("#1D1F1E", "#E6E8E7"),
    _Role.BrightText: ("#B9412E", "#E57A66"),
    _Role.Highlight: ("#2F6B4F", "#4F9C77"),
    _Role.HighlightedText: ("#FFFFFF", "#FFFFFF"),
    _Role.ToolTipBase: ("#FFFFFF", "#333735"),
    _Role.ToolTipText: ("#1D1F1E", "#E6E8E7"),
    _Role.Link: ("#3F659C", "#7FA3D9"),
    _Role.Light: ("#FFFFFF", "#3C413E"),
    _Role.Midlight: ("#E9EAE8", "#353937"),
    _Role.Mid: ("#C9CCCA", "#2A2D2B"),
    _Role.Dark: ("#A3A7A5", "#151716"),
    _Role.Shadow: ("#6E7471", "#000000"),
}

_system: tuple[str, QPalette] | None = None  # the platform's style name and palette


def palette(dark: bool) -> QPalette:
    result = QPalette()
    for role, (light_color, dark_color) in _COLORS.items():
        result.setColor(role, QColor(dark_color if dark else light_color))
    for role in (_Role.WindowText, _Role.Text, _Role.ButtonText):
        faded = QColor(result.color(role))
        faded.setAlpha(110)
        result.setColor(_Group.Disabled, role, faded)
    return result


def apply_theme(app: QApplication, theme: str) -> None:
    """Switch the whole app to `theme` ("system", "light" or "dark")."""
    global _system
    if _system is None:
        _system = (app.style().name(), QPalette(app.palette()))
    if theme in ("light", "dark"):
        if app.style().name().lower() != "fusion":
            app.setStyle(QStyleFactory.create("Fusion"))
        app.setPalette(palette(theme == "dark"))
    else:
        style_name, system_palette = _system
        if app.style().name().lower() != style_name.lower():
            app.setStyle(QStyleFactory.create(style_name))
        app.setPalette(system_palette)
    # A widget with its own style sheet keeps the palette it had when the sheet was set,
    # so set each sheet again: the widget then takes its parent's new palette and gets
    # PaletteChange. Parents go first, or a child would copy a parent's old palette.
    # Closed windows are left alone: the app makes its dialogs afresh each time they open.
    shown = [w for w in app.allWidgets() if w.styleSheet() and w.window().isVisible()]
    for widget in sorted(shown, key=_depth):
        sheet = widget.styleSheet()
        widget.setStyleSheet("")
        widget.setStyleSheet(sheet)


def _depth(widget) -> int:
    depth, parent = 0, widget.parentWidget()
    while parent is not None:
        depth, parent = depth + 1, parent.parentWidget()
    return depth
