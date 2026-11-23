from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.models import Student
from app.services.export import roster_tsv, write_roster_csv
from app.services.roster import RosterError, RosterService, number_key
from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog
from app.ui.files import ask_save_path
from app.ui.dialogs.student_dialog import StudentDialog

_Index = QModelIndex | QPersistentModelIndex
NUMBERED_LISTED = 15  # students named after numbering; a longer list wouldn't fit on screen


class StudentTableModel(QAbstractTableModel):
    COLUMNS = ("Student #", "Last name", "First name", "Status", "Notes")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._students: list[Student] = []

    def set_students(self, students: list[Student]) -> None:
        self.beginResetModel()
        self._students = students
        self.endResetModel()

    def student_at(self, row: int) -> Student:
        return self._students[row]

    def row_of(self, student_id: int) -> int | None:
        for row, student in enumerate(self._students):
            if student.id == student_id:
                return row
        return None

    def rowCount(self, parent: _Index = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._students)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        student = self._students[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self.text(student, column)
        if role == Qt.ItemDataRole.ToolTipRole and column == 4 and student.notes:
            return student.notes
        if role == Qt.ItemDataRole.ForegroundRole and not student.active:
            # Grey out inactive students using the theme's placeholder colour.
            return QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
        return None

    @staticmethod
    def text(student: Student, column: int) -> str:
        """What column `column` shows for `student`."""
        if column == 0:
            return student.student_no or ""
        if column == 1:
            return student.last_name
        if column == 2:
            return student.first_name
        if column == 3:
            return "Active" if student.active else "Inactive"
        return student.notes.splitlines()[0] if student.notes else ""

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None


def sort_key(student: Student, column: int) -> tuple:
    """How the table sorts `student` by `column`: numbers as people read them ("S2"
    before "S10", students without one after the rest), everything else as text."""
    if column == 0:
        return number_key(student), student.last_name.casefold(), student.first_name.casefold()
    return (StudentTableModel.text(student, column).casefold(),)


class StudentSortModel(QSortFilterProxyModel):
    def lessThan(self, left: _Index, right: _Index) -> bool:
        model = self.sourceModel()
        column = left.column()
        return sort_key(model.student_at(left.row()), column) < sort_key(model.student_at(right.row()), column)


class RosterView(QWidget):
    """Student list for the selected class: search, add, edit, (de)activate."""

    create_class_requested = Signal()
    students_changed = Signal()  # a student was added, edited, deactivated or reactivated
    history_requested = Signal(int)  # a student whose attendance history to show

    def __init__(self, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.roster = roster
        self.class_id: int | None = None

        # --- toolbar ---
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, student number or notes  (Ctrl+F, Esc clears)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.installEventFilter(self)  # Escape clears it
        self.show_inactive = QCheckBox("Show inactive")
        self.show_inactive.toggled.connect(self.refresh)
        self.add_button = QPushButton("Add student")
        self.add_button.clicked.connect(self.add_student)
        self.paste_button = QPushButton("Paste list…")
        self.paste_button.setToolTip("Add many students at once, e.g. copied from a spreadsheet (Ctrl+V)")
        self.paste_button.clicked.connect(lambda: self.paste_students())
        self.edit_button = QPushButton("Edit…")
        self.edit_button.clicked.connect(self.edit_selected)
        self.toggle_active_button = QPushButton("Deactivate")
        self.toggle_active_button.clicked.connect(self.toggle_active_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setToolTip("Delete a student added by mistake; only while nothing is recorded for them")
        self.delete_button.clicked.connect(self.delete_selected)
        self.transfer_button = QPushButton("Move to class…")
        self.transfer_button.setToolTip("Move the selected student to another class")
        self.transfer_button.clicked.connect(self.transfer_selected)
        self.history_button = QPushButton("Attendance…")
        self.history_button.setToolTip("Show the selected student's attendance history")
        self.history_button.clicked.connect(self._show_history)
        self.copy_button = QPushButton("Copy list")
        self.copy_button.setToolTip("Copy the students shown, to paste into a spreadsheet (Ctrl+C)")
        self.copy_button.clicked.connect(self.copy_list)
        self.number_button = QPushButton("Number students…")
        self.number_button.setToolTip("Give the students without a student number the next free numbers")
        self.number_button.clicked.connect(self.number_students)
        self.number_button.hide()  # until a class has students without a number
        self.export_button = QPushButton("Export…")
        self.export_button.setToolTip("Save the class list as a CSV file for Excel or other programs")
        self.export_button.clicked.connect(self.export_csv)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search, stretch=1)
        toolbar.addWidget(self.show_inactive)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.paste_button)
        toolbar.addWidget(self.number_button)

        # --- table ---
        self.model = StudentTableModel(self)
        self.proxy = StudentSortModel(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_menu)
        self.table.selectionModel().selectionChanged.connect(self._update_buttons)

        self.count_label = QLabel()
        # Actions on the selected student sit under the table, leaving room to search.
        footer = QHBoxLayout()
        footer.addWidget(self.count_label, stretch=1)
        footer.addWidget(self.edit_button)
        footer.addWidget(self.history_button)
        footer.addWidget(self.toggle_active_button)
        footer.addWidget(self.transfer_button)
        footer.addWidget(self.delete_button)
        footer.addSpacing(12)
        footer.addWidget(self.copy_button)
        footer.addWidget(self.export_button)

        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addLayout(toolbar)
        table_layout.addWidget(self.table)
        table_layout.addLayout(footer)

        # --- empty state (no class yet) ---
        empty_page = QWidget()
        empty_label = QLabel("<h2>No class selected</h2><p>Create a class to start your roster.</p>")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        create_button = QPushButton("Create a class…")
        create_button.clicked.connect(self.create_class_requested)
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.addStretch()
        empty_layout.addWidget(empty_label)
        empty_layout.addWidget(create_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()

        self.pages = QStackedWidget()
        self.pages.addWidget(empty_page)
        self.pages.addWidget(table_page)
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)

        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.search.setFocus)
        QShortcut(QKeySequence.StandardKey.New, self, activated=self.add_student)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self.table, activated=self.edit_selected)
        rename = QShortcut(QKeySequence(Qt.Key.Key_F2), self.table, activated=self.edit_selected)
        rename.setContext(Qt.ShortcutContext.WidgetShortcut)  # F2 edits, as in a file manager
        copy = QShortcut(QKeySequence.StandardKey.Copy, self.table, activated=self.copy_list)
        copy.setContext(Qt.ShortcutContext.WidgetShortcut)
        paste = QShortcut(QKeySequence.StandardKey.Paste, self.table, activated=self.paste_clipboard)
        paste.setContext(Qt.ShortcutContext.WidgetShortcut)
        remove = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table, activated=self.remove_selected)
        remove.setContext(Qt.ShortcutContext.WidgetShortcut)

        self._update_buttons()

    # --- page protocol -----------------------------------------------------

    def set_class(self, class_id: int | None) -> None:
        self.class_id = class_id
        self.search.clear()
        self.pages.setCurrentIndex(0 if class_id is None else 1)
        self.refresh()

    def refresh(self) -> None:
        if self.class_id is None:
            self.model.set_students([])
        else:
            selected = self._selected_student()
            students = self.roster.list_students(
                self.class_id, self.search.text(), self.show_inactive.isChecked()
            )
            self.model.set_students(students)
            # Some schools don't number students: no empty column then.
            everyone = self.roster.list_students(self.class_id, include_inactive=True)
            self.table.setColumnHidden(0, not any(s.student_no for s in everyone))
            if selected:
                self._select(selected.id)
            self._update_count()
        self._update_buttons()

    # --- actions -------------------------------------------------------------

    def add_student(self) -> None:
        if self.class_id is None:
            return
        class_id = self.class_id
        dialog = StudentDialog(
            self.roster.save_student,
            self.class_id,
            parent=self,
            same_name=self.roster.same_name_students,
            suggest_no=lambda: self.roster.suggest_student_no(class_id),
            class_name=school_class.display_name if (school_class := self.roster.get_class(class_id)) else "",
        )
        dialog.exec()
        if dialog.added:  # also when cancelled after "Save and add another"
            self.search.clear()  # make sure the new students are visible
            self.refresh()
            self._select(dialog.added[-1].id)
            self.students_changed.emit()

    def paste_students(self, text: str = "") -> None:
        if self.class_id is None:
            return
        dialog = PasteStudentsDialog(self.roster, self.class_id, parent=self, text=text)
        if dialog.exec() and dialog.added:
            self.search.clear()
            self.refresh()
            self._select(dialog.added[0].id)
            self.students_changed.emit()

    def paste_clipboard(self) -> None:
        """Ctrl+V on the list: add the students copied, e.g. from a spreadsheet, after a preview."""
        self.paste_students(QApplication.clipboard().text())

    def edit_selected(self) -> None:
        student = self._selected_student()
        if student is None or self.class_id is None:
            return
        dialog = StudentDialog(
            self.roster.save_student,
            self.class_id,
            student,
            parent=self,
            same_name=self.roster.same_name_students,
            suggest_no=lambda: self.roster.suggest_student_no(student.class_id),
        )
        if dialog.exec():
            self.refresh()
            self.students_changed.emit()

    def toggle_active_selected(self) -> None:
        student = self._selected_student()
        if student is None:
            return
        if student.active:
            answer = QMessageBox.question(
                self,
                "Deactivate student",
                f"Deactivate {student.full_name}?\n\n"
                "They will be hidden from attendance, grades and seating, but all of "
                "their records are kept. You can reactivate them later via "
                "\"Show inactive\".",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            row = self._selected_row()
            self.roster.deactivate_student(student.id)
        else:
            row = None
            self.roster.reactivate_student(student.id)
        self.refresh()
        if row is not None and self._selected_student() is None:  # hidden now
            self._select_row_near(row)
        self.students_changed.emit()

    def delete_selected(self) -> None:
        student = self._selected_student()
        if student is None:
            return
        answer = QMessageBox.question(
            self, "Delete student", f"Delete {student.full_name}?\n\nThis can't be undone."
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        row = self._selected_row()
        try:
            self.roster.delete_student(student.id)
        except RosterError as exc:
            QMessageBox.information(self, "Delete student", str(exc))
            return
        self.refresh()
        self._select_row_near(row)
        self.students_changed.emit()

    def remove_selected(self) -> None:
        """The Delete key: delete a student added by mistake; one with records can only
        be deactivated, so offer that instead (both ask first)."""
        student = self._selected_student()
        if student is None:
            return
        if self.roster.can_delete_student(student.id):
            self.delete_selected()
        elif student.active:
            self.toggle_active_selected()

    def transfer_selected(self) -> None:
        student = self._selected_student()
        if student is None:
            return
        # Newest school year first, so this year's classes are at the top.
        order = {term: i for i, term in enumerate(self.roster.list_terms())}
        targets = sorted(
            (c for c in self.roster.list_classes() if c.id != student.class_id),
            key=lambda c: order.get(c.term, len(order)),
        )
        if not targets:
            QMessageBox.information(self, "Move to class", "There is no other class to move to yet.")
            return
        names = [c.display_name for c in targets]
        name, ok = QInputDialog.getItem(
            self, "Move to class", f"Move {student.full_name} to:", names, 0, False
        )
        if not ok:
            return
        target = targets[names.index(name)]
        try:
            moved = self.roster.transfer_student(student.id, target.id)
        except RosterError as exc:
            QMessageBox.warning(self, "Move to class", str(exc))
            return
        details = []
        if moved.id != student.id:
            details.append(
                "Their attendance and grades so far stay with this class, where they are "
                "now listed as inactive."
            )
        if student.student_no and moved.student_no != student.student_no:
            details.append(
                f"Student number {student.student_no} is already used in {target.name}, "
                + (f"so they are {moved.student_no} there." if moved.student_no else "so they have no number there yet.")
            )
        QMessageBox.information(
            self,
            "Move to class",
            f"{student.full_name} is now in {target.display_name}." + "".join(f"\n\n{d}" for d in details),
        )
        self.refresh()
        self.students_changed.emit()

    def number_students(self) -> None:
        """Give every active student without a number one, counting up from a number
        the teacher picks (the next free one to start with)."""
        if self.class_id is None:
            return
        missing = self.roster.unnumbered_students(self.class_id)
        if not missing:
            return
        noun = "student" if len(missing) == 1 else f"{len(missing)} students"
        first, ok = QInputDialog.getText(
            self,
            "Number students",
            f"Give the {noun} without a student number numbers, in name order, starting at:",
            text=self.roster.suggest_student_no(self.class_id),
        )
        if not ok:
            return
        try:
            numbered = self.roster.number_students(self.class_id, first)
        except RosterError as exc:
            QMessageBox.warning(self, "Number students", str(exc))
            return
        self.refresh()
        self.students_changed.emit()
        lines = [f"{s.student_no}  {s.full_name}" for s in numbered[:NUMBERED_LISTED]]
        if len(numbered) > NUMBERED_LISTED:
            lines.append(f"and {len(numbered) - NUMBERED_LISTED} more")
        QMessageBox.information(self, "Number students", "New student numbers:\n\n" + "\n".join(lines))

    def copy_list(self) -> None:
        """Put the students shown, in the order shown, on the clipboard as a table."""
        students = [
            self.model.student_at(self.proxy.mapToSource(self.proxy.index(row, 0)).row())
            for row in range(self.proxy.rowCount())
        ]
        if not students:
            return
        QApplication.clipboard().setText(roster_tsv(students))
        noun = "student" if len(students) == 1 else "students"
        self.count_label.setText(f"Copied {len(students)} {noun} · paste them into a spreadsheet")

    def export_csv(self) -> None:
        """Save every student of the class (inactive ones too if they are shown) as CSV,
        in the order of the table."""
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if school_class is None:
            return
        path = ask_save_path(self, "Export students", f"{school_class.display_name} students", "CSV files", ".csv")
        if path is None:
            return
        students = self._in_table_order(
            self.roster.list_students(school_class.id, include_inactive=self.show_inactive.isChecked())
        )
        try:
            write_roster_csv(path, students)
        except OSError as exc:
            QMessageBox.warning(self, "Export students", f"The file could not be saved:\n{exc}")
            return
        QMessageBox.information(self, "Export students", f"Saved {len(students)} students to\n{path}")

    def _show_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        self.table.selectRow(index.row())
        menu = self.student_menu()
        if menu is not None:
            menu.exec(self.table.viewport().mapToGlobal(pos))
            menu.deleteLater()  # a new one is made for each right-click

    def student_menu(self) -> QMenu | None:
        """What can be done for the selected student, for a right-click on their row."""
        student = self._selected_student()
        if student is None:
            return None
        menu = QMenu(self)
        menu.addAction("Edit…\tF2", self.edit_selected)
        menu.addAction("Attendance history…", self._show_history)
        menu.addSeparator()
        menu.addAction("Reactivate" if not student.active else "Deactivate…", self.toggle_active_selected)
        menu.addAction("Move to class…", self.transfer_selected)
        delete = menu.addAction("Delete…\tDelete", self.delete_selected)
        delete.setEnabled(self.delete_button.isEnabled())
        menu.addSeparator()
        menu.addAction("Copy the list\tCtrl+C", self.copy_list)
        return menu

    # --- keyboard ------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.search
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and self.search.text()
        ):
            self.search.clear()
            return True
        return super().eventFilter(watched, event)

    # --- helpers -------------------------------------------------------------

    def _show_history(self) -> None:
        if (student := self._selected_student()) is not None:
            self.history_requested.emit(student.id)

    def _selected_student(self) -> Student | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.student_at(self.proxy.mapToSource(rows[0]).row())

    def _in_table_order(self, students: list[Student]) -> list[Student]:
        """`students` sorted the way the table is, by the column header clicked last."""
        column, order = self.proxy.sortColumn(), self.proxy.sortOrder()
        if column < 0:
            return students
        # Python's sort is stable, like the table's, so ties keep the name order.
        return sorted(
            students,
            key=lambda s: sort_key(s, column),
            reverse=order == Qt.SortOrder.DescendingOrder,
        )

    def _selected_row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _select_row_near(self, row: int | None) -> None:
        """Select the student now at table row `row`, or the last one: after a student
        left the list, the next one is ready for the Delete key."""
        if row is None or self.proxy.rowCount() == 0:
            return
        row = min(row, self.proxy.rowCount() - 1)
        self.table.selectRow(row)
        self.table.scrollTo(self.proxy.index(row, 0))
        self._update_buttons()

    def _select(self, student_id: int | None) -> None:
        row = self.model.row_of(student_id) if student_id is not None else None
        if row is None:
            return
        index = self.proxy.mapFromSource(self.model.index(row, 0))
        self.table.selectRow(index.row())
        self.table.scrollTo(index)

    def _update_buttons(self) -> None:
        student = self._selected_student()
        has_class = self.class_id is not None
        self.add_button.setEnabled(has_class)
        self.paste_button.setEnabled(has_class)
        self.export_button.setEnabled(has_class)
        self.copy_button.setEnabled(has_class and self.model.rowCount() > 0)
        self.edit_button.setEnabled(student is not None)
        self.history_button.setEnabled(student is not None)
        self.toggle_active_button.setEnabled(student is not None)
        self.transfer_button.setEnabled(student is not None)
        self.delete_button.setEnabled(student is not None and self.roster.can_delete_student(student.id))
        self.toggle_active_button.setText(
            "Reactivate" if student is not None and not student.active else "Deactivate"
        )

    def _update_count(self) -> None:
        shown = self.model.rowCount()
        noun = "student" if shown == 1 else "students"
        text = f"{shown} {noun}"
        if self.search.text().strip():
            text += " matches your search" if shown == 1 else " match your search"
        if not self.show_inactive.isChecked() and self.class_id is not None:
            hidden = len(self.roster.list_students(self.class_id, self.search.text(), True)) - shown
            if hidden:
                text += f" · {hidden} inactive hidden"
        else:
            inactive = sum(1 for row in range(shown) if not self.model.student_at(row).active)
            if inactive:
                text += f" · {inactive} inactive"
        self.count_label.setText(text)
        self._update_number_button()

    def _update_number_button(self) -> None:
        """Offer to number the students without one, when the class uses numbers (some schools don't)."""
        missing = len(self.roster.unnumbered_students(self.class_id)) if self.class_id is not None else 0
        offer = bool(missing and self.roster.suggest_student_no(self.class_id))
        self.number_button.setVisible(offer)
        if offer:
            self.number_button.setText(f"Number {missing} student{'' if missing == 1 else 's'}…")
