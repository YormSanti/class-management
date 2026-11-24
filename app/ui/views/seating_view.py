"""The seating chart of the current class: desks in rows, the front of the room at the bottom."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.roster import RosterService
from app.services.seating import SeatingPlan, SeatingService
from app.ui import style
from app.ui.dialogs.layout_dialog import LayoutDialog

STUDENT_ID = Qt.ItemDataRole.UserRole
SEAT_WIDTH = 120
SEAT_HEIGHT = 56


class SeatingView(QWidget):
    def __init__(self, seating: SeatingService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.seating = seating
        self.roster = roster
        self.class_id: int | None = None
        self.layout_id: int | None = None
        self.plan: SeatingPlan | None = None

        self.title = style.label("Seating chart", 1.6, bold=True)
        self.subtitle = style.label("", 0.95, muted=True)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        self.layout_combo = QComboBox()
        self.layout_combo.setToolTip("The class's seating plans, e.g. one for tests and one for group work")
        self.layout_combo.currentIndexChanged.connect(self._layout_picked)
        plan_label = QLabel("&Plan")
        plan_label.setBuddy(self.layout_combo)
        self.new_button = QPushButton("&New plan…")
        self.new_button.setObjectName("Primary")
        self.new_button.clicked.connect(self.new_layout)
        header = QHBoxLayout()
        header.addLayout(titles, stretch=1)
        header.addWidget(plan_label, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.layout_combo, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.new_button, alignment=Qt.AlignmentFlag.AlignBottom)

        # --- the room ---
        self.summary = style.label("", 0.95, muted=True)
        self.grid = QTableWidget()
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grid.setWordWrap(True)
        for head in (self.grid.horizontalHeader(), self.grid.verticalHeader()):
            head.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.grid.horizontalHeader().setDefaultSectionSize(SEAT_WIDTH)
        self.grid.verticalHeader().setDefaultSectionSize(SEAT_HEIGHT)
        self.front = style.label("Front of the room", 0.9, muted=True)
        self.front.setAlignment(Qt.AlignmentFlag.AlignCenter)
        room = QVBoxLayout()
        room.addWidget(self.grid, stretch=1)
        room.addWidget(self.front)
        self.unseated = QListWidget()
        self.unseated.setMaximumWidth(240)
        side = QVBoxLayout()
        self.unseated_label = style.label("Not seated", 1.0, bold=True)
        side.addWidget(self.unseated_label)
        side.addWidget(self.unseated, stretch=1)
        body = QHBoxLayout()
        body.addLayout(room, stretch=1)
        body.addLayout(side)
        self.plan_page = QWidget()
        plan_layout = QVBoxLayout(self.plan_page)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        plan_layout.addWidget(self.summary)
        plan_layout.addLayout(body, stretch=1)

        # --- empty states ---
        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_button = QPushButton("New seating plan…")
        self.empty_button.setObjectName("Primary")
        self.empty_button.clicked.connect(self.new_layout)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        empty_layout.addWidget(self.empty_label)
        empty_layout.addWidget(self.empty_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()

        self.pages = QStackedWidget()
        self.pages.addWidget(empty)
        self.pages.addWidget(self.plan_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(self.pages, stretch=1)
        self.setStyleSheet(style.card_stylesheet(self))
        self.refresh()

    # --- page protocol ---------------------------------------------------------

    def set_class(self, class_id: int | None) -> None:
        if class_id != self.class_id:
            self.layout_id = None
        self.class_id = class_id
        self.refresh()

    def showEvent(self, event) -> None:
        # Students may have been added or deactivated meanwhile.
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """Read the current plan from the database again."""
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if school_class is None:
            self.class_id = None
        self.subtitle.setText(school_class.display_name if school_class else "")
        layouts = self.seating.list_layouts(self.class_id) if self.class_id is not None else []
        if self.layout_id not in [x.id for x in layouts]:
            self.layout_id = layouts[0].id if layouts else None
        with QSignalBlocker(self.layout_combo):
            self.layout_combo.clear()
            for x in layouts:
                self.layout_combo.addItem(f"{x.name} ({x.rows} × {x.cols})", x.id)
            self.layout_combo.setCurrentIndex(self.layout_combo.findData(self.layout_id))
        self.layout_combo.setEnabled(bool(layouts))
        self.new_button.setEnabled(self.class_id is not None)
        self.plan = self.seating.plan(self.layout_id) if self.layout_id is not None else None
        if self.class_id is None:
            self._empty("<h2>No class selected</h2><p>Create a class to plan where its students sit.</p>")
        elif self.plan is None:
            self._empty(
                "<h2>No seating plan yet</h2><p>Set out the desks of the room in rows and seats, "
                "then seat the students. A class can keep several plans, e.g. one for tests.</p>",
                button=True,
            )
        else:
            self._fill()
            self.pages.setCurrentWidget(self.plan_page)

    def _empty(self, text: str, button: bool = False) -> None:
        self.empty_label.setText(text)
        self.empty_button.setVisible(button)
        self.pages.setCurrentIndex(0)

    def _layout_picked(self, index: int) -> None:
        layout_id = self.layout_combo.itemData(index)
        if layout_id is not None and layout_id != self.layout_id:
            self.layout_id = layout_id
            self.refresh()

    def new_layout(self) -> None:
        if self.class_id is None:
            return
        name = "Seating plan" if not self.seating.list_layouts(self.class_id) else ""
        dialog = LayoutDialog(self.seating.save_layout, self.class_id, parent=self, default_name=name)
        if dialog.exec() and dialog.saved:
            self.layout_id = dialog.saved.id
            self.refresh()

    # --- the room --------------------------------------------------------------

    def _fill(self) -> None:
        plan = self.plan
        grid = self.grid
        grid.clear()
        grid.setRowCount(plan.layout.rows)
        grid.setColumnCount(plan.layout.cols)
        # Rows are numbered from the front, which is at the bottom, as the teacher sees the room.
        grid.setVerticalHeaderLabels([str(plan.layout.rows - r) for r in range(plan.layout.rows)])
        grid.setHorizontalHeaderLabels([str(c + 1) for c in range(plan.layout.cols)])
        for row in range(plan.layout.rows):
            for col in range(plan.layout.cols):
                grid.setItem(*self.cell_of(row, col), self._seat_item(row, col))
        self.unseated.clear()
        for student in plan.unseated:
            item = QListWidgetItem(student.full_name)
            item.setData(STUDENT_ID, student.id)
            self.unseated.addItem(item)
        seated = len(plan.seats)
        free = len(plan.free_seats)
        self.summary.setText(
            f"{seated} of {len(plan.students)} students seated · {free} free seat{'' if free == 1 else 's'}"
        )
        self.unseated_label.setText(f"Not seated ({len(plan.unseated)})")

    def cell_of(self, row: int, col: int) -> tuple[int, int]:
        """The grid cell of seat (row, col); row 0 is the front, shown at the bottom."""
        return self.plan.layout.rows - 1 - row, col

    def seat_at(self, grid_row: int, grid_col: int) -> tuple[int, int]:
        """The seat (row, col) shown in a grid cell."""
        return self.plan.layout.rows - 1 - grid_row, grid_col

    def _seat_item(self, row: int, col: int) -> QTableWidgetItem:
        student = self.plan.student_at(row, col)
        item = QTableWidgetItem(student.full_name if student else "")
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if student:
            item.setData(STUDENT_ID, student.id)
        return item
