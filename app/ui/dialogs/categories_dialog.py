from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.gradebook import GradebookError, GradebookService, format_number, weight_shares
from app.ui.dialogs.category_dialog import CategoryDialog

CATEGORY_ID = Qt.ItemDataRole.UserRole


class CategoriesDialog(QDialog):
    """The grade categories of one subject, with what each makes up of the average."""

    def __init__(self, grades: GradebookService, subject_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        subject = grades.subjects.get(subject_id)
        self.setWindowTitle(f"Categories of {subject.name}" if subject else "Categories")
        self.setMinimumSize(460, 320)
        self.grades = grades
        self.subject_id = subject_id
        self.changed = False  # tells the gradebook to reload

        intro = QLabel(
            "Each assignment belongs to a category. A student's average counts each category by its "
            "weight; weights are compared with each other, so they needn't add up to 100."
        )
        intro.setWordWrap(True)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Category", "Weight", "Share of average", "Assignments"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_category())
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.add_button = QPushButton("&Add…")
        self.add_button.setToolTip("Add a category (Ctrl+N)")
        self.add_button.clicked.connect(self.add_category)
        self.edit_button = QPushButton("&Edit…")
        self.edit_button.setToolTip("Edit the selected category (Enter or F2)")
        self.edit_button.clicked.connect(self.edit_category)
        self.delete_button = QPushButton("&Delete")
        self.delete_button.setToolTip("Delete the selected category, while no assignment is in it (Delete)")
        self.delete_button.clicked.connect(self.delete_category)
        row = QHBoxLayout()
        for button in (self.add_button, self.edit_button, self.delete_button):
            button.setAutoDefault(False)  # Enter in the list edits, it doesn't press a button
            row.addWidget(button)
        row.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        row.addWidget(close)

        for keys in ("Return", "Enter", "F2", "Delete"):
            shortcut = QShortcut(QKeySequence(keys), self.table)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            if keys == "Delete":
                shortcut.activated.connect(lambda: self.delete_category())
            else:
                shortcut.activated.connect(lambda: self.edit_category())
        QShortcut(QKeySequence.StandardKey.New, self).activated.connect(lambda: self.add_category())

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(row)
        self.refresh()

    def refresh(self, select: int | None = None) -> None:
        categories = self.grades.list_categories(self.subject_id)
        shares = weight_shares(categories)
        counts = self.grades.assignment_counts(self.subject_id)
        self.table.setRowCount(len(categories))
        for r, category in enumerate(categories):
            cells = (category.name, format_number(category.weight), f"{shares[category.id]:.0f}%",
                     str(counts.get(category.id, 0)))  # fmt: skip
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(CATEGORY_ID, category.id)
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
            if category.id == select:
                self.table.selectRow(r)
        self._update_buttons()

    def selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(CATEGORY_ID) if rows else None

    def _update_buttons(self) -> None:
        self.edit_button.setEnabled(self.selected_id() is not None)
        self.delete_button.setEnabled(self.selected_id() is not None)

    def add_category(self) -> None:
        dialog = CategoryDialog(self.grades.save_category, self.subject_id, parent=self)
        if dialog.exec() and dialog.saved:
            self.changed = True
            self.refresh(dialog.saved.id)

    def edit_category(self) -> None:
        category_id = self.selected_id()
        category = self.grades.gradebook.get_category(category_id) if category_id else None
        if category is None:
            return
        dialog = CategoryDialog(self.grades.save_category, self.subject_id, category, parent=self)
        if dialog.exec():
            self.changed = True
            self.refresh(category.id)

    def delete_category(self) -> None:
        category_id = self.selected_id()
        if category_id is None:
            return
        try:
            self.grades.delete_category(category_id)
        except GradebookError as exc:
            QMessageBox.information(self, "Delete category", str(exc))
            return
        self.changed = True
        self.refresh()
