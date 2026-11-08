from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.ui import style


def _qdate(day: date) -> QDate:
    return QDate(day.year, day.month, day.day)


class PeriodDialog(QDialog):
    """Pick the first and last day of a period, e.g. a term, both included."""

    def __init__(self, title: str, start: date, end: date, parent: QWidget | None = None):
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

        form = QFormLayout()
        form.addRow("&From", self.start_edit)
        form.addRow("&To", self.end_edit)
        hint = style.label("Each student's totals for these days, both included.", 0.9, muted=True)
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)
        self._update_ok()

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
