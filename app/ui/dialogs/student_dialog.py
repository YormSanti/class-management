from collections.abc import Callable
from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
)

from app.models import Student
from app.services.roster import RosterError


class StudentDialog(QDialog):
    """Add a student to `class_id`, or edit `student`. `save` may raise RosterError."""

    def __init__(
        self,
        save: Callable[[Student], Student],
        class_id: int,
        student: Student | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit student" if student else "Add student")
        self.setMinimumWidth(400)
        self._save = save
        self._class_id = class_id
        self._original = student
        self.saved: Student | None = None

        self.student_no = QLineEdit((student.student_no or "") if student else "")
        self.student_no.setPlaceholderText("Optional")
        self.first_name = QLineEdit(student.first_name if student else "")
        self.last_name = QLineEdit(student.last_name if student else "")
        self.notes = QPlainTextEdit(student.notes if student else "")
        self.notes.setFixedHeight(80)
        self.active = QCheckBox("Active")
        self.active.setChecked(student.active if student else True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.first_name.textChanged.connect(self._update_ok)
        self.last_name.textChanged.connect(self._update_ok)
        self._update_ok()

        layout = QFormLayout(self)
        layout.addRow("Student #", self.student_no)
        layout.addRow("First name*", self.first_name)
        layout.addRow("Last name*", self.last_name)
        layout.addRow("Notes", self.notes)
        if student:  # new students are always active
            layout.addRow("", self.active)
        layout.addRow(buttons)

    def _update_ok(self) -> None:
        self._ok_button.setEnabled(
            bool(self.first_name.text().strip() and self.last_name.text().strip())
        )

    def accept(self) -> None:
        values = {
            "student_no": self.student_no.text(),
            "first_name": self.first_name.text(),
            "last_name": self.last_name.text(),
            "notes": self.notes.toPlainText(),
            "active": self.active.isChecked(),
        }
        if self._original:
            student = replace(self._original, **values)
        else:
            student = Student(class_id=self._class_id, **values)
        try:
            self.saved = self._save(student)
        except RosterError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
