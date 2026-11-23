from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
from app.services.roster import (
    PastedStudent,
    RosterError,
    RosterService,
    fix_pasted_case,
    parse_student_list,
    repeated_names,
)
from app.ui import style


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
            "One student per line, as <i>First Last</i>, <i>Last, First</i> or <i>LAST First</i>, optionally after "
            "a student number. Columns copied from a spreadsheet or a CSV file work too: "
            "first and last name; number, first and last name; or number, first and last name and notes."
        )
        intro.setWordWrap(True)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Ada Lovelace\nHopper, Grace\n007 Alan Turing")
        self.text.textChanged.connect(self._update_preview)

        self.preview = QTableWidget(0, 4)
        self.preview.setHorizontalHeaderLabels(("Student #", "First name", "Last name", "Notes"))
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.skip_existing = QCheckBox("Leave out students already in the class")
        self.skip_existing.setToolTip("e.g. when pasting an updated list of the whole class again")
        self.skip_existing.setChecked(True)
        self.skip_existing.toggled.connect(self._update_preview)

        self.fix_case = QCheckBox("Write names typed in capitals or lowercase the usual way, e.g. LOVELACE → Lovelace")
        self.fix_case.setChecked(True)
        self.fix_case.toggled.connect(self._update_preview)

        self.number_missing = QCheckBox()
        self.number_missing.setToolTip("Otherwise they are added without a number, which can be given later")
        self.number_missing.setChecked(True)
        self.number_missing.toggled.connect(self._update_preview)

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
        layout.addWidget(self.fix_case)
        layout.addWidget(self.skip_existing)
        layout.addWidget(self.number_missing)
        layout.addWidget(self.summary)
        layout.addWidget(self.buttons)
        self._update_preview()

    def _update_preview(self) -> None:
        pasted, problems = parse_student_list(self.text.toPlainText())
        fixed = fix_pasted_case(pasted)
        self.fix_case.setVisible(fixed != pasted)  # only when some name would change
        if self.fix_case.isChecked():
            pasted = fixed
        existing = self.roster.already_in_class(self.class_id, pasted)
        skip = self.skip_existing.isChecked()
        self._students = [s for s in pasted if s not in existing] if skip else pasted
        numbered = self.roster.number_pasted(self.class_id, self._students)
        given = [n.student_no for s, n in zip(self._students, numbered) if s.student_no != n.student_no]
        if given:
            n = len(given)
            self.number_missing.setText(
                f"Give the {'student' if n == 1 else f'{n} students'} without a number the next free "
                + (f"number, {given[0]}" if n == 1 else f"numbers, {given[0]} to {given[-1]}")
            )
        self.number_missing.setVisible(bool(given))  # only when the class or the list uses numbers
        if self.number_missing.isChecked():
            self._students = numbered
        problems += self.roster.number_problems(self.class_id, self._students)
        self.preview.setRowCount(len(self._students))
        for row, s in enumerate(self._students):
            for col, text in enumerate((s.student_no or "", s.first_name, s.last_name, s.notes)):
                self.preview.setItem(row, col, QTableWidgetItem(text))
        self.preview.setColumnHidden(3, not any(s.notes for s in self._students))

        self.problems.setText("<br>".join(problems[:5]) + ("<br>…" if len(problems) > 5 else ""))
        style.set_color(self.problems, style.color(self, "danger"))
        self.problems.setVisible(bool(problems))
        self.skip_existing.setVisible(bool(existing))

        n = len(self._students)
        names = ", ".join(f"{s.first_name} {s.last_name}" for s in existing)
        parts = [f"{n} student{'' if n == 1 else 's'} to add."]
        if existing:
            parts.append(f"Leaving out, already in the class: {names}." if skip else f"Already in the class: {names}.")
        if repeated := repeated_names(self._students):
            parts.append("Listed twice: " + ", ".join(repeated) + ".")
        self.summary.setText(" ".join(parts) if pasted else "")
        self._ok.setText(f"Add {n} student{'' if n == 1 else 's'}" if n else "Add students")
        self._ok.setEnabled(bool(n) and not problems)

    def accept(self) -> None:
        try:
            self.added = self.roster.add_students(self.class_id, self._students)
        except RosterError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
