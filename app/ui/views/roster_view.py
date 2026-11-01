import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
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
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.models import Student
from app.services.export import write_roster_csv
from app.services.roster import RosterError, RosterService
from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog
from app.ui.dialogs.student_dialog import StudentDialog

_Index = QModelIndex | QPersistentModelIndex


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
            if column == 0:
                return student.student_no or ""
            if column == 1:
                return student.last_name
            if column == 2:
                return student.first_name
            if column == 3:
                return "Active" if student.active else "Inactive"
            if column == 4:
                return student.notes.splitlines()[0] if student.notes else ""
        elif role == Qt.ItemDataRole.ToolTipRole and column == 4 and student.notes:
            return student.notes
        elif role == Qt.ItemDataRole.ForegroundRole and not student.active:
            # Grey out inactive students using the theme's placeholder colour.
            return QApplication.palette().color(QPalette.ColorRole.PlaceholderText)
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None


class RosterView(QWidget):
    """Student list for the selected class: search, add, edit, (de)activate."""

    create_class_requested = Signal()
    students_changed = Signal()  # a student was added, edited, deactivated or reactivated

    def __init__(self, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.roster = roster
        self.class_id: int | None = None

        # --- toolbar ---
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name or student number  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.show_inactive = QCheckBox("Show inactive")
        self.show_inactive.toggled.connect(self.refresh)
        self.add_button = QPushButton("Add student")
        self.add_button.clicked.connect(self.add_student)
        self.paste_button = QPushButton("Paste list…")
        self.paste_button.setToolTip("Add many students at once, e.g. copied from a spreadsheet")
        self.paste_button.clicked.connect(self.paste_students)
        self.edit_button = QPushButton("Edit…")
        self.edit_button.clicked.connect(self.edit_selected)
        self.toggle_active_button = QPushButton("Deactivate")
        self.toggle_active_button.clicked.connect(self.toggle_active_selected)
        self.transfer_button = QPushButton("Move to class…")
        self.transfer_button.setToolTip("Move the selected student to another class")
        self.transfer_button.clicked.connect(self.transfer_selected)
        self.export_button = QPushButton("Export…")
        self.export_button.setToolTip("Save the class list as a CSV file for Excel or other programs")
        self.export_button.clicked.connect(self.export_csv)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search, stretch=1)
        toolbar.addWidget(self.show_inactive)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.paste_button)

        # --- table ---
        self.model = StudentTableModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

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
        self.table.selectionModel().selectionChanged.connect(self._update_buttons)

        self.count_label = QLabel()
        # Actions on the selected student sit under the table, leaving room to search.
        footer = QHBoxLayout()
        footer.addWidget(self.count_label, stretch=1)
        footer.addWidget(self.edit_button)
        footer.addWidget(self.toggle_active_button)
        footer.addWidget(self.transfer_button)
        footer.addSpacing(12)
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
        )
        dialog.exec()
        if dialog.added:  # also when cancelled after "Save and add another"
            self.search.clear()  # make sure the new students are visible
            self.refresh()
            self._select(dialog.added[-1].id)
            self.students_changed.emit()

    def paste_students(self) -> None:
        if self.class_id is None:
            return
        dialog = PasteStudentsDialog(self.roster, self.class_id, parent=self)
        if dialog.exec() and dialog.added:
            self.search.clear()
            self.refresh()
            self._select(dialog.added[0].id)
            self.students_changed.emit()

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
            self.roster.deactivate_student(student.id)
        else:
            self.roster.reactivate_student(student.id)
        self.refresh()
        self.students_changed.emit()

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
        if student.student_no and not moved.student_no:
            details.append(
                f"Student number {student.student_no} is already used in {target.name}, "
                "so they have no number there yet."
            )
        QMessageBox.information(
            self,
            "Move to class",
            f"{student.full_name} is now in {target.display_name}." + "".join(f"\n\n{d}" for d in details),
        )
        self.refresh()
        self.students_changed.emit()

    def export_csv(self) -> None:
        """Save every student of the class (inactive ones too if they are shown) as CSV."""
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if school_class is None:
            return
        safe_name = re.sub(r'[\\/:*?"<>|]+', "-", school_class.display_name)
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export students", str(Path.home() / f"{safe_name} students.csv"), "CSV files (*.csv)"
        )
        if not path:
            return
        path = Path(path) if path.lower().endswith(".csv") else Path(path + ".csv")
        students = self.roster.list_students(school_class.id, include_inactive=self.show_inactive.isChecked())
        try:
            write_roster_csv(path, students)
        except OSError as exc:
            QMessageBox.warning(self, "Export students", f"The file could not be saved:\n{exc}")
            return
        QMessageBox.information(self, "Export students", f"Saved {len(students)} students to\n{path}")

    # --- helpers -------------------------------------------------------------

    def _selected_student(self) -> Student | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.student_at(self.proxy.mapToSource(rows[0]).row())

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
        self.edit_button.setEnabled(student is not None)
        self.toggle_active_button.setEnabled(student is not None)
        self.transfer_button.setEnabled(student is not None)
        self.toggle_active_button.setText(
            "Reactivate" if student is not None and not student.active else "Deactivate"
        )

    def _update_count(self) -> None:
        shown = self.model.rowCount()
        noun = "student" if shown == 1 else "students"
        text = f"{shown} {noun}"
        if self.search.text().strip():
            text += " match your search"
        self.count_label.setText(text)
