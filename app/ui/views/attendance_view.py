from datetime import date

from PySide6.QtCore import QDate, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.models import AttendanceStatus
from app.services.attendance import (
    UNMARKED,
    AttendanceError,
    AttendanceService,
    DayRegister,
    RegisterRow,
    school_day,
)
from app.services.roster import RosterService
from app.ui import style

STATUSES = (AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED)
KEYS = {Qt.Key.Key_P: STATUSES[0], Qt.Key.Key_L: STATUSES[1], Qt.Key.Key_A: STATUSES[2], Qt.Key.Key_E: STATUSES[3]}
COL_NO, COL_NAME, COL_STATUS, COL_NOTE, COL_RECENT = range(5)


def _fill(widget: QWidget, name: str) -> QColor:
    """A status colour strong enough to carry white text (amber is darkened in light mode)."""
    value = style.color(widget, name)
    return value.darker(125) if name == "warn" and not style.is_dark(widget) else value


def _rgba(color: QColor) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


class StatusButtons(QWidget):
    """Present / Late / Absent / Excused for one student. Clicking the chosen one again clears it."""

    status_clicked = Signal(object)  # AttendanceStatus, or None to clear

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        self.buttons: dict[AttendanceStatus, QToolButton] = {}
        self.status: AttendanceStatus | None = None
        for status in STATUSES:
            button = QToolButton()
            button.setText(status.value.capitalize())
            button.setToolTip(f"{status.value.capitalize()} (key {status.value[0].upper()})")
            button.setCheckable(True)
            button.setProperty("status", status.value)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keys go to the table
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, s=status: self._clicked(s))
            layout.addWidget(button)
            self.buttons[status] = button

    def set_status(self, status: AttendanceStatus | None) -> None:
        self.status = status
        for s, button in self.buttons.items():
            button.setChecked(s is status)

    def _clicked(self, status: AttendanceStatus) -> None:
        self.set_status(self.status)  # the page decides; don't let Qt toggle on its own
        self.status_clicked.emit(None if status is self.status else status)


class AttendanceView(QWidget):
    """Take attendance for the current class, one day and one register at a time.

    Every click is saved straight away. The register is the daily (homeroom) one
    unless the teacher picks a subject; the choice is remembered per class.
    """

    def __init__(self, attendance: AttendanceService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.attendance = attendance
        self.roster = roster
        self.class_id: int | None = None
        self.register: DayRegister | None = None
        self._subject_for_class: dict[int, int | None] = {}
        self._row_widgets: list[tuple[StatusButtons, QLineEdit]] = []

        # --- header ---
        self.date_label = style.caption("")
        self.title_label = style.label("", 1.9)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(self.date_label)
        titles.addWidget(self.title_label)

        self.register_combo = QComboBox()
        self.register_combo.setMinimumWidth(180)
        self.register_combo.currentIndexChanged.connect(self._register_changed)
        register_label = QLabel("&Register")
        register_label.setBuddy(self.register_combo)

        header = QHBoxLayout()
        header.addLayout(titles)
        header.addStretch()
        header.addWidget(register_label, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.register_combo, alignment=Qt.AlignmentFlag.AlignBottom)

        # --- day page ---
        self.prev_button = QPushButton("‹")
        self.prev_button.setToolTip("Previous school day (Alt+Left)")
        self.prev_button.setFixedWidth(36)
        self.prev_button.clicked.connect(lambda: self.set_day(school_day(self.day, -1)))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("ddd d MMM yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.dateChanged.connect(lambda _d: self.refresh())
        self.next_button = QPushButton("›")
        self.next_button.setToolTip("Next school day (Alt+Right)")
        self.next_button.setFixedWidth(36)
        self.next_button.clicked.connect(lambda: self.set_day(school_day(self.day, 1)))
        self.today_button = QPushButton("Today")
        self.today_button.clicked.connect(lambda: self.set_day(date.today()))

        date_row = QHBoxLayout()
        date_row.setSpacing(4)
        date_row.addWidget(self.prev_button)
        date_row.addWidget(self.date_edit)
        date_row.addWidget(self.next_button)
        date_row.addSpacing(8)
        date_row.addWidget(self.today_button)
        date_row.addStretch()
        date_row.addWidget(style.label("Every change is saved as you go", 0.9, muted=True))

        # totals
        totals = QFrame()
        totals.setObjectName("Panel")
        totals_layout = QHBoxLayout(totals)
        totals_layout.setContentsMargins(0, 0, 0, 0)
        totals_layout.setSpacing(0)
        self.count_labels: dict[str, QLabel] = {}
        self.swatches: list[tuple[QLabel, str | None]] = []
        for key, name in [(s.value, s.value.capitalize()) for s in STATUSES] + [(UNMARKED, "Not marked")]:
            self.count_labels[key] = self._add_total(totals_layout, name, style.STATUS_COLOR.get(key))
        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedWidth(1)
        totals_layout.addWidget(line)
        self.rate_label = self._add_total(totals_layout, "Attendance", None, swatch=False)

        # actions
        self.status_label = style.label("", bold=True)
        self.clear_button = QPushButton("Clear the day…")
        self.clear_button.clicked.connect(self.clear_day)
        self.mark_rest_button = QPushButton("Mark the rest present")
        self.mark_rest_button.setObjectName("Primary")
        self.mark_rest_button.clicked.connect(self.mark_rest_present)
        actions = QHBoxLayout()
        actions.addWidget(self.status_label, stretch=1)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.mark_rest_button)

        # students
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["No.", "Student", "Status", "Note", "Last 30 days"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(COL_NO, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(COL_NOTE, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(COL_RECENT, QHeaderView.ResizeMode.ResizeToContents)
        self.table.installEventFilter(self)

        keys_hint = style.label(
            "Keys: ↑ ↓ move · P L A E mark and go to the next student · Delete clears · "
            "N writes a note · Alt+← → change day",
            0.85,
            muted=True,
        )
        keys_hint.setWordWrap(True)

        day_page = QWidget()
        day_layout = QVBoxLayout(day_page)
        day_layout.setContentsMargins(0, 12, 0, 0)
        day_layout.setSpacing(12)
        day_layout.addLayout(date_row)
        day_layout.addWidget(totals)
        day_layout.addLayout(actions)
        day_layout.addWidget(self.table, stretch=1)
        day_layout.addWidget(keys_hint)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(day_page, "Day")

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 16)
        content_layout.setSpacing(12)
        content_layout.addLayout(header)
        content_layout.addWidget(self.tabs, stretch=1)

        # --- empty state (no class yet) ---
        empty_label = QLabel("<h2>No class selected</h2><p>Create a class to take attendance.</p>")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.pages = QStackedWidget()
        self.pages.addWidget(empty_label)
        self.pages.addWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pages)

        for keys, step in (("Alt+Left", -1), ("Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda step=step: self.set_day(school_day(self.day, step)))

        self._apply_style()

    def _add_total(self, layout: QHBoxLayout, name: str, color: str | None, swatch: bool = True) -> QLabel:
        cell = QVBoxLayout()
        cell.setContentsMargins(20, 14, 20, 14)
        cell.setSpacing(4)
        title = QHBoxLayout()
        title.setSpacing(6)
        if swatch:
            box = QLabel()
            box.setFixedSize(10, 10)
            self.swatches.append((box, color))
            title.addWidget(box)
        title.addWidget(style.label(name, 0.92, muted=True))
        title.addStretch()
        value = style.label("—", 1.9)
        cell.addLayout(title)
        cell.addWidget(value)
        layout.addLayout(cell, stretch=1)
        return value

    # --- page interface (see MainWindow) --------------------------------------

    @property
    def day(self) -> date:
        return self.date_edit.date().toPython()

    @property
    def subject_id(self) -> int | None:
        return self.register_combo.currentData()

    def set_class(self, class_id: int | None) -> None:
        self.class_id = class_id
        self._fill_registers()
        self.refresh()

    def set_subject(self, _subject_id: int | None) -> None:
        """Called when subjects change; the register picker keeps its own choice."""
        self._fill_registers()

    def set_day(self, day: date) -> None:
        self.date_edit.setDate(QDate(day.year, day.month, day.day))  # dateChanged refreshes

    def _fill_registers(self) -> None:
        wanted = self._subject_for_class.get(self.class_id or 0)
        self.register_combo.blockSignals(True)
        self.register_combo.clear()
        self.register_combo.addItem("Daily (homeroom)", None)
        for subject in self.roster.list_subjects(self.class_id) if self.class_id is not None else []:
            self.register_combo.addItem(subject.name, subject.id)
        self.register_combo.setCurrentIndex(max(0, self.register_combo.findData(wanted)))
        self.register_combo.blockSignals(False)

    def _register_changed(self) -> None:
        if self.class_id is not None:
            self._subject_for_class[self.class_id] = self.subject_id
        self.refresh()

    # --- loading -------------------------------------------------------------

    def refresh(self) -> None:
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if school_class is None:
            self.register = None
            self.pages.setCurrentIndex(0)
            return
        self.pages.setCurrentIndex(1)
        day = self.day
        self.date_label.setText(f"{day:%A}, {day.day} {day:%B} {day.year}".upper())
        self.title_label.setText(f"Attendance · {school_class.name}")
        self.today_button.setEnabled(day != date.today())

        self.register = self.attendance.day_register(school_class.id, day, self.subject_id)
        ids = [row.student.id for row in self.register.rows]
        if ids != self._shown_ids():
            self._build_rows(len(ids))
        for i, row in enumerate(self.register.rows):
            self._fill_row(i, row)
        self._show_totals()

    def _shown_ids(self) -> list[int]:
        ids = []
        for i in range(self.table.rowCount()):
            item = self.table.item(i, COL_NAME)
            ids.append(item.data(Qt.ItemDataRole.UserRole) if item else None)
        return ids

    def _build_rows(self, count: int) -> None:
        current = max(0, self.table.currentRow())
        self.table.clearContents()
        self.table.setRowCount(count)
        self._row_widgets = []
        for i in range(count):
            for col in (COL_NO, COL_NAME, COL_RECENT):
                self.table.setItem(i, col, QTableWidgetItem())
            buttons = StatusButtons()
            buttons.status_clicked.connect(lambda status, i=i: self._set_status(i, status))
            note = QLineEdit()
            note.setFrame(False)
            note.editingFinished.connect(lambda i=i: self._save_note(i))
            note.installEventFilter(self)
            self.table.setCellWidget(i, COL_STATUS, buttons)
            self.table.setCellWidget(i, COL_NOTE, note)
            self._row_widgets.append((buttons, note))
        if count:
            self.table.setCurrentCell(min(current, count - 1), COL_NAME)

    def _fill_row(self, i: int, row: RegisterRow) -> None:
        student = row.student
        unmarked = row.status is None
        tint = style.soft(self, "warn") if unmarked else None

        number = self.table.item(i, COL_NO)
        number.setText(student.student_no or "")
        name = self.table.item(i, COL_NAME)
        name.setText(student.full_name)
        name.setData(Qt.ItemDataRole.UserRole, student.id)
        name.setToolTip("Not marked yet" if unmarked else "")
        recent = self.table.item(i, COL_RECENT)
        recent.setText(row.recent_text or "—")
        recent.setToolTip(f"Days in the last 30 up to {self.day.day} {self.day:%b}")
        font = recent.font()
        font.setBold(bool(row.recent_tone))
        recent.setFont(font)
        if row.recent_tone:
            recent.setForeground(_fill(self, row.recent_tone))
        else:
            recent.setData(Qt.ItemDataRole.ForegroundRole, None)
        for item in (number, name, recent):
            if tint:
                item.setBackground(tint)
            else:
                item.setData(Qt.ItemDataRole.BackgroundRole, None)

        buttons, note = self._row_widgets[i]
        buttons.set_status(row.status)
        note.setEnabled(not unmarked)
        note.setPlaceholderText("Mark first to add a note" if unmarked else "Add a note")
        if not note.hasFocus():
            note.setText(row.note)

    def _show_totals(self) -> None:
        counts = self.register.counts()
        for key, value in self.count_labels.items():
            value.setText(str(counts[key]))
        rate = self.register.rate
        self.rate_label.setText("—" if rate is None else f"{rate:.0f}%")

        total, unmarked = len(self.register.rows), counts[UNMARKED]
        if not total:
            text, tone = "No active students in this class. Add them on Manage classes.", None
        elif unmarked:
            noun = "student is" if unmarked == 1 else "students are"
            text, tone = f"{unmarked} {noun} not marked yet. They don't count as present.", "warn"
        else:
            text, tone = "Everyone is marked.", "accent"
        self.status_label.setText(text)
        if tone:
            style.set_color(self.status_label, _fill(self, tone))
        else:
            self.status_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.mark_rest_button.setEnabled(unmarked > 0)
        self.clear_button.setEnabled(unmarked < total)

    # --- actions -------------------------------------------------------------

    def _set_status(self, i: int, status: AttendanceStatus | None) -> None:
        row = self.register.rows[i]
        if status is None and row.note:
            answer = QMessageBox.question(
                self,
                "Clear mark",
                f"Clear {row.student.full_name}'s mark for this day? The note \"{row.note}\" goes with it.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            if status is None:
                self.attendance.clear(row.student.id, self.day, self.subject_id)
            else:
                self.attendance.mark(row.student.id, self.day, status, self.subject_id)
        except AttendanceError as exc:
            QMessageBox.information(self, "Attendance", str(exc))
        self.refresh()

    def _save_note(self, i: int) -> None:
        if self.register is None or i >= len(self.register.rows):
            return
        row = self.register.rows[i]
        text = self._row_widgets[i][1].text().strip()
        if row.status is None or text == row.note:
            return
        try:
            self.attendance.set_note(row.student.id, self.day, text, self.subject_id)
        except AttendanceError as exc:
            QMessageBox.information(self, "Attendance", str(exc))
        row.note = text  # editingFinished can fire twice (Return, then losing focus)

    def mark_rest_present(self) -> None:
        if self.class_id is None:
            return
        self.attendance.mark_unmarked(self.class_id, self.day, self.subject_id)
        self.refresh()

    def clear_day(self) -> None:
        if self.class_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Clear the day",
            f"Remove every mark and note for {self.day:%A} {self.day.day} {self.day:%B} "
            f"in the {self.register_combo.currentText()} register?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.attendance.clear_day(self.class_id, self.day, self.subject_id)
            self.refresh()

    # --- keyboard ------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress or self.register is None:
            return super().eventFilter(watched, event)
        key = event.key()
        plain = not (event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier)
        if watched is self.table and plain:
            i = self.table.currentRow()
            if 0 <= i < len(self.register.rows):
                if key in KEYS:
                    self._set_status(i, KEYS[key])
                    self.table.setCurrentCell(min(i + 1, self.table.rowCount() - 1), COL_NAME)
                    return True
                if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._set_status(i, None)
                    return True
                if key in (Qt.Key.Key_N, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    note = self._row_widgets[i][1]
                    if note.isEnabled():
                        note.setFocus()
                        note.selectAll()
                    return True
        elif isinstance(watched, QLineEdit) and key in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            i = next(n for n, (_b, note) in enumerate(self._row_widgets) if note is watched)
            if key == Qt.Key.Key_Escape:
                watched.setText(self.register.rows[i].note)
            self.table.setFocus()  # editingFinished saves the note
            self.table.setCurrentCell(i, COL_NAME)
            return True
        return super().eventFilter(watched, event)

    # --- Qt events -----------------------------------------------------------

    def showEvent(self, event) -> None:
        # Students may have been added, moved or deactivated on other pages meanwhile.
        super().showEvent(event)
        self.refresh()
        self.table.setFocus()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._apply_style()
            if self.register is not None:
                self.refresh()

    def _apply_style(self) -> None:
        line = style.border(self).name()
        rules = [style.card_stylesheet(self)]
        rules.append(
            f"""
            StatusButtons QToolButton {{
                background: palette(base); border: 1px solid {line}; border-radius: 6px;
                padding: 3px 10px;
            }}
            """
        )
        for status in STATUSES:
            name = style.STATUS_COLOR[status.value]
            fill = _fill(self, name).name()
            rules.append(
                f"""
                StatusButtons QToolButton[status="{status.value}"]:hover {{ background: {_rgba(style.soft(self, name))}; }}
                StatusButtons QToolButton[status="{status.value}"]:checked {{
                    background: {fill}; border-color: {fill}; color: {style.on_color(self)}; font-weight: 600;
                }}
                """
            )
        self.setStyleSheet("\n".join(rules))
        for box, name in self.swatches:
            if name:
                box.setStyleSheet(f"background: {_fill(self, name).name()}; border-radius: 2px;")
            else:
                box.setStyleSheet(f"border: 1px solid {line}; border-radius: 2px;")
