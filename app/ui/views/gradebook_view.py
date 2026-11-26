"""The gradebook of the current subject: students down the side, assignments across."""

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.gradebook import (
    PASS_MARK,
    SUGGESTED_CATEGORIES,
    GradebookError,
    GradebookService,
    GradeSheet,
    format_number,
    next_title,
)
from app.services.dashboard import letter_grade
from app.services.export import write_gradebook_csv
from app.services.roster import RosterService, matches
from app.ui import style
from app.ui.dialogs.assignment_dialog import AssignmentDialog
from app.ui.dialogs.categories_dialog import CategoriesDialog
from app.ui.files import ask_save_path


ASSIGNMENT_ID = Qt.ItemDataRole.UserRole  # on header items
STUDENT_ID = Qt.ItemDataRole.UserRole  # on name items
EXEMPT_TEXT = "ex"
UNDO_LIMIT = 50


def percent_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}%"


class ScoreTable(QTableWidget):
    """Scores are typed down a column, one student after the other: Enter saves and goes
    to the next student, as in a spreadsheet."""

    def closeEditor(self, editor: QWidget, hint: QAbstractItemDelegate.EndEditHint) -> None:
        super().closeEditor(editor, hint)
        if hint == QAbstractItemDelegate.EndEditHint.SubmitModelCache:  # Enter, not Tab or Escape
            self._next_row()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.state() != self.State.EditingState:
            self._next_row()
            return
        super().keyPressEvent(event)

    def _next_row(self) -> None:
        """Go down to the next student shown, skipping those Find hides."""
        row, col = self.currentRow(), self.currentColumn()
        if row < 0:
            return
        for below in range(row + 1, self.rowCount()):
            if not self.isRowHidden(below):
                self.setCurrentCell(below, col)
                return


class GradebookView(QWidget):
    manage_subjects_requested = Signal()  # the class has no subject to grade yet

    def __init__(self, grades: GradebookService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.grades = grades
        self.roster = roster
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self.sheet: GradeSheet | None = None
        self.pass_mark = PASS_MARK
        self.by_average = False  # students listed best average first instead of by name
        # Each change is a list of (assignment id, student id, text before, text after).
        self._undo: list[list[tuple[int, int, str, str]]] = []
        self._redo: list[list[tuple[int, int, str, str]]] = []

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
        self.export_button = QPushButton("E&xport…")
        self.export_button.setToolTip("Save the scores, category percents and averages as a CSV file")
        self.export_button.clicked.connect(self.export_csv)
        header.addWidget(self.export_button, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.categories_button, alignment=Qt.AlignmentFlag.AlignBottom)
        self.new_button = QPushButton("&New assignment")
        self.new_button.setObjectName("Primary")
        self.new_button.setToolTip("Add a column for a test, quiz or piece of homework (Ctrl+N)")
        self.new_button.clicked.connect(self.new_assignment)
        header.addWidget(self.new_button, alignment=Qt.AlignmentFlag.AlignBottom)

        self.summary = style.label("", 0.95, muted=True)
        self.category_filter = QComboBox()
        self.category_filter.setToolTip("Show the assignments of one category only")
        self.category_filter.currentIndexChanged.connect(lambda _i: self._apply_filter())
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a student (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(240)
        self.search.textChanged.connect(lambda _t: self._apply_search())
        summary_row = QHBoxLayout()
        summary_row.addWidget(self.summary, stretch=1)
        summary_row.addWidget(self.search)
        summary_row.addWidget(self.category_filter)
        self.table = ScoreTable()
        triggers = QAbstractItemView.EditTrigger
        self.table.setEditTriggers(triggers.DoubleClicked | triggers.EditKeyPressed | triggers.AnyKeyPressed)
        self.table.itemChanged.connect(self._score_typed)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.horizontalHeader().sectionDoubleClicked.connect(self._header_double_clicked)
        self.table.horizontalHeader().sectionClicked.connect(self._header_clicked)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self._show_header_menu)
        self.sheet_page = QWidget()
        sheet_layout = QVBoxLayout(self.sheet_page)
        sheet_layout.setContentsMargins(0, 0, 0, 0)
        sheet_layout.addLayout(summary_row)
        sheet_layout.addWidget(self.table, stretch=1)
        self.keys_hint = style.label(
            "Type a score: points, a percentage (85%) or ex for exempt · Enter goes to the next student · "
            "Delete clears · Ctrl+V pastes scores from a spreadsheet · Ctrl+Z undoes · "
            "double-click a column header to edit it, right-click for more · F1 lists every key",
            0.85,
            muted=True,
        )
        self.keys_hint.setWordWrap(True)
        sheet_layout.addWidget(self.keys_hint)

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
        for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            clear = QShortcut(QKeySequence(key), self.table)
            clear.setContext(Qt.ShortcutContext.WidgetShortcut)  # not while a score is being typed
            clear.activated.connect(self.clear_selected)
        paste = QShortcut(QKeySequence.StandardKey.Paste, self.table)
        paste.setContext(Qt.ShortcutContext.WidgetShortcut)
        paste.activated.connect(lambda: self.paste_scores(QApplication.clipboard().text()))
        copy = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        copy.setContext(Qt.ShortcutContext.WidgetShortcut)
        copy.activated.connect(lambda: QApplication.clipboard().setText(self.selection_text()))
        undo = QShortcut(QKeySequence.StandardKey.Undo, self)  # a score being typed keeps its own undo
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self.undo)
        for keys in ("Ctrl+Y", "Ctrl+Shift+Z"):  # named: on Windows StandardKey.Redo is Ctrl+Y too
            redo = QShortcut(QKeySequence(keys), self)
            redo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            redo.activated.connect(self.redo)
        find = QShortcut(QKeySequence.StandardKey.Find, self)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        new = QShortcut(QKeySequence.StandardKey.New, self)
        new.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        new.activated.connect(lambda: self.new_button.isEnabled() and self.new_assignment())
        self.refresh()

    # --- page protocol ---------------------------------------------------------

    def set_class(self, class_id: int | None) -> None:
        self.class_id = class_id
        self.subject_id = None  # MainWindow picks the subject next
        self.clear_undo()

    def set_subject(self, subject_id: int | None) -> None:
        if subject_id != self.subject_id:
            self.clear_undo()
        self.subject_id = subject_id
        self.refresh()

    def showEvent(self, event) -> None:
        # Students may have been added, moved or deactivated on other pages meanwhile.
        super().showEvent(event)
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
        self.export_button.setEnabled(self.sheet is not None and bool(self.sheet.assignments))
        self.new_button.setEnabled(self.sheet is not None and bool(self.sheet.categories))
        self._show_state()

    def export_csv(self) -> None:
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if self.sheet is None or school_class is None:
            return
        name = f"{school_class.display_name} {self.sheet.subject.name} grades"
        path = ask_save_path(self, "Export grades", name, "CSV files", ".csv")
        if path is None:
            return
        try:
            write_gradebook_csv(path, self.sheet)
        except OSError as exc:
            QMessageBox.warning(self, "Export grades", f"The file could not be saved:\n{exc}")
            return
        n = len(self.sheet.students)
        QMessageBox.information(self, "Export grades", f"Saved the grades of {n} student{'' if n == 1 else 's'} to\n{path}")

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
            default_title=next_title(latest.title, [a.title for a in self.sheet.assignments]) if latest else "",
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
            saved = dialog.saved or assignment
            above = [s for s in self.sheet.students if (self.sheet.score(assignment_id, s.id) or 0) > saved.max_score]
            if saved.max_score < assignment.max_score and above:
                n = len(above)
                QMessageBox.information(
                    self, "Edit assignment",
                    f"{n} score{'' if n == 1 else 's'} {'is' if n == 1 else 'are'} now above the maximum of "
                    f"{format_number(saved.max_score)} and count{'s' if n == 1 else ''} as bonus points.",
                )  # fmt: skip

    def delete_assignment(self, assignment_id: int) -> None:
        """Delete an assignment with its scores, after asking."""
        assignment = self.grades.get_assignment(assignment_id)
        if assignment is None:
            return
        n = self.grades.score_count(assignment_id)
        scores = f" with its {n} score{'' if n == 1 else 's'}" if n else ""
        answer = QMessageBox.question(
            self, "Delete assignment", f"Delete {assignment.title}{scores}?\n\nThis can't be undone."
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.grades.delete_assignment(assignment_id)
            self.refresh()

    def fill_empty(self, assignment_id: int, text: str) -> int:
        """Give every student without a score for the assignment `text`; returns how many."""
        empty = [s.id for s in self.sheet.students if not self.sheet.is_entered(assignment_id, s.id)]
        before = [(assignment_id, s, "") for s in empty]
        try:
            self.grades.enter_scores([(assignment_id, s, text) for s in empty])
        except GradebookError as exc:
            QMessageBox.warning(self, "Fill empty cells", str(exc))
            return 0
        self.refresh()
        self._remember(before)
        return len(empty)

    def ask_fill_empty(self, assignment_id: int) -> None:
        assignment = self.grades.get_assignment(assignment_id)
        if assignment is None or self.sheet is None:
            return
        n = len(self.sheet.students) - self.sheet.entered(assignment_id)
        text, ok = QInputDialog.getText(
            self, "Fill empty cells",
            f"Score for the {n} student{'' if n == 1 else 's'} without one in {assignment.title} "
            f"(out of {format_number(assignment.max_score)}; ex for exempt, 0 for work not handed in):",
            text=format_number(assignment.max_score),
        )  # fmt: skip
        if ok and text.strip():
            self.fill_empty(assignment_id, text)

    def header_menu(self, column: int) -> QMenu | None:
        """What can be done with the assignment in `column`; None for other columns."""
        assignment_id = self.assignment_at(column)
        if assignment_id is None:
            return None
        menu = QMenu(self)
        menu.addAction("&Edit…", lambda: self.edit_assignment(assignment_id))
        fill = menu.addAction("&Fill empty cells…", lambda: self.ask_fill_empty(assignment_id))
        fill.setEnabled(self.sheet.entered(assignment_id) < len(self.sheet.students))
        menu.addAction("&Delete…", lambda: self.delete_assignment(assignment_id))
        return menu

    def _show_header_menu(self, pos) -> None:
        head = self.table.horizontalHeader()
        if menu := self.header_menu(head.logicalIndexAt(pos)):
            menu.exec(head.mapToGlobal(pos))

    def _header_double_clicked(self, column: int) -> None:
        if (assignment_id := self.assignment_at(column)) is not None:
            self.edit_assignment(assignment_id)

    def go_to_assignment(self, assignment_id: int) -> None:
        """Select the first student's cell of the assignment, ready to type."""
        for col in range(1, self.average_column()):
            if self.assignment_at(col) == assignment_id:
                if self.table.isColumnHidden(col):  # another category is shown
                    self.category_filter.setCurrentIndex(0)
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

    def students_shown(self) -> list:
        """The sheet's students in the order chosen: by name, or best average first."""
        if not self.by_average:
            return list(self.sheet.students)
        averages = {s.id: self.sheet.average(s.id) for s in self.sheet.students}
        return sorted(self.sheet.students, key=lambda s: (averages[s.id] is None, -(averages[s.id] or 0)))

    def set_order(self, by_average: bool) -> None:
        self.by_average = by_average
        if self.sheet is not None and self.sheet.categories:
            self._fill_table()

    def _header_clicked(self, column: int) -> None:
        if column == 0:
            self.set_order(by_average=False)
        elif column == self.average_column():
            self.set_order(by_average=True)

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
            item.setToolTip(self._assignment_tip(assignment))
            table.setHorizontalHeaderItem(col, item)
        table.setHorizontalHeaderItem(self.average_column(), QTableWidgetItem("Average"))
        for row, student in enumerate(self.students_shown()):
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
        head.setSortIndicatorShown(True)
        head.setSortIndicator(
            self.average_column() if self.by_average else 0,
            Qt.SortOrder.DescendingOrder if self.by_average else Qt.SortOrder.AscendingOrder,
        )
        del blocker
        self._fill_filter()
        self._apply_search()
        self.summary.setText(self._summary_text())

    def _fill_filter(self) -> None:
        """List the categories to filter by, keeping the one chosen if it's still there."""
        chosen = self.category_filter.currentData()
        with QSignalBlocker(self.category_filter):
            self.category_filter.clear()
            self.category_filter.addItem("All categories", None)
            for category in self.sheet.categories:
                self.category_filter.addItem(category.name, category.id)
            self.category_filter.setCurrentIndex(max(0, self.category_filter.findData(chosen)))
        self._apply_filter()

    def _apply_search(self) -> None:
        """Hide the students whose name or number doesn't match what is typed in Find."""
        if self.sheet is None:
            return
        text = self.search.text()
        for row, student in enumerate(self.students_shown()):
            self.table.setRowHidden(row, not matches(student, text))

    def _apply_filter(self) -> None:
        chosen = self.category_filter.currentData()
        for col, assignment in enumerate(self.sheet.assignments if self.sheet else [], start=1):
            self.table.setColumnHidden(col, chosen is not None and assignment.category_id != chosen)

    def _score_text(self, assignment_id: int, student_id: int) -> str:
        sheet = self.sheet
        if not sheet.is_entered(assignment_id, student_id):
            return ""
        if (score := sheet.score(assignment_id, student_id)) is None:
            return EXEMPT_TEXT
        return format_number(score)

    def _score_item(self, assignment_id: int, student_id: int) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._show_score(item, assignment_id, student_id)
        return item

    def _show_score(self, item: QTableWidgetItem, assignment_id: int, student_id: int) -> None:
        """The score, with points above the maximum shown as a bonus."""
        item.setText(self._score_text(assignment_id, student_id))
        score = self.sheet.score(assignment_id, student_id)
        maximum = next(a.max_score for a in self.sheet.assignments if a.id == assignment_id)
        if score is not None and score > maximum:
            item.setForeground(style.color(self, "info"))
            item.setToolTip(f"{format_number(score - maximum)} bonus points above the maximum of {format_number(maximum)}")
        else:
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
            item.setToolTip("Exempt: left out of the average" if self.sheet.is_entered(assignment_id, student_id)
                            and score is None else "")  # fmt: skip

    def _assignment_tip(self, assignment) -> str:
        """e.g. "Tests · 3 Oct 2026 · out of 20 / Class average 72% · 24 of 25 scores entered"."""
        sheet = self.sheet
        category = next((c.name for c in sheet.categories if c.id == assignment.category_id), "")
        first = [category]
        if assignment.date:
            first.append(f"{assignment.date.day} {assignment.date:%b %Y}")
        first.append(f"out of {format_number(assignment.max_score)}")
        second = []
        if (average := sheet.assignment_average(assignment.id)) is not None:
            second.append(f"Class average {percent_text(average)}")
        second.append(f"{sheet.entered(assignment.id)} of {len(sheet.students)} scores entered")
        return " · ".join(first) + "\n" + " · ".join(second) + "\nDouble-click to edit, right-click for more"

    def _average_item(self, student_id: int) -> QTableWidgetItem:
        item = QTableWidgetItem()
        self._show_average(item, student_id)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

    def _show_average(self, item: QTableWidgetItem, student_id: int) -> None:
        """The student's average, in the danger colour under the pass mark."""
        average = self.sheet.average(student_id)
        item.setText("—" if average is None else f"{percent_text(average)} {letter_grade(average)}")
        percents = self.sheet.category_percents(student_id)
        lines = [
            f"{c.name} (weight {format_number(c.weight)}): {percent_text(percents.get(c.id))}"
            for c in self.sheet.categories
        ]
        if average is not None and average < self.pass_mark:
            item.setForeground(style.color(self, "danger"))
            lines.insert(0, f"Under the pass mark of {format_number(self.pass_mark)}%")
        else:
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
        item.setToolTip("\n".join(lines) if percents else "Nothing scored yet")

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
        before = self._score_text(assignment_id, student_id)
        try:
            self.grades.enter_score(assignment_id, student_id, item.text())
        except GradebookError as exc:
            QMessageBox.warning(self, "Gradebook", str(exc))
        self._update_row(item.row())
        self._remember([(assignment_id, student_id, before)])

    def selected_cells(self) -> list[tuple[int, int, int, int]]:
        """(row, column, assignment id, student id) of every selected score cell."""
        cells = []
        for item in self.table.selectedItems():
            assignment_id, student_id = self.assignment_at(item.column()), self.student_at(item.row())
            if assignment_id is not None and student_id is not None:
                cells.append((item.row(), item.column(), assignment_id, student_id))
        return cells

    def clear_selected(self) -> None:
        """Forget the selected scores (Delete)."""
        cells = [c for c in self.selected_cells() if self.table.item(c[0], c[1]).text()]
        if not cells:
            return
        before = [(a, s, self._score_text(a, s)) for _r, _c, a, s in cells]
        self.grades.enter_scores([(a, s, "") for _r, _c, a, s in cells])
        for row in sorted({c[0] for c in cells}):
            self._update_row(row)
        self._remember(before)

    def selection_text(self) -> str:
        """The selected cells as tab-separated lines for a spreadsheet. With the names in
        the selection, a first line gives the column titles. Students hidden by Find and
        assignments of other categories are left out, as on screen."""
        ranges = self.table.selectedRanges()
        if not ranges:
            return ""
        top = min(r.topRow() for r in ranges)
        bottom = max(r.bottomRow() for r in ranges)
        left = min(r.leftColumn() for r in ranges)
        right = max(r.rightColumn() for r in ranges)
        columns = [c for c in range(left, right + 1) if not self.table.isColumnHidden(c)]
        lines = []
        if left == 0:
            titles = []
            for c in columns:
                if (assignment_id := self.assignment_at(c)) is not None:
                    titles.append(self.grades.get_assignment(assignment_id).title)
                else:
                    titles.append(self.table.horizontalHeaderItem(c).text())
            lines.append("\t".join(titles))
        for row in range(top, bottom + 1):
            if not self.table.isRowHidden(row):
                lines.append("\t".join(self.table.item(row, c).text() for c in columns))
        return "\n".join(lines) + "\n"

    def paste_scores(self, text: str) -> None:
        """Enter a block of scores copied from a spreadsheet (tab-separated, one student per
        line), starting at the current cell. Students hidden by Find and assignments of
        other categories are skipped, as they aren't in the block seen. One value pasted
        over several selected cells goes in each of them, as in a spreadsheet. All or nothing."""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n")
        selected = self.selected_cells()
        if len(lines) == 1 and "\t" not in lines[0] and len(selected) > 1:
            self._enter_pasted([(a, s, lines[0]) for _r, _c, a, s in selected], {r for r, *_ in selected})
            return
        row0, col0 = self.table.currentRow(), self.table.currentColumn()
        if self.assignment_at(col0) is None or row0 < 0:
            QMessageBox.information(self, "Paste scores", "Select the score cell to paste into first.")
            return
        rows = [r for r in range(row0, self.table.rowCount()) if not self.table.isRowHidden(r)]
        columns = [c for c in range(col0, self.average_column()) if not self.table.isColumnHidden(c)]
        entries, cells, left_out = [], set(), 0
        for r, line in enumerate(lines):
            for c, value in enumerate(line.split("\t")):
                if r >= len(rows) or c >= len(columns):
                    left_out += bool(value.strip())
                    continue
                row = rows[r]
                entries.append((self.assignment_at(columns[c]), self.student_at(row), value))
                cells.add(row)
        if self._enter_pasted(entries, cells) and left_out:
            QMessageBox.information(
                self, "Paste scores",
                f"{left_out} value{'' if left_out == 1 else 's'} didn't fit in the gradebook and "
                f"{'was' if left_out == 1 else 'were'} left out. Start the paste further up or left.",
            )  # fmt: skip

    def _enter_pasted(self, entries: list[tuple[int, int, str]], rows: set[int]) -> bool:
        """Enter pasted (assignment id, student id, text) cells, all or none, and show the
        `rows` they are in. False, after saying why, when nothing could be pasted."""
        before = [(a, s, self._score_text(a, s)) for a, s, _text in entries]
        try:
            self.grades.enter_scores(entries)
        except GradebookError as exc:
            QMessageBox.warning(self, "Paste scores", f"Nothing was pasted.\n\n{exc}")
            return False
        for row in sorted(rows):
            self._update_row(row)
        self._remember(before)
        return True

    # --- undo ----------------------------------------------------------------

    def _remember(self, before: list[tuple[int, int, str]]) -> None:
        """Keep a change for Ctrl+Z: each cell's text before it and as now saved."""
        change = [(a, s, old, self._score_text(a, s)) for a, s, old in before]
        change = [c for c in change if c[2] != c[3]]
        if change:
            self._undo = (self._undo + [change])[-UNDO_LIMIT:]
            self._redo.clear()

    def clear_undo(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def undo(self) -> None:
        self._step(self._undo, self._redo, back=True)

    def redo(self) -> None:
        self._step(self._redo, self._undo, back=False)

    def _step(self, source: list, target: list, back: bool) -> None:
        if not source or self.sheet is None:
            return
        change = source.pop()
        try:
            self.grades.enter_scores([(a, s, old if back else new) for a, s, old, new in change])
        except GradebookError as exc:  # e.g. the assignment was deleted since
            QMessageBox.warning(self, "Undo" if back else "Redo", str(exc))
            self.clear_undo()
            return
        target.append(change)
        self.refresh()
        what = "Undid" if back else "Redid"
        n = len(change)
        self.summary.setText(f"{what} {n} score{'' if n == 1 else 's'} · " + self._summary_text())

    def _update_row(self, row: int) -> None:
        """Show a student's scores and average as saved, after a change."""
        self.sheet = self.grades.sheet(self.subject_id)
        student_id = self.student_at(row)
        # Change the texts, not the items: the item being edited mustn't be deleted under Qt.
        with QSignalBlocker(self.table):
            for col, assignment in enumerate(self.sheet.assignments, start=1):
                self._show_score(self.table.item(row, col), assignment.id, student_id)
            self._show_average(self.table.item(row, self.average_column()), student_id)
            for col, assignment in enumerate(self.sheet.assignments, start=1):
                self.table.horizontalHeaderItem(col).setToolTip(self._assignment_tip(assignment))
        self.summary.setText(self._summary_text())

    def _summary_text(self) -> str:
        sheet = self.sheet
        n = len(sheet.assignments)
        parts = [f"{n} assignment{'' if n == 1 else 's'}" if n else "No assignments yet"]
        if (average := sheet.class_average()) is not None:
            parts.append(f"class average {percent_text(average)}")
        return " · ".join(parts)
