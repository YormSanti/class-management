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
    """Create or edit a class. `save` persists it and may raise RosterError."""

    def __init__(
        self,
        save: Callable[[SchoolClass], SchoolClass],
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
        self.subject = QLineEdit(school_class.subject if school_class else "")
        self.subject.setPlaceholderText("e.g. Mathematics")
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
        layout.addRow("Subject", self.subject)
        layout.addRow("Term", self.term)
        layout.addRow(buttons)

    def accept(self) -> None:
        values = {
            "name": self.name.text(),
            "subject": self.subject.text(),
            "term": self.term.text(),
        }
        school_class = replace(self._original, **values) if self._original else SchoolClass(**values)
        try:
            self.saved = self._save(school_class)
        except RosterError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
