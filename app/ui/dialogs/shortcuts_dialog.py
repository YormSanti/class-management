from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# (where, keys, what they do); keep in step with the shortcuts set up on each page.
SHORTCUTS: tuple[tuple[str, str, str], ...] = (
    ("Anywhere", "Ctrl+1 … Ctrl+7", "Switch page, in sidebar order"),
    ("Anywhere", "Ctrl+Shift+B", "Back up now"),
    ("Anywhere", "F5", "Reload the page shown"),
    ("Anywhere", "F1", "This list"),
    ("Attendance, Day tab", "P  L  A  E", "Mark present, late, absent or excused and go to the next student"),
    ("Attendance, Day tab", "Delete", "Clear the student's mark"),
    ("Attendance, Day tab", "N or Enter", "Write a note; Enter or Esc to finish"),
    ("Attendance, Day tab", "H", "Show the student's attendance history"),
    ("Attendance, Day tab", "Alt+Left  Alt+Right", "Previous or next school day"),
    ("Attendance, Day tab", "Alt+Home", "Today"),
    ("Attendance, Day tab", "Ctrl+Z", "Undo the last change"),
    ("Attendance, Month tab", "Enter", "Open the selected day"),
    ("Students", "Ctrl+F", "Search; Esc clears the search"),
    ("Students", "Ctrl+N", "Add a student"),
    ("Students", "Enter", "Edit the selected student"),
    ("Students", "Delete", "Delete the selected student, or deactivate them if anything is recorded"),
    ("Students", "Ctrl+C", "Copy the students shown, for a spreadsheet"),
)


class ShortcutsDialog(QDialog):
    """Every keyboard shortcut of the app, by page."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.setMinimumSize(620, 480)

        self.table = QTableWidget(len(SHORTCUTS), 3)
        self.table.setHorizontalHeaderLabels(["Where", "Keys", "What it does"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        head.setStretchLastSection(True)
        for row, values in enumerate(SHORTCUTS):
            for col, text in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(text))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
