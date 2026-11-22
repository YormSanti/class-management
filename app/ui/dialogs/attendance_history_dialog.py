from datetime import date

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models import AttendanceStatus
from app.services.attendance import StudentHistory
from app.services.dashboard import attendance_rate
from app.services.export import history_text, write_student_history_csv
from app.ui import style
from app.ui.files import ask_save_path


STATUS_ORDER = (AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED)


class AttendanceHistoryDialog(QDialog):
    """One student's marks in one register: totals, and every day they weren't present.

    Double-clicking a day closes the dialog with `chosen_day` set, to open that day.
    """

    def __init__(self, history: StudentHistory, register_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Attendance · {history.student.full_name}")
        self.setMinimumSize(480, 420)
        self.chosen_day: date | None = None
        self._history = history
        self._register_name = register_name
        self._days: list[date] = []

        counts = history.counts()
        marked = sum(counts.values())
        rate = history.rate
        title = style.label(history.student.full_name, 1.4, bold=True)
        subtitle = style.label(f"{register_name} register · {marked} marked day{'' if marked == 1 else 's'}", muted=True)
        parts = [f"{counts[s.value]} {s.value}" for s in AttendanceStatus]
        parts.append("attendance —" if rate is None else f"attendance {rate:.0f}%")
        self.totals_label = style.label(" · ".join(parts), bold=True)
        self.totals_label.setWordWrap(True)
        current, longest = history.absence_runs()
        runs = []
        if current >= 2:
            runs.append(f"Absent the last {current} marked days in a row")
        if longest >= 2 and longest > current:
            runs.append(f"longest run of absences: {longest} days")
        self.runs_label = style.label(" · ".join(runs).capitalize() if runs else "", bold=True)
        self.runs_label.setVisible(bool(runs))
        style.set_color(self.runs_label, style.color(self, "danger" if current >= 2 else "warn"))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Day", "Status", "Note"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self._open_day)
        self.table.setToolTip("Double-click a day (or press Enter) to open it")
        self.table.installEventFilter(self)

        self.show_all = QCheckBox("Show present days too")
        self.show_all.setEnabled(bool(marked))
        self.show_all.toggled.connect(self._fill)
        self.list_caption = style.caption("")
        self.empty_label = style.label("", muted=True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self.export_button = buttons.addButton("Export CSV…", QDialogButtonBox.ButtonRole.ActionRole)
        self.export_button.setToolTip("Save every marked day as a CSV file, e.g. for a meeting with parents")
        self.export_button.setAutoDefault(False)
        self.export_button.setEnabled(bool(marked))
        self.export_button.clicked.connect(self.export_csv)
        self.copy_button = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.setToolTip("Copy the totals and the days not present, e.g. for a message to parents")
        self.copy_button.setAutoDefault(False)
        self.copy_button.setEnabled(bool(marked))
        self.copy_button.clicked.connect(self.copy_text)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.totals_label)
        layout.addWidget(self.runs_label)
        days_page = QWidget()
        days_layout = QVBoxLayout(days_page)
        days_layout.setContentsMargins(0, 8, 0, 0)
        days_layout.addWidget(self.list_caption)
        days_layout.addWidget(self.table, stretch=1)
        days_layout.addWidget(self.empty_label, stretch=1)
        days_layout.addWidget(self.show_all)

        self.months_table = QTableWidget(0, 6)
        self.months_table.setHorizontalHeaderLabels(["Month", "Present", "Late", "Absent", "Excused", "Rate"])
        self.months_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.months_table.verticalHeader().setVisible(False)
        self.months_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.months_table.horizontalHeader().setStretchLastSection(True)
        self._fill_months()

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(days_page, "&Days")
        self.tabs.addTab(self.months_table, "By &month")
        self.tabs.setTabEnabled(1, marked > 0)

        layout.addSpacing(4)
        layout.addWidget(self.tabs, stretch=1)
        layout.addWidget(buttons)
        self._fill()

    def _fill(self) -> None:
        """List the days not present, or every marked day when "Show present days too" is ticked."""
        every_day = self.show_all.isChecked()
        records = self._history.records if every_day else self._history.not_present
        self._days = [r.date for r in records]
        self.list_caption.setText("Every marked day".upper() if every_day else "Days not present".upper())
        self.table.setRowCount(len(records))
        for i, record in enumerate(records):
            day = record.date
            self.table.setItem(i, 0, QTableWidgetItem(f"{day:%a} {day.day} {day:%b %Y}"))
            status = QTableWidgetItem(record.status.value.capitalize())
            status.setForeground(style.color(self, style.STATUS_COLOR[record.status.value]))
            self.table.setItem(i, 1, status)
            self.table.setItem(i, 2, QTableWidgetItem(record.note))
        marked = bool(self._history.records)
        self.empty_label.setText("Present every marked day." if marked else "No marks yet in this register.")
        self.table.setVisible(bool(records))
        self.empty_label.setVisible(not records)

    def _fill_months(self) -> None:
        """Each month's totals and rate, newest first, to see a change over the year."""
        months = self._history.by_month()
        self.months_table.setRowCount(len(months))
        for i, (first, counts) in enumerate(months):
            rate = attendance_rate(counts)
            values = [f"{first:%B %Y}"] + [str(counts[s.value]) for s in STATUS_ORDER]
            values.append("—" if rate is None else f"{rate:.0f}%")
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.months_table.setItem(i, col, item)

    def copy_text(self) -> None:
        QApplication.clipboard().setText(history_text(self._history, self._register_name))

    def export_csv(self) -> None:
        """Save every marked day of the student in this register as CSV."""
        name = f"{self._history.student.full_name} attendance {self._register_name}"
        path = ask_save_path(self, "Export attendance", name, "CSV files", ".csv")
        if path is None:
            return
        try:
            write_student_history_csv(path, self._history)
        except OSError as exc:
            QMessageBox.warning(self, "Export attendance", f"The file could not be saved:\n{exc}")
            return
        days = len(self._history.records)
        QMessageBox.information(
            self, "Export attendance", f"Saved {days} marked day{'' if days == 1 else 's'} to\n{path}"
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.table
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.table.currentRow() >= 0
        ):
            self._open_day(self.table.currentRow(), 0)
            return True
        return super().eventFilter(watched, event)

    def _open_day(self, row: int, _col: int) -> None:
        self.chosen_day = self._days[row]
        self.accept()
