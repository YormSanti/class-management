from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from app.models import SchoolClass
from app.services.roster import RosterError


class ClassDialog(QDialog):
    """Create or edit a class. `save(school_class, first_subject)` persists it and may
    raise RosterError. The first-subject field is only shown for a new class."""

    def __init__(
        self,
        save: Callable[[SchoolClass, str], SchoolClass],
        school_class: SchoolClass | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit class" if school_class else "New class")
        self.setMinimumWidth(360)
        self._save = save
        self._original = school_class
        self.saved: SchoolClass | None = None

        self.name = QLineEdit(school_class.name if school_class else "")
        self.name.setPlaceholderText("e.g. 7B")
        self.first_subject = QLineEdit()
        self.first_subject.setPlaceholderText("e.g. Mathematics (more can be added later)")
        self.term = QLineEdit(school_class.term if school_class else "")
        self.term.setPlaceholderText("e.g. 2026 Term 1")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(bool(self.name.text().strip()))
        self.name.textChanged.connect(lambda text: ok_button.setEnabled(bool(text.strip())))

        layout = QFormLayout(self)
        layout.addRow("Name*", self.name)
        layout.addRow("Term", self.term)
        if school_class is None:
            layout.addRow("First subject", self.first_subject)
        layout.addRow(buttons)

    def accept(self) -> None:
        values = {"name": self.name.text(), "term": self.term.text()}
        school_class = replace(self._original, **values) if self._original else SchoolClass(**values)
        try:
            self.saved = self._save(school_class, self.first_subject.text())
        except RosterError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
