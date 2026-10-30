from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.roster import RosterService
from app.ui.views.roster_view import RosterView

ALL_YEARS = "\0all"  # year-filter value meaning "show every school year"


def _table(headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setStretchLastSection(True)
    return table


def _item(text: str, data: int | None = None, align_right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


class ClassesView(QWidget):
    """Classes by school year, and the students and subjects of the selected class.

    The Students tab is the full roster (search, add, edit, deactivate). This is where the app's current class and subject are chosen: clicking a row
    makes it current for every page, and switching the school year switches to a
    class of that year. The buttons only emit requests; the main window runs the
    dialogs and owns the current selection.
    """

    class_selected = Signal(int)
    subject_selected = Signal(int)
    new_class_requested = Signal(str)  # school year to suggest for the new class
    new_year_requested = Signal(str)  # school year to copy classes from
    edit_class_requested = Signal()
    delete_class_requested = Signal()
    new_subject_requested = Signal()
    edit_subject_requested = Signal()
    delete_subject_requested = Signal()

    def __init__(self, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.roster = roster
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self.year: str | None = None  # school year shown; "" = classes without one

        # --- school year ---
        self.year_combo = QComboBox()
        self.year_combo.setMinimumContentsLength(14)
        self.year_combo.activated.connect(self._on_year_picked)
        year_row = QHBoxLayout()
        year_row.addWidget(QLabel("School year:"))
        year_row.addWidget(self.year_combo)
        year_row.addStretch()
        self.new_year_button = QPushButton("New school year…")
        self.new_year_button.setToolTip("Create next year's classes from this year's")
        self.new_year_button.clicked.connect(
            lambda: self.new_year_requested.emit("" if self.year == ALL_YEARS else self.year or "")
        )
        year_row.addWidget(self.new_year_button)

        # --- classes ---
        self.class_table = _table(("Class", "School year", "Students", "Subjects"))
        self.class_table.horizontalHeader().setStretchLastSection(False)
        self.class_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.class_table.itemSelectionChanged.connect(self._on_class_clicked)
        self.class_table.doubleClicked.connect(lambda _index: self.edit_class_requested.emit())
        new_class = QPushButton("New class…")
        new_class.clicked.connect(
            lambda: self.new_class_requested.emit("" if self.year == ALL_YEARS else self.year or "")
        )
        self.edit_class_button = QPushButton("Edit…")
        self.edit_class_button.clicked.connect(self.edit_class_requested)
        self.delete_class_button = QPushButton("Delete")
        self.delete_class_button.clicked.connect(self.delete_class_requested)

        class_buttons = QHBoxLayout()
        class_buttons.addWidget(new_class)
        class_buttons.addStretch()
        class_buttons.addWidget(self.edit_class_button)
        class_buttons.addWidget(self.delete_class_button)
        class_box = QGroupBox("Classes")
        class_layout = QVBoxLayout(class_box)
        class_layout.addWidget(self.class_table)
        class_layout.addLayout(class_buttons)

        # --- subjects of the selected class ---
        self.subject_table = _table(("Subject", "Teacher"))
        self.subject_table.itemSelectionChanged.connect(self._on_subject_clicked)
        self.subject_table.doubleClicked.connect(lambda _index: self.edit_subject_requested.emit())
        self.new_subject_button = QPushButton("Add subject…")
        self.new_subject_button.clicked.connect(self.new_subject_requested)
        self.edit_subject_button = QPushButton("Edit…")
        self.edit_subject_button.clicked.connect(self.edit_subject_requested)
        self.delete_subject_button = QPushButton("Delete")
        self.delete_subject_button.clicked.connect(self.delete_subject_requested)
        self.subject_hint = QLabel()
        self.subject_hint.setWordWrap(True)
        self.subject_hint.setForegroundRole(QPalette.ColorRole.PlaceholderText)

        subject_buttons = QHBoxLayout()
        subject_buttons.addWidget(self.new_subject_button)
        subject_buttons.addStretch()
        subject_buttons.addWidget(self.edit_subject_button)
        subject_buttons.addWidget(self.delete_subject_button)
        self.subject_box = QWidget()
        subject_layout = QVBoxLayout(self.subject_box)
        subject_layout.addWidget(self.subject_table)
        subject_layout.addWidget(self.subject_hint)
        subject_layout.addLayout(subject_buttons)

        # --- students and subjects of the selected class ---
        self.roster_view = RosterView(roster)
        self.roster_view.students_changed.connect(self.refresh)  # student counts
        self.tabs = QTabWidget()
        self.tabs.addTab(self.roster_view, "Students")
        self.tabs.addTab(self.subject_box, "Subjects")

        intro = QLabel(
            "<h2>Manage classes</h2><p>Click a class to see its students and subjects; the "
            "class and subject you pick are used on the other pages. A class is a group of "
            "students in one school year; each subject taught to it has its own gradebook. "
            "A class or subject can only be deleted while nothing is recorded in it.</p>"
        )
        intro.setWordWrap(True)

        columns = QHBoxLayout()
        columns.addWidget(class_box, stretch=1)
        columns.addWidget(self.tabs, stretch=2)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(year_row)
        layout.addLayout(columns, stretch=1)

        self.refresh()

    # --- page protocol -----------------------------------------------------

    def set_class(self, class_id: int | None) -> None:
        self.class_id = class_id
        self.roster_view.set_class(class_id)
        self.refresh()

    def set_subject(self, subject_id: int | None) -> None:
        self.subject_id = subject_id
        self.refresh()  # the class list shows subject counts too

    def showEvent(self, event) -> None:
        # Attendance or grades recorded meanwhile can change what may be deleted.
        super().showEvent(event)
        self.refresh()

    # --- helpers -------------------------------------------------------------

    def refresh(self) -> None:
        current = self.roster.get_class(self.class_id) if self.class_id is not None else None
        terms = self.roster.list_terms()
        classes = self.roster.list_classes()
        if self.year != ALL_YEARS and current is not None:
            self.year = current.term  # show the year of the class being worked on
        elif self.year is None or (self.year != ALL_YEARS and self.year not in terms):
            self.year = terms[0] if terms else ALL_YEARS

        with QSignalBlocker(self.year_combo):
            self.year_combo.clear()
            for term in terms:
                self.year_combo.addItem(term, term)
            if any(not c.term for c in classes):
                self.year_combo.addItem("No school year", "")
            self.year_combo.addItem("All years", ALL_YEARS)
            self.year_combo.setCurrentIndex(max(0, self.year_combo.findData(self.year)))

        self.new_year_button.setEnabled(bool(classes))
        shown = classes if self.year == ALL_YEARS else [c for c in classes if c.term == self.year]
        self.class_table.setColumnHidden(1, self.year != ALL_YEARS)
        with QSignalBlocker(self.class_table):
            self.class_table.setRowCount(0)
            for school_class in shown:
                row = self.class_table.rowCount()
                self.class_table.insertRow(row)
                students = len(self.roster.list_students(school_class.id))
                subjects = len(self.roster.list_subjects(school_class.id))
                self.class_table.setItem(row, 0, _item(school_class.name, school_class.id))
                self.class_table.setItem(row, 1, _item(school_class.term))
                self.class_table.setItem(row, 2, _item(str(students), align_right=True))
                self.class_table.setItem(row, 3, _item(str(subjects), align_right=True))
                if school_class.id == self.class_id:
                    self.class_table.selectRow(row)
        has_class = self.class_id is not None
        self.edit_class_button.setEnabled(has_class)
        self.delete_class_button.setEnabled(has_class)
        self._refresh_subjects()

    def _refresh_subjects(self) -> None:
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        subjects = self.roster.list_subjects(school_class.id) if school_class else []
        with QSignalBlocker(self.subject_table):
            self.subject_table.setRowCount(0)
            for row, subject in enumerate(subjects):
                self.subject_table.insertRow(row)
                self.subject_table.setItem(row, 0, _item(subject.name, subject.id))
                self.subject_table.setItem(row, 1, _item(subject.teacher or "You"))
                if subject.id == self.subject_id:
                    self.subject_table.selectRow(row)

        students = len(self.roster.list_students(school_class.id)) if school_class else 0
        self.tabs.setTabText(0, f"Students ({students})" if school_class else "Students")
        self.tabs.setTabText(1, f"Subjects ({len(subjects)})" if school_class else "Subjects")
        self.subject_box.setEnabled(school_class is not None)
        if school_class is None:
            self.subject_hint.setText("Create a class first.")
        elif not subjects:
            self.subject_hint.setText("No subjects yet. Add the subjects taught to this class.")
        else:
            self.subject_hint.setText("")
        self.subject_hint.setVisible(bool(self.subject_hint.text()))
        has_subject = self.subject_id is not None and bool(subjects)
        self.edit_subject_button.setEnabled(has_subject)
        self.delete_subject_button.setEnabled(has_subject)

    def _selected_id(self, table: QTableWidget) -> int | None:
        rows = table.selectionModel().selectedRows()
        return table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None

    def _on_class_clicked(self) -> None:
        class_id = self._selected_id(self.class_table)
        if class_id is not None and class_id != self.class_id:
            self.class_selected.emit(class_id)

    def _on_subject_clicked(self) -> None:
        subject_id = self._selected_id(self.subject_table)
        if subject_id is not None and subject_id != self.subject_id:
            self.subject_selected.emit(subject_id)

    def _on_year_picked(self, _index: int) -> None:
        """Show another school year, and switch to one of its classes so every page follows."""
        self.year = self.year_combo.currentData()
        current = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if self.year != ALL_YEARS and (current is None or current.term != self.year):
            in_year = self.roster.list_classes(self.year)
            if in_year:
                self.class_selected.emit(in_year[0].id)
                return
        self.refresh()
