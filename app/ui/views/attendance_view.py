import re
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFileDialog,
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
    MonthRegister,
    RegisterRow,
    day_warning,
    school_day,
)
from app.services.export import write_attendance_csv
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


class MonthView(QWidget):
    """A month at a glance: students down the side, school days across, totals at the end."""

    day_requested = Signal(object)  # a date to open on the Day tab

    def __init__(self, attendance: AttendanceService, parent: QWidget | None = None):
        super().__init__(parent)
        self.attendance = attendance
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self.file_label = ""  # e.g. "7B (2026-27) Maths", for the export file name
        today = date.today()
        self.year, self.month = today.year, today.month
        self.register: MonthRegister | None = None

        self.prev_button = QPushButton("‹")
        self.prev_button.setToolTip("Previous month")
        self.prev_button.setFixedWidth(36)
        self.prev_button.clicked.connect(lambda: self._step(-1))
        self.month_label = style.label("", 1.1, bold=True)
        self.month_label.setMinimumWidth(130)
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_button = QPushButton("›")
        self.next_button.setToolTip("Next month")
        self.next_button.setFixedWidth(36)
        self.next_button.clicked.connect(lambda: self._step(1))
        self.export_button = QPushButton("Export CSV…")
        self.export_button.setToolTip("Save this month as a CSV file for Excel or other programs")
        self.export_button.clicked.connect(self.export_csv)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        toolbar.addWidget(self.prev_button)
        toolbar.addWidget(self.month_label)
        toolbar.addWidget(self.next_button)
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
        toolbar.addWidget(self.export_button)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setWordWrap(False)
        self.table.cellDoubleClicked.connect(self._open_cell)
        self.table.horizontalHeader().sectionDoubleClicked.connect(lambda col: self._open_cell(-1, col))

        hint = style.label(
            "Double-click a day to open its register. The rate counts present and late out of the "
            "days marked; excused days count neither way, as on the dashboard.",
            0.85,
            muted=True,
        )
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(toolbar)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(hint)

    def load(self, class_id: int, subject_id: int | None, file_label: str) -> None:
        self.class_id, self.subject_id, self.file_label = class_id, subject_id, file_label
        self.refresh()

    def set_month(self, year: int, month: int) -> None:
        if (year, month) != (self.year, self.month):
            self.year, self.month = year, month
            self.refresh()

    def _step(self, months: int) -> None:
        index = self.year * 12 + self.month - 1 + months
        self.set_month(index // 12, index % 12 + 1)

    def refresh(self) -> None:
        if self.class_id is None:
            return
        first = date(self.year, self.month, 1)
        self.month_label.setText(f"{first:%B} {first.year}")
        self.register = self.attendance.month_register(self.class_id, self.year, self.month, self.subject_id)
        self._fill()

    def _fill(self) -> None:
        register = self.register
        days, recorded = register.days, set(register.recorded_days)
        totals = ("Abs.", "Late", "Exc.", "Rate")
        first_total = 1 + len(days)
        self.table.clear()
        self.table.setColumnCount(first_total + len(totals))
        self.table.setRowCount(len(register.rows) + 1)
        palette = self.palette()
        muted = style.mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text), 0.5)

        self.table.setHorizontalHeaderItem(0, QTableWidgetItem("Student"))
        for col, day in enumerate(days, start=1):
            item = QTableWidgetItem(f"{day:%a}"[:2] + f"\n{day.day}")
            item.setToolTip(f"{day:%A} {day.day} {day:%B} · double-click to open")
            if day not in recorded:
                item.setForeground(muted)
            self.table.setHorizontalHeaderItem(col, item)
        for col, text in enumerate(totals, start=first_total):
            self.table.setHorizontalHeaderItem(col, QTableWidgetItem(text))

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
                else:
                    item.setBackground(looks[status])
                    if status is not AttendanceStatus.PRESENT:
                        item.setText(status.value[0].upper())
                        item.setForeground(on_color)
                word = status.value.capitalize() if status else "Not marked"
                item.setToolTip(f"{row.student.full_name}, {day:%a} {day.day} {day:%b}: {word}")
                self.table.setItem(r, col, item)
            counts, rate = row.counts(), row.rate
            values = (counts["absent"], counts["late"], counts["excused"], "—" if rate is None else f"{rate:.0f}%")
            for col, value in enumerate(values, start=first_total):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if col == first_total and counts["absent"] >= 2:
                    item.setForeground(_fill(self, "danger"))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
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
            item.setForeground(_fill(self, "danger") if n else muted)
            self.table.setItem(last, col, item)
        counts, rate = register.counts(), register.rate
        values = (counts["absent"], counts["late"], counts["excused"], "—" if rate is None else f"{rate:.0f}%")
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

    def _open_cell(self, _row: int, col: int) -> None:
        if self.register is not None and 1 <= col <= len(self.register.days):
            self.day_requested.emit(self.register.days[col - 1])

    def export_csv(self) -> None:
        if self.register is None:
            return
        first = date(self.year, self.month, 1)
        safe_name = re.sub(r'[\\/:*?"<>|]+', "-", f"{self.file_label} attendance {first:%B} {first.year}")
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export attendance", str(Path.home() / f"{safe_name}.csv"), "CSV files (*.csv)"
        )
        if not path:
            return
        path = Path(path) if path.lower().endswith(".csv") else Path(path + ".csv")
        try:
            write_attendance_csv(path, self.register)
        except OSError as exc:
            QMessageBox.warning(self, "Export attendance", f"The file could not be saved:\n{exc}")
            return
        QMessageBox.information(self, "Export attendance", f"Saved {first:%B} {first.year} to\n{path}")

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

    def __init__(self, attendance: AttendanceService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.attendance = attendance
        self.roster = roster
        self.class_id: int | None = None
        self.register: DayRegister | None = None
        self._subject_for_class: dict[int, int | None] = {}
        self._row_widgets: list[tuple[StatusButtons, QLineEdit]] = []
        self._month_follows: date | None = None

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
        self._fill_classes()
        self._fill_registers()
        self.refresh()

    def set_subject(self, _subject_id: int | None) -> None:
        """Called when subjects change; the register picker keeps its own choice."""
        self._fill_registers()

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
        warning = day_warning(day, date.today())
        self.day_notice.setText(warning or "")
        self.day_notice.setVisible(warning is not None)
        style.set_color(self.day_notice, _fill(self, "warn"))
        file_label = " ".join(x for x in (school_class.display_name, self.subject_id and self.register_combo.currentText()) if x)
        if day != self._month_follows:  # the month follows the day, until changed by hand
            self._month_follows = day
            self.month_view.year, self.month_view.month = day.year, day.month
        self.month_view.load(school_class.id, self.subject_id, file_label)

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
        self.month_view.apply_style()
        for box, name in self.swatches:
            if name:
                box.setStyleSheet(f"background: {_fill(self, name).name()}; border-radius: 2px;")
            else:
                box.setStyleSheet(f"border: 1px solid {line}; border-radius: 2px;")
