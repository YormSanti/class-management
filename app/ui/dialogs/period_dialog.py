import calendar
from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
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
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    return {
        "This month": (month_start, today.replace(day=calendar.monthrange(today.year, today.month)[1])),
        "Last month": (last_month_end.replace(day=1), last_month_end),
        "Last 30 days": (today - timedelta(days=29), today),
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

        presets = QHBoxLayout()
        self.preset_buttons: dict[str, QPushButton] = {}
        for text, (first, last) in preset_periods(today or date.today()).items():
            button = QPushButton(text)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked, first=first, last=last: self.set_period(first, last))
            presets.addWidget(button)
            self.preset_buttons[text] = button
        presets.addStretch()

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
