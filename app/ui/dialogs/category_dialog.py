from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from app.models import Category
from app.services.gradebook import WEIGHT_MAX, GradebookError


class CategoryDialog(QDialog):
    """Add a grade category to `subject_id`, or edit `category`. `save` persists it and
    may raise GradebookError."""

    def __init__(
        self,
        save: Callable[[Category], Category],
        subject_id: int,
        category: Category | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit category" if category else "New category")
        self.setMinimumWidth(340)
        self._save = save
        self._subject_id = subject_id
        self._original = category
        self.saved: Category | None = None

        self.name = QLineEdit(category.name if category else "")
        self.name.setPlaceholderText("e.g. Tests")
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0, WEIGHT_MAX)
        self.weight.setDecimals(1)
        self.weight.setValue(category.weight if category else 10)
        self.weight.setToolTip(
            "How much the category counts towards the average, compared with the others. "
            "Weights needn't add up to 100; 0 leaves the category out of the average "
            "(unless every category is 0: then they count equally)."
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(bool(self.name.text().strip()))
        self.name.textChanged.connect(lambda text: ok_button.setEnabled(bool(text.strip())))

        layout = QFormLayout(self)
        layout.addRow("Name*", self.name)
        layout.addRow("Weight", self.weight)
        layout.addRow(buttons)

    def accept(self) -> None:
        values = {"name": self.name.text(), "weight": self.weight.value()}
        category = replace(self._original, **values) if self._original else Category(self._subject_id, **values)
        try:
            self.saved = self._save(category)
        except GradebookError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
