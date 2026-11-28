from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from app.models import SeatLayout
from app.services.seating import COLS_MAX, ROWS_MAX, SeatingError

DEFAULT_ROWS = 5
DEFAULT_COLS = 6


class LayoutDialog(QDialog):
    """Add a seating plan to `class_id`, or rename/resize `layout`. `save` persists it
    and may raise SeatingError."""

    def __init__(
        self,
        save: Callable[[SeatLayout], SeatLayout],
        class_id: int,
        layout: SeatLayout | None = None,
        parent: QWidget | None = None,
        default_name: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit seating plan" if layout else "New seating plan")
        self.setMinimumWidth(340)
        self._save = save
        self._class_id = class_id
        self._original = layout
        self.saved: SeatLayout | None = None

        self.name = QLineEdit(layout.name if layout else default_name)
        self.name.setPlaceholderText("e.g. Tests or Group work")
        self.rows = QSpinBox()
        self.rows.setRange(1, ROWS_MAX)
        self.rows.setValue(layout.rows if layout else DEFAULT_ROWS)
        self.rows.setToolTip("Rows of desks, from the front of the room to the back")
        self.cols = QSpinBox()
        self.cols.setRange(1, COLS_MAX)
        self.cols.setValue(layout.cols if layout else DEFAULT_COLS)
        self.cols.setToolTip("Seats in each row, from left to right")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(bool(self.name.text().strip()))
        self.name.textChanged.connect(lambda text: ok_button.setEnabled(bool(text.strip())))

        form = QFormLayout(self)
        form.addRow("Name*", self.name)
        form.addRow("Rows", self.rows)
        form.addRow("Seats per row", self.cols)
        form.addRow(buttons)

    def accept(self) -> None:
        values = {"name": self.name.text(), "rows": self.rows.value(), "cols": self.cols.value()}
        layout = replace(self._original, **values) if self._original else SeatLayout(self._class_id, **values)
        try:
            self.saved = self._save(layout)
        except SeatingError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
