"""The seating chart of the current class: desks in rows, the front of the room at the bottom."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.roster import RosterService
from app.models import SeatLayout
from app.services.export import seating_plan_html
from app.services.seating import SeatingError, SeatingPlan, SeatingService
from app.ui import style
from app.ui.dialogs.layout_dialog import LayoutDialog
from app.ui.files import ask_save_path, write_pdf

STUDENT_ID = Qt.ItemDataRole.UserRole
SEAT_WIDTH = 120
SEAT_HEIGHT = 56
UNDO_LIMIT = 50
HINT = (
    "Click a student under Not seated, then a seat. Click a seated student, then another seat "
    "to move them; if it's taken, the two swap. Delete takes a student out of their seat."
)


class SeatingView(QWidget):
    def __init__(self, seating: SeatingService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.seating = seating
        self.roster = roster
        self.class_id: int | None = None
        self.layout_id: int | None = None
        self.plan: SeatingPlan | None = None
        self.picked: int | None = None  # the student clicked, waiting for a seat
        # Who sat where before each change, as (layout id, {(row, col): student id}).
        self._undo: list[tuple[int, dict[tuple[int, int], int]]] = []
        self._redo: list[tuple[int, dict[tuple[int, int], int]]] = []

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
        self.edit_button = QPushButton("&Edit…")
        self.edit_button.setToolTip("Rename the plan or change the rows and seats of the room")
        self.edit_button.clicked.connect(self.edit_layout)
        self.delete_button = QPushButton("&Delete")
        self.delete_button.setToolTip("Delete the plan shown")
        self.delete_button.clicked.connect(self.delete_layout)
        header = QHBoxLayout()
        header.addLayout(titles, stretch=1)
        header.addWidget(plan_label, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.layout_combo, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.edit_button, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.delete_button, alignment=Qt.AlignmentFlag.AlignBottom)
        self.pdf_button = QPushButton("Save PD&F…")
        self.pdf_button.setToolTip("Save the plan as a PDF to print, e.g. for a substitute teacher")
        self.pdf_button.clicked.connect(self.save_pdf)
        header.addWidget(self.pdf_button, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.new_button, alignment=Qt.AlignmentFlag.AlignBottom)

        # --- the room ---
        self.summary = style.label("", 0.95, muted=True)
        self.fill_button = QPushButton("Seat the &rest")
        self.fill_button.setToolTip("Seat the students not seated yet in the free seats, front row first, by name")
        self.fill_button.clicked.connect(lambda: self.fill(shuffle=False))
        self.shuffle_button = QPushButton("&Shuffle")
        self.shuffle_button.setToolTip("Seat everyone at random, front row first (Ctrl+Z undoes)")
        self.shuffle_button.clicked.connect(lambda: self.fill(shuffle=True))
        self.clear_button = QPushButton("C&lear")
        self.clear_button.setToolTip("Take every student out of their seat (Ctrl+Z undoes)")
        self.clear_button.clicked.connect(self.clear_seats)
        summary_row = QHBoxLayout()
        summary_row.addWidget(self.summary, stretch=1)
        for button in (self.fill_button, self.shuffle_button, self.clear_button):
            summary_row.addWidget(button)
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
        plan_layout.addLayout(summary_row)
        plan_layout.addLayout(body, stretch=1)
        self.hint = style.label(HINT, 0.85, muted=True)
        self.hint.setWordWrap(True)
        plan_layout.addWidget(self.hint)
        self.grid.cellClicked.connect(lambda r, c: self.seat_clicked(*self.seat_at(r, c)))
        self.unseated.itemClicked.connect(lambda item: self.pick(item.data(STUDENT_ID)))
        for widget, act in (
            (self.grid, lambda: self.grid.currentRow() >= 0 and self.seat_clicked(
                *self.seat_at(self.grid.currentRow(), self.grid.currentColumn()))),
            (self.unseated, lambda: self.unseated.currentItem() and self.pick(
                self.unseated.currentItem().data(STUDENT_ID))),
        ):
            for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                shortcut = QShortcut(QKeySequence(key), widget)
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
                shortcut.activated.connect(act)
        for key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            unseat = QShortcut(QKeySequence(key), self.grid)
            unseat.setContext(Qt.ShortcutContext.WidgetShortcut)
            unseat.activated.connect(
                lambda: self.grid.currentRow() >= 0
                and self.unseat_at(*self.seat_at(self.grid.currentRow(), self.grid.currentColumn()))
            )
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._show_seat_menu)
        cancel = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        cancel.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        cancel.activated.connect(lambda: self.pick(None))
        undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self.undo)
        for keys in ("Ctrl+Y", "Ctrl+Shift+Z"):
            redo = QShortcut(QKeySequence(keys), self)
            redo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            redo.activated.connect(self.redo)

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
            self.clear_undo()
        self.class_id = class_id
        self.refresh()

    def showEvent(self, event) -> None:
        # Students may have been added or deactivated meanwhile.
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """Read the current plan from the database again."""
        self.picked = None
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
        for widget in (self.layout_combo, self.edit_button, self.delete_button, self.pdf_button):
            widget.setEnabled(bool(layouts))
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

    def edit_layout(self) -> None:
        if self.plan is None:
            return
        dialog = LayoutDialog(self._save_resized, self.class_id, self.plan.layout, parent=self)
        if dialog.exec():
            self.refresh()

    def _save_resized(self, layout: SeatLayout) -> SeatLayout:
        """Save an edited layout, after asking if the smaller room leaves students without a seat."""
        losing = self.seating.seated_outside(layout.id, layout.rows, layout.cols)
        if losing:
            names = ", ".join(s.full_name for s in losing)
            answer = QMessageBox.question(
                self,
                "Edit seating plan",
                f"The smaller room has no seat for {names}. Make it smaller anyway? "
                "They will be listed under Not seated.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                raise SeatingError("Choose more rows or seats, or Cancel to keep the room as it is.")
        return self.seating.save_layout(layout)

    def save_pdf(self) -> None:
        """Save the plan shown as a landscape A4 PDF, ready to print."""
        if self.plan is None:
            return
        title = f"{self.subtitle.text()} · {self.plan.layout.name}"
        name = f"{self.subtitle.text()} {self.plan.layout.name} seating"
        path = ask_save_path(self, "Save PDF", name, "PDF files", ".pdf")
        if path is not None and write_pdf(self, path, title, seating_plan_html(self.plan, title), True):
            QMessageBox.information(self, "Save PDF", f"Saved the seating plan to\n{path}")

    def delete_layout(self) -> None:
        if self.plan is None:
            return
        answer = QMessageBox.question(
            self, "Delete seating plan", f"Delete the seating plan {self.plan.layout.name}?\n\nThis can't be undone."
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.seating.delete_layout(self.plan.layout.id)
            self.layout_id = None
            self.refresh()

    # --- seating students -------------------------------------------------------

    def pick(self, student_id: int | None) -> None:
        """Take up a student to seat with the next seat clicked; None puts them down."""
        student = next((s for s in self.plan.students if s.id == student_id), None) if self.plan else None
        self.picked = student.id if student else None
        if student is None:
            self.hint.setText(HINT)
        else:
            if self.plan.seat_of(student.id):
                self.hint.setText(f"Now click where {student.full_name} should sit; in a taken seat, the two swap · Esc cancels")
            else:
                self.hint.setText(f"Now click a seat for {student.full_name} · Esc cancels")

    def seat_clicked(self, row: int, col: int) -> None:
        """Seat the student picked here, or pick up whoever sits here."""
        if self.plan is None:
            return
        if self.picked is None:
            occupant = self.plan.student_at(row, col)
            if occupant is not None:
                self.pick(occupant.id)
            return
        picked, self.picked = self.picked, None
        if self.plan.seat_of(picked) != (row, col):
            self._remember()
            try:
                self.seating.place(self.plan.layout.id, picked, row, col)
            except SeatingError as exc:
                QMessageBox.warning(self, "Seating chart", str(exc))
        self.refresh()
        self.grid.setCurrentCell(*self.cell_of(row, col))
        self.pick(None)

    def unseat_at(self, row: int, col: int) -> None:
        """Take whoever sits at (row, col) out of their seat."""
        occupant = self.plan.student_at(row, col) if self.plan else None
        if occupant is None:
            return
        self._remember()
        self.seating.unseat(self.plan.layout.id, occupant.id)
        self.refresh()
        self.grid.setCurrentCell(*self.cell_of(row, col))

    def seat_menu(self, row: int, col: int) -> QMenu | None:
        """What can be done with the student at (row, col); None for an empty seat."""
        occupant = self.plan.student_at(row, col) if self.plan else None
        if occupant is None:
            return None
        menu = QMenu(self)
        menu.addAction(f"&Move {occupant.full_name}…", lambda: self.pick(occupant.id))
        menu.addAction("&Take out of the seat\tDelete", lambda: self.unseat_at(row, col))
        return menu

    def _show_seat_menu(self, pos) -> None:
        index = self.grid.indexAt(pos)
        if index.isValid() and (menu := self.seat_menu(*self.seat_at(index.row(), index.column()))):
            menu.exec(self.grid.viewport().mapToGlobal(pos))

    def fill(self, shuffle: bool) -> None:
        """Seat the rest by name, or everyone at random."""
        if self.plan is None:
            return
        self._remember()
        self.seating.fill(self.plan.layout.id, shuffle=shuffle)
        self.refresh()
        if self.plan.unseated:
            names = ", ".join(s.full_name for s in self.plan.unseated)
            QMessageBox.information(
                self, "Seating chart", f"There's no free seat for {names}. Add seats with Edit…"
            )

    def clear_seats(self) -> None:
        if self.plan is None or not self.plan.seats:
            return
        self._remember()
        self.seating.set_seats(self.plan.layout.id, {})
        self.refresh()

    # --- undo ------------------------------------------------------------------

    def _remember(self) -> None:
        """Keep who sits where now, before a change, so Ctrl+Z can put it back."""
        self._undo.append((self.plan.layout.id, dict(self.plan.seats)))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def clear_undo(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def undo(self) -> None:
        self._step(self._undo, self._redo)

    def redo(self) -> None:
        self._step(self._redo, self._undo)

    def _step(self, source: list, target: list) -> None:
        if not source:
            return
        layout_id, seats = source.pop()
        current = self.seating.plan(layout_id)
        if current is None:  # the plan was deleted meanwhile
            self.clear_undo()
            return
        target.append((layout_id, dict(current.seats)))
        self.seating.set_seats(layout_id, seats)
        self.layout_id = layout_id
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
        self.fill_button.setEnabled(bool(plan.unseated and plan.free_seats))
        self.shuffle_button.setEnabled(bool(plan.students))
        self.clear_button.setEnabled(bool(plan.seats))

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
