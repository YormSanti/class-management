from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderView(QWidget):
    """Stand-in page for screens built in later phases."""

    def __init__(self, title: str, note: str, parent: QWidget | None = None):
        super().__init__(parent)
        label = QLabel(f"<h2>{title}</h2><p>{note}</p>")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addWidget(label)

    def set_class(self, class_id: int | None) -> None:
        pass
