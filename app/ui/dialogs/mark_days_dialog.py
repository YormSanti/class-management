from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.models import AttendanceStatus
from app.services.attendance import DAYS_AHEAD, EARLIEST_DAY, MAX_DAYS_AT_ONCE, NOTE_MAX, school_days
from app.ui import style

# Excused first: a sick note or a school trip is the usual reason to mark several days.
CHOICES = (AttendanceStatus.EXCUSED, AttendanceStatus.ABSENT, AttendanceStatus.PRESENT, AttendanceStatus.LATE)


def _qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


class MarkDaysDialog(QDialog):
    """Pick the days, status and note to mark one student with, e.g. for a sick note."""

    def __init__(
        self, student_name: str, register_name: str, day: date, parent: QWidget | None = None,
        today: date | None = None,
    ):  # fmt: skip
        super().__init__(parent)
        self._today = today or date.today()
        self.setWindowTitle(f"Mark several days · {student_name}")
        self.setMinimumWidth(380)

        self.start_edit = QDateEdit(_qdate(day))
        self.end_edit = QDateEdit(_qdate(day))
        for edit in (self.start_edit, self.end_edit):
            # the same limits as the service: a mistyped year can't be picked
            edit.setDateRange(_qdate(EARLIEST_DAY), _qdate(self._today + timedelta(days=DAYS_AHEAD)))
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("ddd d MMM yyyy")
            edit.dateChanged.connect(self._update)
        self.status_combo = QComboBox()
        for status in CHOICES:
            self.status_combo.addItem(status.value.capitalize(), status)
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("e.g. Sick note, School trip")
        self.note_edit.setMaxLength(NOTE_MAX)
        self.replace_box = QCheckBox("Replace marks already made on these days")
        self.replace_box.setToolTip("Otherwise days the student is already marked stay as they are")

        self.days_label = QLabel()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Mark")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        hint = style.label(f"{student_name}, in the {register_name} register. Weekends are skipped.", 0.9, muted=True)
        hint.setWordWrap(True)
        form = QFormLayout()
        form.addRow("&From", self.start_edit)
        form.addRow("&To", self.end_edit)
        form.addRow("&Status", self.status_combo)
        form.addRow("&Note", self.note_edit)
        form.addRow("", self.replace_box)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.days_label)
        layout.addWidget(self.buttons)
        self._update()

    @property
    def start(self) -> date:
        return self.start_edit.date().toPython()

    @property
    def end(self) -> date:
        return self.end_edit.date().toPython()

    @property
    def status(self) -> AttendanceStatus:
        return AttendanceStatus(self.status_combo.currentData())  # Qt hands back a plain str

    @property
    def note(self) -> str:
        return self.note_edit.text().strip()

    @property
    def replace_marks(self) -> bool:
        return self.replace_box.isChecked()

    def set_period(self, start: date, end: date) -> None:
        self.start_edit.setDate(_qdate(start))
        self.end_edit.setDate(_qdate(end))

    def _update(self) -> None:
        """Say how many school days the dates cover, or what is wrong with them."""
        days = len(school_days(self.start, self.end))
        if self.end < self.start:
            text, ok = "The last day is before the first.", False
        elif not days:
            text, ok = "These dates are only a weekend.", False
        elif days > MAX_DAYS_AT_ONCE:
            text, ok = f"That is {days} school days. Mark at most {MAX_DAYS_AT_ONCE} at once.", False
        else:
            text, ok = f"{days} school day{'' if days == 1 else 's'}", True
            ahead = len(school_days(max(self.start, self._today + timedelta(days=1)), self.end))
            if ahead:  # fine for a planned trip, a slip for a sick note
                text += f", {ahead} of them still ahead"
        self.days_label.setText(text)
        style.set_color(self.days_label, style.color(self, "accent" if ok else "danger"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
