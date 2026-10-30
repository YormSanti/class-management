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

from app.models import Subject
from app.services.roster import RosterError


class SubjectDialog(QDialog):
    """Add a subject to `class_id`, or edit `subject`. `save` persists it and may raise RosterError."""

    def __init__(
        self,
        save: Callable[[Subject], Subject],
        class_id: int,
        subject: Subject | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit subject" if subject else "New subject")
        self.setMinimumWidth(360)
        self._save = save
        self._class_id = class_id
        self._original = subject
        self.saved: Subject | None = None

        self.name = QLineEdit(subject.name if subject else "")
        self.name.setPlaceholderText("e.g. Science")
        self.teacher = QLineEdit(subject.teacher if subject else "")
        self.teacher.setPlaceholderText("Leave empty if you teach it")

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
        layout.addRow("Teacher", self.teacher)
        layout.addRow(buttons)

    def accept(self) -> None:
        values = {"name": self.name.text(), "teacher": self.teacher.text()}
        subject = (
            replace(self._original, **values)
            if self._original
            else Subject(class_id=self._class_id, **values)
        )
        try:
            self.saved = self._save(subject)
        except RosterError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
