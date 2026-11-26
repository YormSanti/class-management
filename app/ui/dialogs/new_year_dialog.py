from datetime import date

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import SchoolClass
from app.services.roster import RosterError, RosterService, example_school_year, move_up, next_term, term_warning

_COPY, _CLASS, _STUDENTS, _SUBJECTS, _NEW_NAME = range(5)


class NewYearDialog(QDialog):
    """Start a school year by copying chosen classes, their subjects and (optionally) students.

    The previous year is not changed. `created` holds the new classes after OK.
    """

    def __init__(self, roster: RosterService, from_term: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New school year")
        self.setMinimumSize(520, 460)
        self.roster = roster
        self.created: list[SchoolClass] = []
        self._suggested_term = ""

        terms = roster.list_terms()
        self.source = QComboBox()
        for term in terms:
            self.source.addItem(term, term)
        if any(not c.term for c in roster.list_classes()):
            self.source.addItem("No school year", "")
        self.source.setCurrentIndex(max(0, self.source.findData(from_term)))
        self.source.currentIndexChanged.connect(self._load_classes)

        self.new_term = QLineEdit()
        self.new_term.setPlaceholderText(f"e.g. {next_term(example_school_year(date.today()))}")

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Copy", "Class", "Students", "Subjects", "New name"))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_NEW_NAME, QHeaderView.ResizeMode.Stretch)

        move_up_button = QPushButton("Move up a grade")
        move_up_button.setToolTip("Rename every class one grade up, e.g. 7B → 8B")
        move_up_button.clicked.connect(self._move_up)
        keep_names_button = QPushButton("Keep names")
        keep_names_button.clicked.connect(self._keep_names)
        self.tick_all_button = QPushButton("Untick all")
        self.tick_all_button.setToolTip("Tick or untick every class, e.g. to copy only one or two")
        self.tick_all_button.clicked.connect(self._tick_all)
        self.table.itemChanged.connect(self._update_tick_all)
        name_buttons = QHBoxLayout()
        name_buttons.addWidget(self.tick_all_button)
        name_buttons.addWidget(QLabel("Double-click a new name to change it."))
        name_buttons.addStretch()
        name_buttons.addWidget(keep_names_button)
        name_buttons.addWidget(move_up_button)

        self.copy_students = QCheckBox("Bring the students along (active students only)")
        self.copy_students.setChecked(True)
        note = QLabel(
            "Subjects and their teachers are copied. Attendance and grades start empty; "
            "the old school year stays exactly as it is."
        )
        note.setWordWrap(True)
        note.setForegroundRole(QPalette.ColorRole.PlaceholderText)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create classes")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Copy classes from", self.source)
        form.addRow("New school year*", self.new_term)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(name_buttons)
        layout.addWidget(self.copy_students)
        layout.addWidget(note)
        layout.addWidget(buttons)

        self._load_classes()

    def _load_classes(self) -> None:
        term = self.source.currentData()
        # Keep a year the teacher typed; replace only our own earlier suggestion.
        if self.new_term.text().strip() in ("", self._suggested_term):
            self._suggested_term = next_term(term or "")
            self.new_term.setText(self._suggested_term)

        counts = self.roster.class_counts()
        with QSignalBlocker(self.table):
            self.table.setRowCount(0)
            for row, school_class in enumerate(self.roster.list_classes(term if term is not None else "")):
                self.table.insertRow(row)
                copy = QTableWidgetItem()
                copy.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                copy.setCheckState(Qt.CheckState.Checked)
                copy.setData(Qt.ItemDataRole.UserRole, school_class.id)
                self.table.setItem(row, _COPY, copy)
                for col, text in (
                    (_CLASS, school_class.name),
                    (_STUDENTS, str(counts.get(school_class.id, (0, 0))[0])),
                    (_SUBJECTS, str(counts.get(school_class.id, (0, 0))[1])),
                ):
                    item = QTableWidgetItem(text)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    if col == _SUBJECTS:  # these are copied, so say which
                        item.setToolTip(", ".join(s.name for s in self.roster.list_subjects(school_class.id)))
                    self.table.setItem(row, col, item)
                self.table.setItem(row, _NEW_NAME, QTableWidgetItem(school_class.name))
        self._update_tick_all()

    def _copy_items(self) -> list[QTableWidgetItem]:
        return [self.table.item(row, _COPY) for row in range(self.table.rowCount())]

    def _tick_all(self) -> None:
        """Untick every class if all are ticked, otherwise tick them all."""
        items = self._copy_items()
        all_ticked = all(i.checkState() == Qt.CheckState.Checked for i in items)
        state = Qt.CheckState.Unchecked if all_ticked else Qt.CheckState.Checked
        with QSignalBlocker(self.table):
            for item in items:
                item.setCheckState(state)
        self._update_tick_all()

    def _update_tick_all(self) -> None:
        items = self._copy_items()
        all_ticked = bool(items) and all(i.checkState() == Qt.CheckState.Checked for i in items)
        self.tick_all_button.setText("Untick all" if all_ticked else "Tick all")
        self.tick_all_button.setEnabled(bool(items))

    def _move_up(self) -> None:
        for row in range(self.table.rowCount()):
            self.table.item(row, _NEW_NAME).setText(move_up(self.table.item(row, _CLASS).text()))

    def _keep_names(self) -> None:
        for row in range(self.table.rowCount()):
            self.table.item(row, _NEW_NAME).setText(self.table.item(row, _CLASS).text())

    def plan(self) -> list[tuple[int, str]]:
        """(class to copy, new name) for every ticked row."""
        plan = []
        for row in range(self.table.rowCount()):
            copy = self.table.item(row, _COPY)
            if copy.checkState() == Qt.CheckState.Checked:
                plan.append((copy.data(Qt.ItemDataRole.UserRole), self.table.item(row, _NEW_NAME).text()))
        return plan

    def accept(self) -> None:
        warning = term_warning(" ".join(self.new_term.text().split()), date.today())
        if warning and QMessageBox.question(
            self, self.windowTitle(), f"{warning}\n\nCreate the classes in this school year anyway?"
        ) != QMessageBox.StandardButton.Yes:
            self.new_term.setFocus()
            return
        try:
            self.created = self.roster.start_new_year(
                self.new_term.text(), self.plan(), self.copy_students.isChecked()
            )
        except RosterError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        super().accept()
