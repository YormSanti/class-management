import calendar
from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import style


def _qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


def preset_periods(today: date) -> dict[str, tuple[date, date]]:
    """Common periods ending around `today`: {button text: (first day, last day)}."""
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    return {
        "This week": (week_start, week_start + timedelta(days=4)),
        "Last week": (week_start - timedelta(days=7), week_start - timedelta(days=3)),
        "Last 30 days": (today - timedelta(days=29), today),
        "This month": (month_start, today.replace(day=calendar.monthrange(today.year, today.month)[1])),
        "Last month": (last_month_end.replace(day=1), last_month_end),
        "This year": (date(today.year, 1, 1), date(today.year, 12, 31)),
    }


class PeriodDialog(QDialog):
    """Pick the first and last day of a period, e.g. a term, both included."""

    def __init__(
        self, title: str, start: date, end: date, parent: QWidget | None = None, today: date | None = None
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(340)

        self.start_edit = QDateEdit(_qdate(start))
        self.end_edit = QDateEdit(_qdate(end))
        for edit in (self.start_edit, self.end_edit):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("ddd d MMM yyyy")
            edit.dateChanged.connect(self._update_ok)

        self.problem = QLabel()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export…")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        presets = QGridLayout()  # three to a row
        self.preset_buttons: dict[str, QPushButton] = {}
        self._presets = preset_periods(today or date.today())
        for n, text in enumerate(self._presets):
            button = QPushButton(text)
            button.setAutoDefault(False)
            # A bound method, not a lambda holding `self`: such a cycle lets Python's garbage
            # collector delete a parentless dialog at a random moment later, crashing Qt.
            button.clicked.connect(self._use_preset)
            presets.addWidget(button, n // 3, n % 3)
            self.preset_buttons[text] = button

        form = QFormLayout()
        form.addRow("&From", self.start_edit)
        form.addRow("&To", self.end_edit)
        form.addRow("", presets)
        hint = style.label("Each student's totals for these days, both included.", 0.9, muted=True)
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)
        self._update_ok()

    def _use_preset(self) -> None:
        self.set_period(*self._presets[self.sender().text()])

    def set_period(self, start: date, end: date) -> None:
        self.start_edit.setDate(_qdate(start))
        self.end_edit.setDate(_qdate(end))

    @property
    def start(self) -> date:
        return self.start_edit.date().toPython()

    @property
    def end(self) -> date:
        return self.end_edit.date().toPython()

    def _update_ok(self) -> None:
        ok = self.start <= self.end
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        self.problem.setText("" if ok else "The last day is before the first.")
        self.problem.setVisible(not ok)
        style.set_color(self.problem, style.color(self, "danger"))
