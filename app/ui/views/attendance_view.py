import calendar
from datetime import date

from PySide6.QtCore import QDate, QEvent, QObject, QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
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

from app.models import AttendanceRecord, AttendanceStatus
from app.services.attendance import (
    DAYS_AHEAD,
    EARLIEST_DAY,
    LOW_RATE,
    NOTE_MAX,
    RECENT_DAYS,
    STREAK_SHOWN,
    UNMARKED,
    AttendanceError,
    AttendanceService,
    DayRegister,
    MonthRegister,
    RegisterRow,
    day_warning,
    school_day,
    school_days,
)
from app.services.export import (
    absence_report,
    attendance_month_html,
    attendance_month_tsv,
    attendance_period_html,
    write_attendance_csv,
    write_attendance_summary_csv,
)
from app.services.roster import RosterService, matches, number_key
from app.ui import style
from app.ui.dialogs.attendance_history_dialog import AttendanceHistoryDialog
from app.ui.dialogs.mark_days_dialog import MarkDaysDialog
from app.ui.dialogs.period_dialog import PeriodDialog
from app.ui.files import ask_save_path, write_pdf

STATUSES = (AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED)
KEYS = {Qt.Key.Key_P: STATUSES[0], Qt.Key.Key_L: STATUSES[1], Qt.Key.Key_A: STATUSES[2], Qt.Key.Key_E: STATUSES[3]}
# 1 to 4 in the buttons' order, for the number pad; Space for the most common mark
KEYS |= {Qt.Key.Key_1: STATUSES[0], Qt.Key.Key_2: STATUSES[1], Qt.Key.Key_3: STATUSES[2], Qt.Key.Key_4: STATUSES[3]}
KEYS[Qt.Key.Key_Space] = AttendanceStatus.PRESENT
COL_NO, COL_NAME, COL_STATUS, COL_NOTE, COL_RECENT = range(5)
UNDO_LIMIT = 50
REGISTER_NAME = Qt.ItemDataRole.UserRole + 1  # a register's name without its teacher
NAMED_UNMARKED = 3  # this few students left to mark are named in the status line
NOT_TAKEN_NAMED = 8  # school days without a register named on the Month tab before "and N more"


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


class MonthView(QWidget):
    """A month at a glance: students down the side, school days across, totals at the end."""

    day_requested = Signal(object)  # a date to open on the Day tab
    mark_requested = Signal(int, object, object)  # student id, date, AttendanceStatus or None to clear
    history_requested = Signal(int)  # a student whose history to show

    def __init__(self, attendance: AttendanceService, parent: QWidget | None = None):
        super().__init__(parent)
        self.attendance = attendance
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self.file_label = ""  # e.g. "7B (2026-27) Maths", for the export file name
        self._today = date.today  # replaceable in tests
        today = self._today()
        self.year, self.month = today.year, today.month
        self.register: MonthRegister | None = None
        self._scrolled_to: tuple[int, int] | None = None  # the month last scrolled to today

        self.prev_button = QPushButton("‹")
        self.prev_button.setToolTip("Previous month (Alt+Left or Page Up)")
        self.prev_button.setFixedWidth(36)
        self.prev_button.clicked.connect(lambda: self.step(-1))
        self.month_label = style.label("", 1.1, bold=True)
        self.month_label.setMinimumWidth(130)
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_button = QPushButton("›")
        self.next_button.setToolTip("Next month (Alt+Right or Page Down)")
        self.next_button.setFixedWidth(36)
        self.next_button.clicked.connect(lambda: self.step(1))
        self.this_month_button = QPushButton("This month")
        self.this_month_button.setToolTip("Go to this month (Alt+Home)")
        self.this_month_button.clicked.connect(lambda: self.set_month(self._today().year, self._today().month))
        self.export_button = QPushButton("Export CSV…")
        self.export_button.setToolTip("Save this month as a CSV file for Excel or other programs")
        self.export_button.clicked.connect(self.export_csv)
        self.export_period_button = QPushButton("Export period…")
        self.export_period_button.setToolTip("Save each student's totals for any dates, e.g. a term, as CSV")
        self.export_period_button.clicked.connect(self.export_period)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setToolTip("Copy this month as a table, to paste into a spreadsheet")
        self.copy_button.clicked.connect(self.copy_table)
        self.pdf_button = QPushButton("Save PDF…")
        self.pdf_button.setToolTip("Save this month as a PDF to print or share")
        self.pdf_button.clicked.connect(self.save_pdf)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        toolbar.addWidget(self.prev_button)
        toolbar.addWidget(self.month_label)
        toolbar.addWidget(self.next_button)
        toolbar.addSpacing(8)
        toolbar.addWidget(self.this_month_button)
        toolbar.addSpacing(16)
        self.legend: list[tuple[QLabel, str | None]] = []
        for text, letter, name in (
            ("Present", "", "accent"), ("Late", "L", "warn"), ("Absent", "A", "danger"),
            ("Excused", "E", "info"), ("Not marked", "·", None),
        ):  # fmt: skip
            box = QLabel(letter)
            box.setFixedSize(16, 16)
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.legend.append((box, name))
            toolbar.addWidget(box)
            toolbar.addWidget(style.label(text, 0.9, muted=True))
            toolbar.addSpacing(8)
        toolbar.addStretch()
        toolbar.addWidget(self.copy_button)
        toolbar.addWidget(self.pdf_button)
        toolbar.addWidget(self.export_period_button)
        toolbar.addWidget(self.export_button)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setWordWrap(False)
        self.table.cellDoubleClicked.connect(self._open_cell)
        self.table.horizontalHeader().sectionDoubleClicked.connect(lambda col: self._open_cell(-1, col))
        self.table.installEventFilter(self)  # Enter opens the selected day
        for keys, months in (("PgUp", -1), ("PgDown", 1)):  # the month has no pages to scroll
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda months=months: self.step(months))

        hint = style.label(
            "Hover over a mark to see its note; P L A E (or 1 2 3 4) mark the selected cell and Delete clears it; "
            "double-click a day (or press Enter) to open its register, or a name (or press H) for the student's history. "
            "The rate counts present and late out of the "
            "days marked; excused days count neither way, as on the dashboard.",
            0.85,
            muted=True,
        )
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(toolbar)
        self.not_taken_label = style.label("", 0.9, bold=True)
        self.not_taken_label.setWordWrap(True)
        self.not_taken_label.hide()

        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.not_taken_label)
        layout.addWidget(hint)

    def load(self, class_id: int, subject_id: int | None, file_label: str) -> None:
        self.class_id, self.subject_id, self.file_label = class_id, subject_id, file_label
        self.refresh()

    def set_month(self, year: int, month: int) -> None:
        if (year, month) != (self.year, self.month):
            self.year, self.month = year, month
            self.refresh()

    def step(self, months: int) -> None:
        index = self.year * 12 + self.month - 1 + months
        self.set_month(index // 12, index % 12 + 1)

    def refresh(self) -> None:
        if self.class_id is None:
            return
        first = date(self.year, self.month, 1)
        self.month_label.setText(f"{first:%B} {first.year}")
        today = self._today()
        self.this_month_button.setEnabled((self.year, self.month) != (today.year, today.month))
        self.register = self.attendance.month_register(self.class_id, self.year, self.month, self.subject_id)
        row, col = self.table.currentRow(), self.table.currentColumn()
        self._fill()
        if row >= 0 and col >= 0:  # keep the place after a mark
            self.table.setCurrentCell(min(row, self.table.rowCount() - 1), min(col, self.table.columnCount() - 1))
        if (self.year, self.month) != self._scrolled_to:  # a month just opened: show today, when in it
            self._scrolled_to = (self.year, self.month)
            if today in self.register.days and self.register.rows:
                item = self.table.item(0, 1 + self.register.days.index(today))
                self.table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _fill(self) -> None:
        register = self.register
        days, recorded = register.days, set(register.recorded_days)
        totals = ("Abs.", "Late", "Exc.", "Not m.", "Rate")
        first_total = 1 + len(days)
        self.table.clear()
        self.table.setColumnCount(first_total + len(totals))
        self.table.setRowCount(len(register.rows) + 1)
        palette = self.palette()
        muted = style.mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text), 0.5)
        # weekend days are listed only when marked; their shading tells them apart from school days
        weekend = style.mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text), 0.08)

        self.table.setHorizontalHeaderItem(0, QTableWidgetItem("Student"))
        today = self._today()
        for col, day in enumerate(days, start=1):
            item = QTableWidgetItem(f"{day:%a}"[:2] + f"\n{day.day}")
            note = " (today)" if day == today else " (weekend)" if day.weekday() >= 5 else ""
            item.setToolTip(f"{day:%A} {day.day} {day:%B}{note} · double-click to open")
            if day == today:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setForeground(_fill(self, "accent"))
            elif day not in recorded:
                item.setForeground(muted)
            self.table.setHorizontalHeaderItem(col, item)
        for col, text in enumerate(totals, start=first_total):
            self.table.setHorizontalHeaderItem(col, QTableWidgetItem(text))
        self.table.horizontalHeaderItem(first_total + 3).setToolTip(
            "Not marked: days the register was taken on which the student has no mark"
        )

        looks = {
            s: (style.soft(self, "accent") if s is AttendanceStatus.PRESENT else _fill(self, style.STATUS_COLOR[s.value]))
            for s in STATUSES
        }
        on_color = QColor(style.on_color(self))
        for r, row in enumerate(register.rows):
            name = QTableWidgetItem(row.student.full_name)
            self.table.setItem(r, 0, name)
            for col, day in enumerate(days, start=1):
                status = row.statuses.get(day)
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if status is None:
                    item.setText("·")
                    item.setForeground(muted)
                    if day.weekday() >= 5:
                        item.setBackground(weekend)
                else:
                    item.setBackground(looks[status])
                    if status is not AttendanceStatus.PRESENT:
                        item.setText(status.value[0].upper())
                        item.setForeground(on_color)
                word = status.value.capitalize() if status else "Not marked"
                note = row.notes.get(day)
                item.setToolTip(
                    f"{row.student.full_name}, {day:%a} {day.day} {day:%b}: {word}" + (f"\nNote: {note}" if note else "")
                )
                self.table.setItem(r, col, item)
            counts, rate, gaps = row.counts(), row.rate, register.unmarked(row)
            values = (counts["absent"], counts["late"], counts["excused"], gaps or "–",
                      "—" if rate is None else f"{rate:.0f}%")  # fmt: skip
            for col, value in enumerate(values, start=first_total):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == first_total and counts["absent"] >= 2:
                    item.setForeground(_fill(self, "danger"))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                elif col == first_total + 3:
                    item.setForeground(_fill(self, "warn") if gaps else muted)
                elif col == first_total + 4 and rate is not None and rate < LOW_RATE:
                    item.setForeground(_fill(self, "warn"))
                    item.setToolTip(f"Under {LOW_RATE:.0f}%")
                self.table.setItem(r, col, item)

        # last row: how many were absent each day, and the class's totals
        last = len(register.rows)
        bold = self.table.font()
        bold.setBold(True)
        label = QTableWidgetItem("Absent that day")
        label.setFont(bold)
        self.table.setItem(last, 0, label)
        for col, day in enumerate(days, start=1):
            n = register.absent_on(day)
            item = QTableWidgetItem(("–" if n == 0 else str(n)) if day in recorded else "")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if n:
                absent = [r.student.full_name for r in register.rows if r.statuses.get(day) is AttendanceStatus.ABSENT]
                item.setToolTip(f"Absent {day:%a} {day.day} {day:%b}: " + ", ".join(absent))
            item.setForeground(_fill(self, "danger") if n else muted)
            self.table.setItem(last, col, item)
        counts, rate = register.counts(), register.rate
        gaps = sum(register.unmarked(row) for row in register.rows)
        values = (counts["absent"], counts["late"], counts["excused"], gaps or "–",
                  "—" if rate is None else f"{rate:.0f}%")  # fmt: skip
        for col, value in enumerate(values, start=first_total):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setFont(bold)
            self.table.setItem(last, col, item)

        head = self.table.horizontalHeader()
        head.setMinimumSectionSize(24)
        head.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, first_total):
            self.table.setColumnWidth(col, 27)
        for col in range(first_total, first_total + len(totals)):
            head.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.export_button.setEnabled(bool(register.rows))
        self.pdf_button.setEnabled(bool(register.rows))
        self.copy_button.setEnabled(bool(register.rows))
        self._show_not_taken()

    def _show_not_taken(self) -> None:
        """Name the school days so far without a register, e.g. a forgotten Monday."""
        days = self.register.not_taken(self._today()) if self.register.rows else []
        if days:
            listed = ", ".join(f"{day:%a} {day.day}" for day in days[:NOT_TAKEN_NAMED])
            if len(days) > NOT_TAKEN_NAMED:
                listed += f" and {len(days) - NOT_TAKEN_NAMED} more"
            self.not_taken_label.setText(
                f"No register taken on {listed}. Double-click a day to take it (holidays need none)."
            )
            style.set_color(self.not_taken_label, _fill(self, "warn"))
        self.not_taken_label.setVisible(bool(days))

    def _open_cell(self, row: int, col: int) -> None:
        """A day opens its register; a student's name opens their history."""
        if self.register is None:
            return
        if 1 <= col <= len(self.register.days):
            self.day_requested.emit(self.register.days[col - 1])
        elif col == 0 and 0 <= row < len(self.register.rows):
            self.history_requested.emit(self.register.rows[row].student.id)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.table and event.type() == QEvent.Type.KeyPress:
            key, row, col = event.key(), self.table.currentRow(), self.table.currentColumn()
            plain = not (event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier)
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._open_cell(row, col)
                return True
            if plain and key == Qt.Key.Key_H and self.register is not None and 0 <= row < len(self.register.rows):
                self.history_requested.emit(self.register.rows[row].student.id)  # as on the Day tab
                return True
            cell = self._cell(row, col)
            if plain and cell is not None and (key in KEYS or key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)):
                student_id, day = cell
                self.mark_requested.emit(student_id, day, KEYS.get(key))
                if key in KEYS:  # on to the next student, as on the Day tab
                    self.table.setCurrentCell(min(row + 1, len(self.register.rows) - 1), col)
                return True
        return super().eventFilter(watched, event)

    def _cell(self, row: int, col: int) -> tuple[int, date] | None:
        """(student id, day) of a mark cell of the table, None for names, totals and the last row."""
        if self.register is None or not 0 <= row < len(self.register.rows) or not 1 <= col <= len(self.register.days):
            return None
        return self.register.rows[row].student.id, self.register.days[col - 1]

    def export_csv(self) -> None:
        if self.register is None:
            return
        first = date(self.year, self.month, 1)
        name = f"{self.file_label} attendance {first:%B} {first.year}"
        path = ask_save_path(self, "Export attendance", name, "CSV files", ".csv")
        if path is None:
            return
        try:
            write_attendance_csv(path, self.register)
        except OSError as exc:
            QMessageBox.warning(self, "Export attendance", f"The file could not be saved:\n{exc}")
            return
        QMessageBox.information(self, "Export attendance", f"Saved {first:%B} {first.year} to\n{path}")

    def copy_table(self) -> None:
        if self.register is not None:
            QApplication.clipboard().setText(attendance_month_tsv(self.register))

    def save_pdf(self) -> None:
        """Save the month register as a landscape A4 PDF, ready to print."""
        if self.register is None:
            return
        first = date(self.year, self.month, 1)
        title = f"{self.file_label} · attendance {first:%B} {first.year}"
        name = f"{self.file_label} attendance {first:%B} {first.year}"
        path = ask_save_path(self, "Save PDF", name, "PDF files", ".pdf")
        if path is not None and write_pdf(self, path, title, attendance_month_html(self.register, title), True):
            QMessageBox.information(self, "Save PDF", f"Saved {first:%B} {first.year} to\n{path}")

    def export_period(self) -> None:
        """Ask for the first and last day, then save each student's totals for them."""
        if self.class_id is None:
            return
        first = date(self.year, self.month, 1)
        last = date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])
        dialog = PeriodDialog("Export attendance for a period", first, last, self)
        if not dialog.exec():
            return
        start, end = dialog.start, dialog.end
        try:
            summary = self.attendance.period_summary(self.class_id, start, end, self.subject_id)
        except AttendanceError as exc:
            QMessageBox.information(self, "Export attendance", str(exc))
            return
        name = f"{self.file_label} attendance {start} to {end}"
        days = summary.recorded_days
        recorded = f"{days} recorded day{'' if days == 1 else 's'}"
        if dialog.as_pdf:
            title = f"{self.file_label} · attendance {start.day} {start:%b %Y} to {end.day} {end:%b %Y}"
            path = ask_save_path(self, "Save PDF", name, "PDF files", ".pdf")
            if path is not None and write_pdf(self, path, title, attendance_period_html(summary, title), False):
                QMessageBox.information(self, "Save PDF", f"Saved {recorded} to\n{path}")
            return
        path = ask_save_path(self, "Export attendance", name, "CSV files", ".csv")
        if path is None:
            return
        try:
            write_attendance_summary_csv(path, summary)
        except OSError as exc:
            QMessageBox.warning(self, "Export attendance", f"The file could not be saved:\n{exc}")
            return
        QMessageBox.information(self, "Export attendance", f"Saved {recorded} to\n{path}")

    def apply_style(self) -> None:
        line = style.border(self).name()
        # Lines in the background colour keep the coloured cells apart.
        self.table.setStyleSheet("QTableWidget { gridline-color: palette(base); }")
        for box, name in self.legend:
            if name == "accent":
                box.setStyleSheet(f"background: {_rgba(style.soft(self, name))}; border-radius: 3px;")
            elif name:
                box.setStyleSheet(
                    f"background: {_fill(self, name).name()}; color: {style.on_color(self)};"
                    " border-radius: 3px; font-size: 9px; font-weight: 700;"
                )
            else:
                muted = self.palette().color(QPalette.ColorRole.PlaceholderText).name()
                box.setStyleSheet(f"border: 1px solid {line}; border-radius: 3px; color: {muted};")


class AttendanceView(QWidget):
    """Take attendance for the current class, one day and one register at a time.

    Every click is saved straight away. The register is the daily (homeroom) one
    unless the teacher picks a subject; the choice is remembered per class.
    The class picker switches the current class for the whole window.
    """

    class_selected = Signal(int)
    navigate_requested = Signal(str)  # a page name, e.g. "Manage classes"

    def __init__(self, attendance: AttendanceService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.attendance = attendance
        self.roster = roster
        self.class_id: int | None = None
        self.register: DayRegister | None = None
        self._subject_for_class: dict[int, int | None] = {}
        self._row_widgets: list[tuple[StatusButtons, QLineEdit]] = []
        self._month_follows: date | None = None
        self.by_number = False  # the register in student number order instead of by name
        self._clock = date.today  # replaceable in tests
        self._showing_today: date | None = None  # the date, when the day shown was "today"
        self._week: list[tuple[date, int]] = []  # Monday to Friday of the day shown, with students marked
        self._day_timer = QTimer(self)  # the page may stay open on screen past midnight
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(lambda: self.isVisible() and self.follow_today())
        self._day_timer.start()
        # Notes written before in this class, offered in every note field while typing.
        self.note_completer = QCompleter(QStringListModel(self), self)
        self.note_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.note_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        # (subject id, {day: its register before the change}, what the change was), newest last
        self._undo: list[tuple[int | None, dict[date, list[AttendanceRecord]], str]] = []
        self._redo: list[tuple[int | None, dict[date, list[AttendanceRecord]], str]] = []  # changes undone

        # --- header ---
        self.date_label = style.caption("")
        self.title_label = style.label("", 1.9)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(self.date_label)
        titles.addWidget(self.title_label)

        self.class_combo = QComboBox()
        self.class_combo.setMinimumWidth(160)
        self.class_combo.activated.connect(self._class_picked)
        class_label = QLabel("C&lass")
        class_label.setBuddy(self.class_combo)

        self.register_combo = QComboBox()
        self.register_combo.setMinimumWidth(180)
        self.register_combo.currentIndexChanged.connect(self._register_changed)
        register_label = QLabel("&Register")
        register_label.setBuddy(self.register_combo)

        header = QHBoxLayout()
        header.addLayout(titles)
        header.addStretch()
        header.addWidget(class_label, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.class_combo, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addSpacing(12)
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
        # the same limits as the service: a mistyped year can't be picked
        self.date_edit.setDateRange(QDate(EARLIEST_DAY), QDate.currentDate().addDays(DAYS_AHEAD))
        self.date_edit.dateChanged.connect(lambda _d: self.refresh())
        self.next_button = QPushButton("›")
        self.next_button.setToolTip("Next school day (Alt+Right)")
        self.next_button.setFixedWidth(36)
        self.next_button.clicked.connect(lambda: self.set_day(school_day(self.day, 1)))
        self.today_button = QPushButton("Today")
        self.today_button.setToolTip("Go to today (Alt+Home)")
        self.today_button.clicked.connect(lambda: self.set_day(date.today()))

        date_row = QHBoxLayout()
        date_row.setSpacing(4)
        date_row.addWidget(self.prev_button)
        date_row.addWidget(self.date_edit)
        date_row.addWidget(self.next_button)
        date_row.addSpacing(8)
        date_row.addWidget(self.today_button)
        date_row.addSpacing(12)
        # the week at a glance: which days are done, and a click to open one
        self.week_buttons: list[QToolButton] = []
        for n in range(5):
            button = QToolButton()
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, n=n: self._open_weekday(n))
            date_row.addWidget(button)
            self.week_buttons.append(button)
        date_row.addStretch()
        date_row.addWidget(style.label("Every change is saved as you go", 0.9, muted=True))
        date_row.addSpacing(12)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find a student (Ctrl+F)")
        self.find_edit.setToolTip("Show only students whose name, number or notes contain this, accents or not; Esc shows everyone")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setFixedWidth(220)
        self.find_edit.textChanged.connect(self._apply_filter)
        self.find_edit.installEventFilter(self)
        date_row.addWidget(self.find_edit)

        self.day_notice = style.label("", bold=True)
        self.day_notice.setWordWrap(True)
        self.day_notice.hide()

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
        self.status_label.setWordWrap(True)  # the buttons beside it leave little room
        self.status_label.linkActivated.connect(self.navigate_requested.emit)
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("Redo")
        self.redo_button.clicked.connect(self.redo)
        self.clear_button = QPushButton("Clear the day…")
        self.clear_button.clicked.connect(self.clear_day)
        self.copy_button = QPushButton("Copy absences")
        self.copy_button.setToolTip(
            "Copy who is absent, late or excused this day, e.g. to send to the school office (Ctrl+Shift+C)"
        )
        self.copy_button.clicked.connect(self.copy_absences)
        self.days_button = QPushButton("Several days…")
        self.days_button.setToolTip("Mark the selected student for several days, e.g. a sick note or a trip (D)")
        self.days_button.clicked.connect(lambda: self.mark_days(self.table.currentRow()))
        self.daily_button = QPushButton("Copy from daily")
        self.daily_button.setToolTip(
            "Mark students who are absent or excused in the daily register the same way here"
        )
        self.daily_button.clicked.connect(self.copy_from_daily)
        self.mark_rest_button = QPushButton("Mark the rest present")
        self.mark_rest_button.setObjectName("Primary")
        self.mark_rest_button.setToolTip("Mark everyone not marked yet as present (Ctrl+Enter)")
        self.mark_rest_button.clicked.connect(self.mark_rest_present)
        actions = QHBoxLayout()
        actions.addWidget(self.status_label, stretch=1)
        actions.addWidget(self.undo_button)
        actions.addWidget(self.redo_button)
        actions.addWidget(self.copy_button)
        actions.addWidget(self.days_button)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.daily_button)
        actions.addWidget(self.mark_rest_button)

        # students
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["No.", "Student", "Status", "Note", f"Last {RECENT_DAYS} days"])
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
        self.table.cellDoubleClicked.connect(lambda row, _col: self.show_history(row))
        head.sectionClicked.connect(self._header_clicked)
        head.setSortIndicatorShown(True)
        head.setSortIndicator(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)

        keys_hint = style.label(
            "Keys: ↑ ↓ move · P L A E (or 1 2 3 4, Space for present) mark and go to the next student · "
            "Delete clears · N writes a note · "
            "U goes to the next one not marked · D marks several days · "
            "H or double-click shows a student's history · Alt+← → change day · Alt+Home goes to today · "
            "F1 lists every key",
            0.85,
            muted=True,
        )
        keys_hint.setWordWrap(True)

        day_page = QWidget()
        day_layout = QVBoxLayout(day_page)
        day_layout.setContentsMargins(0, 12, 0, 0)
        day_layout.setSpacing(12)
        day_layout.addLayout(date_row)
        day_layout.addWidget(self.day_notice)
        day_layout.addWidget(totals)
        day_layout.addLayout(actions)
        day_layout.addWidget(self.table, stretch=1)
        day_layout.addWidget(keys_hint)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(day_page, "&Day")
        self.month_view = MonthView(attendance)
        self.month_view.day_requested.connect(self.open_day)
        self.month_view.mark_requested.connect(self.mark_in_month)
        self.month_view.history_requested.connect(self.show_student_history)
        self.tabs.addTab(self.month_view, "&Month")

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
            shortcut.activated.connect(lambda step=step: self._step(step))
        today = QShortcut(QKeySequence("Alt+Home"), self)
        today.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        today.activated.connect(self._go_to_today)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):  # the main key and the number pad's
            rest = QShortcut(QKeySequence(keys), self)
            rest.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            rest.activated.connect(lambda: self.mark_rest_button.isEnabled() and self.mark_rest_present())
        copy = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        copy.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy.activated.connect(lambda: self.copy_button.isEnabled() and self.copy_absences())
        find = QShortcut(QKeySequence.StandardKey.Find, self)  # like the class list: whole window, page shown
        find.activated.connect(self._start_find)
        undo = QShortcut(QKeySequence.StandardKey.Undo, self)  # a note being typed keeps its own undo
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self.undo)
        # Named, not StandardKey.Redo: on Windows that is Ctrl+Y too, and two equal shortcuts both stop working.
        for keys in ("Ctrl+Y", "Ctrl+Shift+Z"):
            redo = QShortcut(QKeySequence(keys), self)
            redo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            redo.activated.connect(self.redo)
        self._update_undo()

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

    @property
    def register_name(self) -> str:
        """ "Daily (homeroom)" or the subject's name."""
        return self.register_combo.currentData(REGISTER_NAME) or self.register_combo.currentText()

    def set_class(self, class_id: int | None) -> None:
        if class_id != self.class_id:
            self.clear_undo()  # undo stays within one class
            self.find_edit.clear()
        self.class_id = class_id
        self._fill_classes()
        self._fill_registers()
        self.refresh()

    def set_subject(self, _subject_id: int | None) -> None:
        """Called when subjects change; the register picker keeps its own choice."""
        self._fill_registers()

    def _go_to_today(self) -> None:
        """Alt+Home: today, or this month on the Month tab."""
        if self.tabs.currentWidget() is self.month_view:
            self.month_view.this_month_button.click()
        else:
            self.set_day(date.today())

    def _step(self, step: int) -> None:
        """Alt+← / Alt+→: the previous or next school day, or month on the Month tab."""
        if self.tabs.currentWidget() is self.month_view:
            self.month_view.step(step)
        else:
            self.set_day(school_day(self.day, step))

    def set_day(self, day: date) -> None:
        self.date_edit.setDate(QDate(day.year, day.month, day.day))  # dateChanged refreshes

    def open_day(self, day: date) -> None:
        self.tabs.setCurrentIndex(0)
        self.set_day(day)

    def _fill_classes(self) -> None:
        """Every class, newest school year first, then by name."""
        terms = self.roster.list_terms()
        classes = sorted(
            self.roster.list_classes(),
            key=lambda c: terms.index(c.term) if c.term in terms else len(terms),
        )  # stable, so classes stay sorted by name within a year
        self.class_combo.blockSignals(True)
        self.class_combo.clear()
        for school_class in classes:
            self.class_combo.addItem(school_class.display_name, school_class.id)
        self.class_combo.setCurrentIndex(self.class_combo.findData(self.class_id))
        self.class_combo.blockSignals(False)

    def _class_picked(self) -> None:
        class_id = self.class_combo.currentData()
        if class_id is not None and class_id != self.class_id:
            self.class_selected.emit(class_id)

    def _fill_registers(self) -> None:
        wanted = self._subject_for_class.get(self.class_id or 0)
        self.register_combo.blockSignals(True)
        self.register_combo.clear()
        self.register_combo.addItem("Daily (homeroom)", None)
        for subject in self.roster.list_subjects(self.class_id) if self.class_id is not None else []:
            # whose lesson it is, when someone else teaches it; titles and files use the name alone
            label = subject.name + (f" · {subject.teacher}" if subject.teacher else "")
            self.register_combo.addItem(label, subject.id)
            self.register_combo.setItemData(self.register_combo.count() - 1, subject.name, REGISTER_NAME)
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
        self._showing_today = day if day == self._clock() else None
        self.date_label.setText(f"{day:%A}, {day.day} {day:%B} {day.year}".upper())
        register = f" · {self.register_name}" if self.subject_id is not None else ""
        self.title_label.setText(f"Attendance · {school_class.name}{register}")
        self.today_button.setEnabled(day != date.today())
        warning = day_warning(day, date.today())
        self.day_notice.setText(warning or "")
        self.day_notice.setVisible(warning is not None)
        style.set_color(self.day_notice, _fill(self, "warn"))
        file_label = " ".join(x for x in (school_class.display_name, self.subject_id and self.register_name) if x)
        if day != self._month_follows:  # the month follows the day, until changed by hand
            self._month_follows = day
            self.month_view.year, self.month_view.month = day.year, day.month
        self.month_view.load(school_class.id, self.subject_id, file_label)

        self.register = self.attendance.day_register(school_class.id, day, self.subject_id)
        self._show_week(school_class.id)
        if self.by_number:
            self.register.rows.sort(key=lambda row: number_key(row.student))  # stable: by name within
        self.note_completer.model().setStringList(self.attendance.note_suggestions(school_class.id))
        ids = [row.student.id for row in self.register.rows]
        if ids != self._shown_ids():
            self._build_rows(len(ids))
        for i, row in enumerate(self.register.rows):
            self._fill_row(i, row)
        # an empty column is only in the way when the school doesn't number its students
        self.table.setColumnHidden(COL_NO, not any(row.student.student_no for row in self.register.rows))
        self._show_totals()
        self._apply_filter()

    def _header_clicked(self, column: int) -> None:
        if column in (COL_NO, COL_NAME):
            self.set_order(by_number=column == COL_NO)
        else:  # only these two columns sort; keep the indicator where it is
            self.table.horizontalHeader().setSortIndicator(
                COL_NO if self.by_number else COL_NAME, Qt.SortOrder.AscendingOrder
            )

    def set_order(self, by_number: bool) -> None:
        """List the students by number (as the school's list does) or by name."""
        self.by_number = by_number
        self.table.horizontalHeader().setSortIndicator(COL_NO if by_number else COL_NAME, Qt.SortOrder.AscendingOrder)
        self.refresh()

    def _show_week(self, class_id: int) -> None:
        """Mark each weekday button ✓ when everyone is marked, • when some are."""
        students = len(self.register.rows)
        self._week = self.attendance.week_progress(class_id, self.day, self.subject_id)
        for button, (day, marked) in zip(self.week_buttons, self._week):
            sign = " ✓" if students and marked >= students else " •" if marked else ""
            button.setText(f"{day:%a}{sign}")
            button.setChecked(day == self.day)
            state = "everyone marked" if sign == " ✓" else f"{marked} of {students} marked" if marked else "not taken"
            button.setToolTip(f"{day:%A} {day.day} {day:%B}: {state}")

    def _open_weekday(self, n: int) -> None:
        self.set_day(self._week[n][0])
        self.week_buttons[n].setChecked(True)  # also when it was the day shown already

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
            note.setMaxLength(NOTE_MAX)
            note.editingFinished.connect(lambda i=i: self._save_note(i))
            note.installEventFilter(self)
            note.setCompleter(self.note_completer)
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
        number.setText(student.student_no or "—")  # the column only shows when others have one
        number.setToolTip("" if student.student_no else "No student number yet; give one in Manage classes")
        if student.student_no:
            number.setData(Qt.ItemDataRole.ForegroundRole, None)
        else:
            number.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
        name = self.table.item(i, COL_NAME)
        name.setText(student.full_name)
        name.setData(Qt.ItemDataRole.UserRole, student.id)
        tip = ["Not marked yet"] if unmarked else []
        if row.previous:
            day, status = row.previous
            tip.append(f"Last marked {status.value} on {day:%a} {day.day} {day:%b}")
        name.setToolTip("\n".join(tip))
        recent = self.table.item(i, COL_RECENT)
        recent.setText(row.recent_text or "—")
        tip = f"Days in the last {RECENT_DAYS} up to {self.day.day} {self.day:%b}"
        if row.absent_streak >= STREAK_SHOWN:
            tip += f"\nAbsent in each of the last {row.absent_streak} registers taken"
        recent.setToolTip(tip)
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
            note.setCursorPosition(0)  # show the start of a long note
        note.setToolTip(row.note)  # the whole note, when the column is too narrow for it

    def _show_totals(self) -> None:
        counts = self.register.counts()
        for key, value in self.count_labels.items():
            value.setText(str(counts[key]))
        rate = self.register.rate
        self.rate_label.setText("—" if rate is None else f"{rate:.0f}%")
        here = counts["present"] + counts["late"]
        self.rate_label.setToolTip(
            "Present or late, out of the students marked present, late or absent. "
            "Excused and not marked count neither way."
            + ("" if rate is None else f"\nHere: {here} of {here + counts['absent']}.")
        )

        total, unmarked = len(self.register.rows), counts[UNMARKED]
        if not total:
            text, tone = 'No active students in this class. <a href="Manage classes">Add students…</a>', None
        elif 0 < unmarked <= NAMED_UNMARKED and unmarked < total:  # the last few: say who
            names = [row.student.full_name for row in self.register.rows if row.status is None]
            listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
            text, tone = f"Not marked yet: {listed}. They don't count as present.", "warn"
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
        self.daily_button.setVisible(self.subject_id is not None)
        if self.subject_id is not None:
            n = len(self.attendance.daily_to_copy(self.register.class_id, self.day, self.subject_id))
            self.daily_button.setText(f"Copy from daily ({n})" if n else "Copy from daily")
            self.daily_button.setEnabled(n > 0)
        self.clear_button.setEnabled(unmarked < total)
        self.copy_button.setEnabled(unmarked < total)
        self.days_button.setEnabled(total > 0)

    # --- finding a student ---------------------------------------------------

    def _start_find(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def _apply_filter(self) -> None:
        """Hide the students the text in the find box doesn't find, as in the class list."""
        if self.register is None:
            return
        text = self.find_edit.text()
        for i, row in enumerate(self.register.rows):
            self.table.setRowHidden(i, not matches(row.student, text))  # as the class list: "Jose" finds "José"
        if self.table.isRowHidden(self.table.currentRow()) or self.table.currentRow() < 0:
            visible = self._visible_rows()
            if visible:
                self.table.setCurrentCell(visible[0], COL_NAME)

    def _visible_rows(self) -> list[int]:
        return [i for i in range(self.table.rowCount()) if not self.table.isRowHidden(i)]

    def go_to_unmarked(self) -> None:
        """Select the next student shown who isn't marked yet, starting again from the top."""
        if self.register is None:
            return
        visible = self._visible_rows()
        current = self.table.currentRow()
        after = [i for i in visible if i > current] + [i for i in visible if i <= current]
        found = next((i for i in after if self.register.rows[i].status is None), None)
        if found is not None:
            self.table.setCurrentCell(found, COL_NAME)

    def _next_row(self, i: int) -> int:
        """The next row shown after row `i`, or `i` itself at the end."""
        return next((n for n in self._visible_rows() if n > i), i)

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
        if status == row.status:
            return
        name = row.student.full_name
        self._remember(f"clear {name}" if status is None else f"mark {name} {status.value}")
        try:
            if status is None:
                self.attendance.clear(row.student.id, self.day, self.subject_id)
            else:
                self.attendance.mark(row.student.id, self.day, status, self.subject_id)
        except AttendanceError as exc:
            self._forget()
            QMessageBox.information(self, "Attendance", str(exc))
        self.refresh()

    def _save_note(self, i: int) -> None:
        if self.register is None or i >= len(self.register.rows):
            return
        row = self.register.rows[i]
        text = self._row_widgets[i][1].text().strip()
        if row.status is None or text == row.note:
            return
        self._remember(f"note for {row.student.full_name}")
        try:
            self.attendance.set_note(row.student.id, self.day, text, self.subject_id)
        except AttendanceError as exc:
            self._forget()
            self._row_widgets[i][1].setText(row.note)  # show the note that is saved, not the one refused
            QMessageBox.information(self, "Attendance", str(exc))
            return
        row.note = text  # editingFinished can fire twice (Return, then losing focus)

    def mark_rest_present(self) -> None:
        if self.class_id is None:
            return
        day = self.day
        if day > date.today() or day.weekday() >= 5:  # a whole class marked on a wrong day is a lot to undo
            why = "hasn't happened yet" if day > date.today() else "is a weekend day"
            answer = QMessageBox.question(
                self,
                "Mark the rest present",
                f"{day:%A} {day.day} {day:%B} {why}. Mark everyone who isn't marked as present anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._remember("mark the rest present")
        try:
            n = self.attendance.mark_unmarked(self.class_id, self.day, self.subject_id)
        except AttendanceError as exc:
            self._forget()
            QMessageBox.information(self, "Attendance", str(exc))
            return
        self.refresh()
        self.status_label.setText(f"Marked {n} student{'' if n == 1 else 's'} present. {self.status_label.text()}")

    def copy_from_daily(self) -> None:
        """Give students away all day (absent or excused in the daily register) the same mark here."""
        if self.class_id is None or self.subject_id is None:
            return
        self._remember("copy from the daily register")
        try:
            n = self.attendance.copy_from_daily(self.class_id, self.day, self.subject_id)
        except AttendanceError as exc:
            self._forget()
            QMessageBox.information(self, "Attendance", str(exc))
            return
        if not n:
            self._forget()
        self.refresh()
        if n:
            text = f"Marked {n} student{'' if n == 1 else 's'} as in the daily register"
        else:
            text = "No one who isn't marked here is absent or excused in the daily register"
        self.status_label.setText(text)
        style.set_color(self.status_label, _fill(self, "accent" if n else "warn"))

    def clear_day(self) -> None:
        if self.class_id is None:
            return
        rows = self.register.rows if self.register else []
        marks = sum(1 for row in rows if row.status is not None)
        notes = sum(1 for row in rows if row.note)
        what = f"{marks} mark{'' if marks == 1 else 's'}"
        if notes:
            what += f" and {notes} note{'' if notes == 1 else 's'}"
        answer = QMessageBox.question(
            self,
            "Clear the day",
            f"Remove {what} for {self.day:%A} {self.day.day} {self.day:%B} "
            f"in the {self.register_name} register? Undo can bring them back.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._remember("clear the day")
            self.attendance.clear_day(self.class_id, self.day, self.subject_id)
            self.refresh()

    def copy_absences(self) -> None:
        """Put who is absent, late, excused or not marked on the clipboard as text."""
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if self.register is None or school_class is None:
            return
        title = f"{school_class.name} · {self.register_name}"
        QApplication.clipboard().setText(absence_report(self.register, title))
        self.status_label.setText("Copied · paste it into an email or message")
        style.set_color(self.status_label, _fill(self, "accent"))

    def _show_row_menu(self, pos) -> None:
        i = self.table.rowAt(pos.y())
        if self.register is not None and 0 <= i < len(self.register.rows):
            self.table.setCurrentCell(i, COL_NAME)
            menu = self.row_menu(i)
            menu.exec(self.table.viewport().mapToGlobal(pos))
            menu.deleteLater()  # a new one is made for each right-click

    def row_menu(self, i: int) -> QMenu:
        """What can be done for student `i`, for a right-click on their row."""
        row = self.register.rows[i]
        menu = QMenu(self)
        for status in STATUSES:
            action = menu.addAction(f"{status.value.capitalize()}\t{status.value[0].upper()}")
            action.setCheckable(True)
            action.setChecked(row.status is status)
            action.triggered.connect(lambda _checked, s=status: self._set_status(i, s))
        clear = menu.addAction("Clear the mark\tDelete", lambda: self._set_status(i, None))
        clear.setEnabled(row.status is not None)
        menu.addSeparator()
        note = menu.addAction("Write a note\tN", lambda: self._edit_note(i))
        note.setEnabled(row.status is not None)
        menu.addAction("Mark several days…\tD", lambda: self.mark_days(i))
        menu.addAction("Show history…\tH", lambda: self.show_history(i))
        return menu

    def _edit_note(self, i: int) -> None:
        note = self._row_widgets[i][1]
        if note.isEnabled():
            note.setFocus()
            note.selectAll()

    def mark_in_month(self, student_id: int, day: date, status: AttendanceStatus | None) -> None:
        """Mark (or clear) one cell of the Month tab, with undo as on the Day tab."""
        if self.class_id is None:
            return
        row = next((r for r in self.month_view.register.rows if r.student.id == student_id), None)
        if row is None or row.statuses.get(day) == status:
            return
        name = row.student.full_name
        if status is None and row.notes.get(day):
            answer = QMessageBox.question(
                self, "Clear mark", f"Clear {name}'s mark for {day:%a} {day.day} {day:%b}? Its note goes with it."
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        when = f"{day:%a} {day.day}"
        what = f"clear {name} on {when}" if status is None else f"mark {name} {status.value} on {when}"
        self._remember(what, [day])
        try:
            if status is None:
                self.attendance.clear(student_id, day, self.subject_id)
            else:
                self.attendance.mark(student_id, day, status, self.subject_id)
        except AttendanceError as exc:
            self._forget()
            QMessageBox.information(self, "Attendance", str(exc))
        self.refresh()

    def mark_days(self, i: int) -> None:
        """Ask for a period, then mark student `i` on each school day of it."""
        if self.register is None or not 0 <= i < len(self.register.rows):
            return
        student = self.register.rows[i].student
        dialog = MarkDaysDialog(student.full_name, self.register_name, self.day, self)
        if not dialog.exec():
            return
        days = school_days(dialog.start, dialog.end)
        self._remember(f"mark {student.full_name} for {len(days)} days", days)
        try:
            changed = self.attendance.mark_days(
                student.id, dialog.start, dialog.end, dialog.status, dialog.note, self.subject_id, dialog.replace_marks
            )
        except AttendanceError as exc:
            self._forget()
            QMessageBox.information(self, "Attendance", str(exc))
            return
        if not changed:
            self._forget()
        self.refresh()
        n, skipped = len(changed), len(days) - len(changed)
        text = f"Marked {student.full_name} {dialog.status.value} on {n} day{'' if n == 1 else 's'}"
        if skipped:
            text += f" · {skipped} day{'' if skipped == 1 else 's'} already marked kept as before"
        self.status_label.setText(text)
        style.set_color(self.status_label, _fill(self, "accent" if n else "warn"))

    def show_history(self, i: int) -> None:
        """Show student `i`'s marks in this register; a day picked there opens on the Day tab."""
        if self.register is None or not 0 <= i < len(self.register.rows):
            return
        self.show_student_history(self.register.rows[i].student.id)

    def show_student_history(self, student_id: int) -> None:
        """Show a student's marks in the register shown; a day picked there opens on the Day tab."""
        try:
            history = self.attendance.student_history(student_id, self.subject_id)
        except AttendanceError as exc:
            QMessageBox.information(self, "Attendance", str(exc))
            return
        registers = [
            (self.register_combo.itemData(i, REGISTER_NAME) or self.register_combo.itemText(i),
             self.register_combo.itemData(i))
            for i in range(self.register_combo.count())
        ]  # fmt: skip
        dialog = AttendanceHistoryDialog(
            history, self.register_name, self, registers,
            lambda subject_id: self.attendance.student_history(student_id, subject_id), self.subject_id,
        )  # fmt: skip
        if not dialog.exec() or (dialog.chosen_day is None and dialog.chosen_month is None):
            return
        if dialog.chosen_subject != self.subject_id:  # a day or month picked in another register
            self.register_combo.setCurrentIndex(self.register_combo.findData(dialog.chosen_subject))
        if dialog.chosen_day is not None:
            self.open_day(dialog.chosen_day)  # on the Day tab, also when asked from the Month tab
        else:
            self.tabs.setCurrentWidget(self.month_view)
            self.month_view.set_month(dialog.chosen_month.year, dialog.chosen_month.month)

    # --- undo ----------------------------------------------------------------

    def _remember(self, what: str, days: list[date] | None = None) -> None:
        """Keep the register of the days (the day shown by default) as it is now, before a
        change, so undo() can bring it back."""
        if self.class_id is None:
            return
        before = {day: self.attendance.snapshot(self.class_id, day, self.subject_id) for day in days or [self.day]}
        self._undo.append((self.subject_id, before, what))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()  # a new change starts a new line of history
        self._update_undo()

    def clear_undo(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._update_undo()

    def _forget(self) -> None:
        """Drop the last remembered register, when the change it was kept for failed."""
        if self._undo:
            self._undo.pop()
        self._update_undo()

    def undo(self) -> None:
        """Undo the newest change, showing the day and register it was made in."""
        self._step_history(self._undo, self._redo, "Undo")

    def redo(self) -> None:
        """Make the newest change undone again."""
        self._step_history(self._redo, self._undo, "Redo")

    def _step_history(self, source: list, target: list, title: str) -> None:
        """Put back the registers of the newest entry of `source`, keeping how they are now in `target`."""
        if not source or self.class_id is None:
            return
        subject_id, registers, what = source.pop()
        self._update_undo()
        if subject_id != self.subject_id:
            index = self.register_combo.findData(subject_id)
            if index < 0:  # the subject was deleted since
                self._step_history(source, target, title)
                return
            self.register_combo.setCurrentIndex(index)
        if self.day not in registers:
            self.set_day(min(registers))
        now = {day: self.attendance.snapshot(self.class_id, day, subject_id) for day in registers}
        try:
            for day, records in registers.items():
                self.attendance.restore(self.class_id, day, subject_id, records)
        except AttendanceError as exc:
            QMessageBox.information(self, title, str(exc))
        else:
            target.append((subject_id, now, what))
        self._update_undo()
        self.refresh()

    def _update_undo(self) -> None:
        for button, stack, key, name in (
            (self.undo_button, self._undo, QKeySequence.StandardKey.Undo, "Undo"),
            (self.redo_button, self._redo, QKeySequence("Ctrl+Y"), "Redo"),
        ):
            button.setEnabled(bool(stack))
            keys = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
            what = f": {stack[-1][2]}" if stack else ""
            button.setToolTip(f"{name}{what} ({keys})")

    # --- keyboard ------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress or self.register is None:
            return super().eventFilter(watched, event)
        key = event.key()
        plain = not (event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier)
        if watched is self.table and plain:
            i = self.table.currentRow()
            if not self._visible_rows() and key not in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                return True  # the find box matches no one: no key may mark or select a hidden student
            if 0 <= i < len(self.register.rows):
                if key in KEYS:
                    self._set_status(i, KEYS[key])
                    self.table.setCurrentCell(self._next_row(i), COL_NAME)
                    return True
                if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._set_status(i, None)
                    return True
                if key == Qt.Key.Key_H:
                    self.show_history(i)
                    return True
                if key == Qt.Key.Key_D:
                    self.mark_days(i)
                    return True
                if key == Qt.Key.Key_U:
                    self.go_to_unmarked()
                    return True
                if key in (Qt.Key.Key_N, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._edit_note(i)
                    return True
        elif watched is self.find_edit:
            if key in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
                if key == Qt.Key.Key_Escape:
                    self.find_edit.clear()
                self.table.setFocus()  # mark the student found straight away with P L A E
                visible = self._visible_rows()
                if visible and self.table.currentRow() not in visible:
                    self.table.setCurrentCell(visible[0], COL_NAME)
                return True
        elif isinstance(watched, QLineEdit) and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            # to the note above or below, as in a spreadsheet, saving this one first
            # (focus may pass through the suggestions popup, which doesn't count as finishing)
            i = next(n for n, (_b, note) in enumerate(self._row_widgets) if note is watched)
            self.note_completer.popup().hide()
            self._save_note(i)
            visible = self._visible_rows()
            nearby = [n for n in visible if n < i][-1:] if key == Qt.Key.Key_Up else [n for n in visible if n > i][:1]
            if nearby:
                self.table.setCurrentCell(nearby[0], COL_NAME)
                note = self._row_widgets[nearby[0]][1]
                if note.isEnabled():
                    note.setFocus()
                    note.selectAll()
                else:  # not marked yet: back to the list, ready for P L A E
                    self.table.setFocus()
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

    def follow_today(self) -> None:
        """Left open overnight on today's register, go on to the new today."""
        today = self._clock()
        if self._showing_today is not None and self.day == self._showing_today != today:
            self.set_day(today)

    def showEvent(self, event) -> None:
        # Students may have been added, moved or deactivated on other pages meanwhile.
        super().showEvent(event)
        self.follow_today()
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
        self.month_view.apply_style()
        for box, name in self.swatches:
            if name:
                box.setStyleSheet(f"background: {_fill(self, name).name()}; border-radius: 2px;")
            else:
                box.setStyleSheet(f"border: 1px solid {line}; border-radius: 2px;")
