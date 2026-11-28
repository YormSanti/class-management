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
    ("Attendance, Day tab", "1  2  3  4, Space", "The same from the number pad; Space marks present"),
    ("Attendance, Day tab", "Delete", "Clear the student's mark"),
    ("Attendance, Day tab", "N or Enter", "Write a note; Enter or Esc to finish, ↑ ↓ for the next note"),
    ("Attendance, Day tab", "H", "Show the student's attendance history"),
    ("Attendance, Day tab", "U", "Go to the next student not marked yet"),
    ("Attendance, Day tab", "D", "Mark the student for several days, e.g. a sick note"),
    ("Attendance, Day tab", "Alt+Left  Alt+Right", "Previous or next school day"),
    ("Attendance, Day tab", "Alt+Home", "Today"),
    ("Attendance, Day tab", "Ctrl+Enter", "Mark the rest present"),
    ("Attendance, Day tab", "Ctrl+Shift+C", "Copy the day's absences, e.g. for the school office"),
    ("Attendance, Day tab", "Ctrl+Z", "Undo the last change"),
    ("Attendance, Day tab", "Ctrl+Y", "Redo what was undone"),
    ("Attendance, Day tab", "Ctrl+F", "Find a student by name or number; Enter goes back to the list"),
    ("Attendance, Month tab", "Enter", "Open the selected day"),
    ("Attendance, Month tab", "H", "Show the selected student's attendance history"),
    ("Attendance, Month tab", "Alt+Left  Alt+Right, Page Up  Page Down", "Previous or next month"),
    ("Attendance, Month tab", "Alt+Home", "This month"),
    ("Attendance, Month tab", "Ctrl+F", "Find a student's row by name or number; Enter goes back to the table"),
    ("Gradebook", "0-9, ex", "Type a score in the selected cell: points, a percentage (85%), points out of a total (17/20) or ex for exempt"),
    ("Gradebook", "Enter", "Save the score and go to the next student"),
    ("Gradebook", "Shift+Enter", "Save the score and go back to the student before"),
    ("Gradebook", "Delete", "Clear the selected scores"),
    ("Gradebook", "Ctrl+C  Ctrl+V", "Copy the selected scores, or paste scores copied from a spreadsheet"),
    ("Gradebook", "Ctrl+Z", "Undo the last change to the scores"),
    ("Gradebook", "Ctrl+Y", "Redo what was undone"),
    ("Gradebook", "Ctrl+F", "Find a student by name or number"),
    ("Gradebook", "Ctrl+N", "Add an assignment"),
    ("Grade categories", "Ctrl+N", "Add a category"),
    ("Grade categories", "Enter or F2", "Edit the selected category"),
    ("Grade categories", "Delete", "Delete the selected category, while no assignment is in it"),
    ("Rankings", "Alt+R", "Choose what to rank by: all subjects or one of them"),
    ("Rankings", "Ctrl+F", "Find a student's place by name or number; Enter goes to it"),
    ("Rankings", "Ctrl+C", "Copy the ranking, to paste into a spreadsheet"),
    ("Rankings", "Enter", "Show the selected student's scores in the gradebook (or double-click them)"),
    ("Seating", "Enter or Space", "Pick up the selected student, or put the student picked up in the selected seat"),
    ("Seating", "Esc", "Put the student picked up down again"),
    ("Seating", "Delete", "Take the selected student out of their seat"),
    ("Seating", "Shift+F10", "List what can be done with the selected seat, e.g. say there's no desk"),
    ("Seating", "Ctrl+F", "Find a student's seat by name or number; Enter goes to it"),
    ("Seating", "Ctrl+Z", "Undo the last change to the plan"),
    ("Seating", "Ctrl+Y", "Redo what was undone"),
    ("Manage classes", "F2", "Edit the selected class"),
    ("Manage classes", "Delete", "Delete the selected class, while nothing is recorded in it"),
    ("Subjects", "F2", "Edit the selected subject"),
    ("Subjects", "Delete", "Delete the selected subject, while nothing is recorded in it"),
    ("Students", "Ctrl+F", "Search; Enter goes to the first student found, Esc clears the search"),
    ("Students", "Ctrl+N", "Add a student"),
    ("Add student", "Ctrl+Enter", "Save and add another"),
    ("Students", "Enter or F2", "Edit the selected student"),
    ("Students", "Delete", "Delete the selected student, or deactivate them if anything is recorded"),
    ("Students", "Ctrl+C", "Copy the students shown, for a spreadsheet"),
    ("Students", "Ctrl+V", "Add the students copied, e.g. from a spreadsheet, after a preview"),
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
