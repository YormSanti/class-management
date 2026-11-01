from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import Student
from app.services.roster import PastedStudent, RosterError, RosterService, parse_student_list


class PasteStudentsDialog(QDialog):
    """Add many students by pasting a list, with a live preview of how it was read.

    `added` holds the new students after OK.
    """

    def __init__(self, roster: RosterService, class_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Paste a list of students")
        self.setMinimumSize(720, 440)
        self.roster = roster
        self.class_id = class_id
        self.added: list[Student] = []
        self._students: list[PastedStudent] = []

        intro = QLabel(
            "One student per line, as <i>First Last</i> or <i>Last, First</i>, optionally after "
            "a student number. Columns copied from a spreadsheet work too: first and last "
            "name, or number, first and last name."
        )
        intro.setWordWrap(True)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Ada Lovelace\nHopper, Grace\n007 Alan Turing")
        self.text.textChanged.connect(self._update_preview)

        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(("Student #", "First name", "Last name"))
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.summary = QLabel()
        self.summary.setForegroundRole(QPalette.ColorRole.PlaceholderText)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)

        columns = QHBoxLayout()
        columns.addWidget(self.text, stretch=1)
        columns.addWidget(self.preview, stretch=1)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(columns, stretch=1)
        layout.addWidget(self.problems)
        layout.addWidget(self.summary)
        layout.addWidget(self.buttons)
        self._update_preview()

    def _update_preview(self) -> None:
        self._students, problems = parse_student_list(self.text.toPlainText())
        self.preview.setRowCount(len(self._students))
        for row, s in enumerate(self._students):
            for col, text in enumerate((s.student_no or "", s.first_name, s.last_name)):
                self.preview.setItem(row, col, QTableWidgetItem(text))

        self.problems.setText("<br>".join(problems[:5]) + ("<br>…" if len(problems) > 5 else ""))
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        self.problems.setStyleSheet(f"color: {'#E57A66' if dark else '#B9412E'};")  # dashboard's danger
        self.problems.setVisible(bool(problems))

        n = len(self._students)
        duplicates = [
            f"{s.first_name} {s.last_name}"
            for s in self._students
            if self.roster.same_name_students(Student(self.class_id, s.first_name, s.last_name))
        ]
        summary = f"{n} student{'' if n == 1 else 's'} to add."
        if duplicates:
            summary += " Already in the class: " + ", ".join(duplicates) + "."
        self.summary.setText(summary if n else "")
        self._ok.setText(f"Add {n} student{'' if n == 1 else 's'}" if n else "Add students")
        self._ok.setEnabled(bool(n) and not problems)

    def accept(self) -> None:
        try:
            self.added = self.roster.add_students(self.class_id, self._students)
        except RosterError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
