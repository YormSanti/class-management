from collections.abc import Callable
from dataclasses import replace
from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from app.models import Assignment, Category
from app.services.gradebook import MAX_SCORE_LIMIT, GradebookError


class AssignmentDialog(QDialog):
    """Add an assignment to `subject_id`, or edit `assignment`. `save` persists it and may
    raise GradebookError. A new one starts in `default_category` (an id), dated `today`."""

    def __init__(
        self,
        save: Callable[[Assignment], Assignment],
        subject_id: int,
        categories: list[Category],
        assignment: Assignment | None = None,
        parent: QWidget | None = None,
        *,
        default_category: int | None = None,
        default_max: float = 10,
        today: date | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit assignment" if assignment else "New assignment")
        self.setMinimumWidth(380)
        self._save = save
        self._subject_id = subject_id
        self._original = assignment
        self.saved: Assignment | None = None

        self.title = QLineEdit(assignment.title if assignment else "")
        self.title.setPlaceholderText("e.g. Test 1: fractions")
        self.category = QComboBox()
        for category in categories:
            self.category.addItem(category.name, category.id)
        wanted = assignment.category_id if assignment else default_category
        if (index := self.category.findData(wanted)) >= 0:
            self.category.setCurrentIndex(index)
        self.max_score = QDoubleSpinBox()
        self.max_score.setRange(0.5, MAX_SCORE_LIMIT)
        self.max_score.setDecimals(1)
        self.max_score.setValue(assignment.max_score if assignment else default_max)
        self.max_score.setToolTip("The points a student gets for a perfect answer")

        day = (assignment.date if assignment else today or date.today()) or today or date.today()
        self.date = QDateEdit(QDate(day.year, day.month, day.day))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("d MMM yyyy")
        self.dated = QCheckBox("Dated")
        self.dated.setChecked(assignment is None or assignment.date is not None)
        self.dated.toggled.connect(self.date.setEnabled)
        self.date.setEnabled(self.dated.isChecked())
        date_row = QHBoxLayout()
        date_row.addWidget(self.dated)
        date_row.addWidget(self.date, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(bool(self.title.text().strip()))
        self.title.textChanged.connect(lambda text: ok_button.setEnabled(bool(text.strip())))

        layout = QFormLayout(self)
        layout.addRow("Title*", self.title)
        layout.addRow("Category", self.category)
        layout.addRow("Maximum score", self.max_score)
        layout.addRow("Date", date_row)
        layout.addRow(buttons)

    def accept(self) -> None:
        values = {
            "title": self.title.text(),
            "category_id": self.category.currentData(),
            "max_score": self.max_score.value(),
            "date": self.date.date().toPython() if self.dated.isChecked() else None,
        }
        if values["category_id"] is None:
            QMessageBox.warning(self, self.windowTitle(), "Add a category under Categories… first.")
            return
        assignment = replace(self._original, **values) if self._original else Assignment(self._subject_id, **values)
        try:
            self.saved = self._save(assignment)
        except GradebookError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
