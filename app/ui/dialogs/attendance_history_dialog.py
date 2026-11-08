from datetime import date

from PySide6.QtCore import Qt
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

from app.models import AttendanceStatus
from app.services.attendance import StudentHistory
from app.ui import style


class AttendanceHistoryDialog(QDialog):
    """One student's marks in one register: totals, and every day they weren't present.

    Double-clicking a day closes the dialog with `chosen_day` set, to open that day.
    """

    def __init__(self, history: StudentHistory, register_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Attendance · {history.student.full_name}")
        self.setMinimumSize(480, 420)
        self.chosen_day: date | None = None
        self._days = [r.date for r in history.not_present]

        counts = history.counts()
        marked = sum(counts.values())
        rate = history.rate
        title = style.label(history.student.full_name, 1.4, bold=True)
        subtitle = style.label(f"{register_name} register · {marked} marked day{'' if marked == 1 else 's'}", muted=True)
        parts = [f"{counts[s.value]} {s.value}" for s in AttendanceStatus]
        parts.append("attendance —" if rate is None else f"attendance {rate:.0f}%")
        self.totals_label = style.label(" · ".join(parts), bold=True)
        self.totals_label.setWordWrap(True)

        self.table = QTableWidget(len(self._days), 3)
        self.table.setHorizontalHeaderLabels(["Day", "Status", "Note"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i, record in enumerate(history.not_present):
            day = record.date
            self.table.setItem(i, 0, QTableWidgetItem(f"{day:%a} {day.day} {day:%b %Y}"))
            status = QTableWidgetItem(record.status.value.capitalize())
            status.setForeground(style.color(self, style.STATUS_COLOR[record.status.value]))
            self.table.setItem(i, 1, status)
            self.table.setItem(i, 2, QTableWidgetItem(record.note))
        self.table.cellDoubleClicked.connect(self._open_day)
        self.table.setToolTip("Double-click a day to open it")

        self.empty_label = style.label(
            "Present every marked day." if marked else "No marks yet in this register.", muted=True
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setVisible(bool(self._days))
        self.empty_label.setVisible(not self._days)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.totals_label)
        layout.addSpacing(4)
        layout.addWidget(style.caption("Days not present"))
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.empty_label, stretch=1)
        layout.addWidget(buttons)

    def _open_day(self, row: int, _col: int) -> None:
        self.chosen_day = self._days[row]
        self.accept()
