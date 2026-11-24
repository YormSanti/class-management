"""The gradebook of the current subject: students down the side, assignments across."""

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.gradebook import (
    SUGGESTED_CATEGORIES,
    GradebookError,
    GradebookService,
    GradeSheet,
    format_number,
)
from app.services.roster import RosterService
from app.ui import style
from app.ui.dialogs.assignment_dialog import AssignmentDialog
from app.ui.dialogs.categories_dialog import CategoriesDialog


ASSIGNMENT_ID = Qt.ItemDataRole.UserRole  # on header items
STUDENT_ID = Qt.ItemDataRole.UserRole  # on name items
EXEMPT_TEXT = "ex"


def percent_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}%"


class GradebookView(QWidget):
    manage_subjects_requested = Signal()  # the class has no subject to grade yet

    def __init__(self, grades: GradebookService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.grades = grades
        self.roster = roster
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self.sheet: GradeSheet | None = None

        self.title = style.label("Gradebook", 1.6, bold=True)
        self.subtitle = style.label("", 0.95, muted=True)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        self.categories_button = QPushButton("&Categories…")
        self.categories_button.setToolTip("The subject's grade categories and how much each counts")
        self.categories_button.clicked.connect(self.edit_categories)
        header = QHBoxLayout()
        header.addLayout(titles, stretch=1)
        header.addWidget(self.categories_button, alignment=Qt.AlignmentFlag.AlignBottom)
        self.new_button = QPushButton("&New assignment")
        self.new_button.setObjectName("Primary")
        self.new_button.setToolTip("Add a column for a test, quiz or piece of homework (Ctrl+N)")
        self.new_button.clicked.connect(self.new_assignment)
        header.addWidget(self.new_button, alignment=Qt.AlignmentFlag.AlignBottom)

        self.summary = style.label("", 0.95, muted=True)
        self.table = QTableWidget()
        triggers = QAbstractItemView.EditTrigger
        self.table.setEditTriggers(triggers.DoubleClicked | triggers.EditKeyPressed | triggers.AnyKeyPressed)
        self.table.itemChanged.connect(self._score_typed)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.horizontalHeader().sectionDoubleClicked.connect(self._header_double_clicked)
        self.sheet_page = QWidget()
        sheet_layout = QVBoxLayout(self.sheet_page)
        sheet_layout.setContentsMargins(0, 0, 0, 0)
        sheet_layout.addWidget(self.summary)
        sheet_layout.addWidget(self.table, stretch=1)

        # --- empty states ---
        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_button = QPushButton()
        self.empty_button.setObjectName("Primary")
        self.empty_button.clicked.connect(self._empty_action)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        empty_layout.addWidget(self.empty_label)
        empty_layout.addWidget(self.empty_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.own_categories_button = QPushButton("Set up my own categories…")
        self.own_categories_button.clicked.connect(self.edit_categories)
        empty_layout.addWidget(self.own_categories_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()

        self.pages = QStackedWidget()
        self.pages.addWidget(empty)
        self.pages.addWidget(self.sheet_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(self.pages, stretch=1)
        self.setStyleSheet(style.card_stylesheet(self))
        new = QShortcut(QKeySequence.StandardKey.New, self)
        new.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        new.activated.connect(lambda: self.new_button.isEnabled() and self.new_assignment())
        self.refresh()

    # --- page protocol ---------------------------------------------------------

    def set_class(self, class_id: int | None) -> None:
        self.class_id = class_id
        self.subject_id = None  # MainWindow picks the subject next

    def set_subject(self, subject_id: int | None) -> None:
        self.subject_id = subject_id
        self.refresh()

    def refresh(self) -> None:
        """Read the current subject's gradebook from the database again."""
        self.sheet = self.grades.sheet(self.subject_id) if self.subject_id is not None else None
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if self.sheet is not None and school_class is not None:
            self.subtitle.setText(f"{self.sheet.subject.name} · {school_class.display_name}")
        else:
            self.subtitle.setText(school_class.display_name if school_class else "")
        self.categories_button.setEnabled(self.sheet is not None)
        self.new_button.setEnabled(self.sheet is not None and bool(self.sheet.categories))
        self._show_state()

    def edit_categories(self) -> None:
        if self.subject_id is None:
            return
        dialog = CategoriesDialog(self.grades, self.subject_id, parent=self)
        dialog.exec()
        if dialog.changed:
            self.refresh()

    def new_assignment(self) -> None:
        """Ask for a new assignment like the latest one, then go to its column to enter scores."""
        if self.sheet is None or not self.sheet.categories:
            return
        latest = self.sheet.assignments[-1] if self.sheet.assignments else None
        dialog = AssignmentDialog(
            self.grades.save_assignment,
            self.sheet.subject.id,
            self.sheet.categories,
            parent=self,
            default_category=latest.category_id if latest else None,
            default_max=latest.max_score if latest else 10,
        )
        if dialog.exec() and dialog.saved:
            self.refresh()
            self.go_to_assignment(dialog.saved.id)

    def edit_assignment(self, assignment_id: int) -> None:
        assignment = self.grades.get_assignment(assignment_id)
        if assignment is None or self.sheet is None:
            return
        dialog = AssignmentDialog(
            self.grades.save_assignment, assignment.subject_id, self.sheet.categories, assignment, parent=self
        )
        if dialog.exec():
            self.refresh()
            self.go_to_assignment(assignment_id)  # its date may have moved it

    def _header_double_clicked(self, column: int) -> None:
        if (assignment_id := self.assignment_at(column)) is not None:
            self.edit_assignment(assignment_id)

    def go_to_assignment(self, assignment_id: int) -> None:
        """Select the first student's cell of the assignment, ready to type."""
        for col in range(1, self.average_column()):
            if self.assignment_at(col) == assignment_id:
                if self.table.rowCount():
                    self.table.setCurrentCell(0, col)
                    self.table.scrollToItem(self.table.item(0, col))
                self.table.setFocus()
                return

    def _show_state(self) -> None:
        if self.class_id is None:
            self._empty("<h2>No class selected</h2><p>Create a class to keep its grades.</p>")
        elif self.sheet is None:
            self._empty(
                "<h2>No subject yet</h2><p>Every subject of a class has its own gradebook. "
                "Add the subjects you teach this class first.</p>",
                "Add a subject",
            )
        elif not self.sheet.categories:
            suggested = ", ".join(f"{name} {weight:.0f}" for name, weight in SUGGESTED_CATEGORIES)
            self._empty(
                f"<h2>How is {self.sheet.subject.name} graded?</h2><p>Assignments are grouped in "
                "categories, and each category counts towards the average by its weight. "
                f"Start with {suggested}, or set up your own.</p>",
                "Use these categories",
            )
            self.own_categories_button.show()
        else:
            self._fill_table()
            self.pages.setCurrentWidget(self.sheet_page)

    def _empty(self, text: str, button: str = "") -> None:
        self.empty_label.setText(text)
        self.empty_button.setText(button)
        self.empty_button.setVisible(bool(button))
        self.own_categories_button.hide()
        self.pages.setCurrentIndex(0)

    def _empty_action(self) -> None:
        if self.class_id is None:
            return
        if self.sheet is None:
            self.manage_subjects_requested.emit()
        elif not self.sheet.categories:
            self.grades.add_categories(self.sheet.subject.id, SUGGESTED_CATEGORIES)
            self.refresh()

    # --- the table -------------------------------------------------------------

    def average_column(self) -> int:
        return 1 + len(self.sheet.assignments) if self.sheet else 1

    def _fill_table(self) -> None:
        sheet = self.sheet
        table = self.table
        blocker = QSignalBlocker(table)  # filling in isn't typing
        table.clear()
        table.setRowCount(len(sheet.students))
        table.setColumnCount(len(sheet.assignments) + 2)
        table.setHorizontalHeaderItem(0, QTableWidgetItem("Student"))
        for col, assignment in enumerate(sheet.assignments, start=1):
            item = QTableWidgetItem(f"{assignment.title}\n/ {format_number(assignment.max_score)}")
            item.setData(ASSIGNMENT_ID, assignment.id)
            table.setHorizontalHeaderItem(col, item)
        table.setHorizontalHeaderItem(self.average_column(), QTableWidgetItem("Average"))
        for row, student in enumerate(sheet.students):
            name = QTableWidgetItem(student.full_name)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name.setData(STUDENT_ID, student.id)
            table.setItem(row, 0, name)
            for col, assignment in enumerate(sheet.assignments, start=1):
                table.setItem(row, col, self._score_item(assignment.id, student.id))
            table.setItem(row, self.average_column(), self._average_item(student.id))
        head = table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        table.resizeColumnToContents(0)
        del blocker
        self.summary.setText(self._summary_text())

    def _score_text(self, assignment_id: int, student_id: int) -> str:
        sheet = self.sheet
        if not sheet.is_entered(assignment_id, student_id):
            return ""
        if (score := sheet.score(assignment_id, student_id)) is None:
            return EXEMPT_TEXT
        return format_number(score)

    def _score_item(self, assignment_id: int, student_id: int) -> QTableWidgetItem:
        item = QTableWidgetItem(self._score_text(assignment_id, student_id))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _average_item(self, student_id: int) -> QTableWidgetItem:
        item = QTableWidgetItem(percent_text(self.sheet.average(student_id)))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

    def assignment_at(self, column: int) -> int | None:
        """The id of the assignment in `column`, None for the name and average columns."""
        item = self.table.horizontalHeaderItem(column)
        return item.data(ASSIGNMENT_ID) if item is not None and 0 < column < self.average_column() else None

    def student_at(self, row: int) -> int | None:
        item = self.table.item(row, 0)
        return item.data(STUDENT_ID) if item is not None else None

    def _score_typed(self, item: QTableWidgetItem) -> None:
        """Save what was typed in a score cell, or say why it can't be and put the old score back."""
        assignment_id, student_id = self.assignment_at(item.column()), self.student_at(item.row())
        if assignment_id is None or student_id is None:
            return
        try:
            self.grades.enter_score(assignment_id, student_id, item.text())
        except GradebookError as exc:
            QMessageBox.warning(self, "Gradebook", str(exc))
        self._update_row(item.row())

    def _update_row(self, row: int) -> None:
        """Show a student's scores and average as saved, after a change."""
        self.sheet = self.grades.sheet(self.subject_id)
        student_id = self.student_at(row)
        # Change the texts, not the items: the item being edited mustn't be deleted under Qt.
        with QSignalBlocker(self.table):
            for col, assignment in enumerate(self.sheet.assignments, start=1):
                self.table.item(row, col).setText(self._score_text(assignment.id, student_id))
            self.table.item(row, self.average_column()).setText(percent_text(self.sheet.average(student_id)))
        self.summary.setText(self._summary_text())

    def _summary_text(self) -> str:
        sheet = self.sheet
        n = len(sheet.assignments)
        parts = [f"{n} assignment{'' if n == 1 else 's'}" if n else "No assignments yet"]
        if (average := sheet.class_average()) is not None:
            parts.append(f"class average {percent_text(average)}")
        return " · ".join(parts)
