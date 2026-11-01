from collections.abc import Callable
from dataclasses import replace

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
)

from app.models import Student
from app.services.roster import RosterError


class StudentDialog(QDialog):
    """Add a student to `class_id`, or edit `student`. `save` may raise RosterError.

    `same_name`, if given, returns other students with the entered name; the
    teacher is asked before a second student with that name is saved.
    `suggest_no`, if given, pre-fills the student number of each new student.

    When adding, "Save and add another" keeps the dialog open for the next
    student. `added` lists every student saved, even if the dialog is then cancelled.
    """

    def __init__(
        self,
        save: Callable[[Student], Student],
        class_id: int,
        student: Student | None = None,
        parent: QWidget | None = None,
        *,
        same_name: Callable[[Student], list[Student]] | None = None,
        suggest_no: Callable[[], str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit student" if student else "Add student")
        self.setMinimumWidth(400)
        self._save = save
        self._same_name = same_name
        self._class_id = class_id
        self._original = student
        self._suggest_no = suggest_no
        self.saved: Student | None = None
        self.added: list[Student] = []

        self.student_no = QLineEdit((student.student_no or "") if student else self._next_no())
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
        self._another_button = None
        if student is None:
            self._another_button = buttons.addButton(
                "Save && add another", QDialogButtonBox.ButtonRole.ActionRole
            )
            self._another_button.clicked.connect(self.save_and_add_another)
        self.first_name.textChanged.connect(self._update_ok)
        self.last_name.textChanged.connect(self._update_ok)
        self._update_ok()

        self.status = QLabel()
        self.status.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.status.hide()

        layout = QFormLayout(self)
        layout.addRow("Student #", self.student_no)
        layout.addRow("First name*", self.first_name)
        layout.addRow("Last name*", self.last_name)
        layout.addRow("Notes", self.notes)
        if student:  # new students are always active
            layout.addRow("", self.active)
        layout.addRow(self.status)
        layout.addRow(buttons)

    def _next_no(self) -> str:
        return self._suggest_no() if self._suggest_no else ""

    def _update_ok(self) -> None:
        ready = bool(self.first_name.text().strip() and self.last_name.text().strip())
        self._ok_button.setEnabled(ready)
        if self._another_button is not None:
            self._another_button.setEnabled(ready)

    def accept(self) -> None:
        if self._save_form():
            super().accept()

    def save_and_add_another(self) -> None:
        """Save this student, then clear the form for the next one."""
        if not self._save_form():
            return
        self.status.setText(f"Added {self.saved.full_name}.")
        self.status.show()
        self.student_no.setText(self._next_no())
        for field in (self.first_name, self.last_name):
            field.clear()
        self.notes.clear()
        self.first_name.setFocus()

    def _save_form(self) -> bool:
        """Validate and save the form. False (with a message shown) if it wasn't saved."""
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
        if not self._confirm_name(student):
            return False
        try:
            self.saved = self._save(student)
        except RosterError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return False
        if self._original is None:
            self.added.append(self.saved)
        return True

    def _confirm_name(self, student: Student) -> bool:
        """Ask before saving a name that another student in the class already has."""
        renamed = self._original is None or (
            (student.first_name.strip().casefold(), student.last_name.strip().casefold())
            != (self._original.first_name.casefold(), self._original.last_name.casefold())
        )
        others = self._same_name(student) if self._same_name and renamed else []
        if not others:
            return True
        described = []
        for other in others:
            extra = [f"#{other.student_no}"] if other.student_no else []
            if not other.active:
                extra.append("inactive")
            described.append(other.full_name + (f" ({', '.join(extra)})" if extra else ""))
        answer = QMessageBox.question(
            self,
            self.windowTitle(),
            "This class already has " + ", ".join(described) + ".\n\n"
            "Save another student with the same name?",
        )
        return answer == QMessageBox.StandardButton.Yes
