"""The Attendance page, driven offscreen in the real window."""

import os
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import AppConfig  # noqa: E402
from app.models import AttendanceStatus, SchoolClass, Student  # noqa: E402
from app.repositories.attendance_repo import AttendanceRepository  # noqa: E402
from app.repositories.dashboard_repo import DashboardRepository  # noqa: E402
from app.repositories.gradebook_repo import GradebookRepository  # noqa: E402
from app.repositories.student_repo import StudentRepository  # noqa: E402
from app.repositories.subject_repo import SubjectRepository  # noqa: E402
from app.services.attendance import AttendanceService  # noqa: E402
from app.services.dashboard import DashboardService  # noqa: E402
from app.services.gradebook import GradebookService  # noqa: E402
from app.services.roster import RosterService  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

FRIDAY = date(2026, 11, 6)


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
) -> Iterator[MainWindow]:
    students, subjects = StudentRepository(conn), SubjectRepository(conn)
    window = MainWindow(
        roster,
        DashboardService(DashboardRepository(conn), students, subjects),
        AttendanceService(AttendanceRepository(conn), students, subjects),
        GradebookService(GradebookRepository(conn), students, subjects),
        AppConfig(data_dir=tmp_path),
    )
    window.show()
    yield window
    window.close()
    window.deleteLater()


def _page(window: MainWindow, roster: RosterService, names=("Ada Lovelace", "Grace Hopper"), day=FRIDAY):
    class_id = roster.save_class(SchoolClass(name="7B"), "Maths").id
    for name in names:
        first, last = name.split()
        roster.save_student(Student(class_id=class_id, first_name=first, last_name=last))
    window.select_class(class_id)
    window.show_page("Attendance")
    view = window.attendance_view
    view.set_day(day)
    return view


def _statuses(view) -> list[str | None]:
    return [row.status.value if row.status else None for row in view.register.rows]


def test_keys_mark_nobody_when_the_find_box_matches_no_one(window: MainWindow, roster: RosterService):
    view = _page(window, roster)
    view.find_edit.setText("zzz")
    assert all(view.table.isRowHidden(i) for i in range(view.table.rowCount()))
    QTest.keyClick(view.find_edit, Qt.Key.Key_Return)
    QTest.keyClick(view.table, Qt.Key.Key_A)
    assert _statuses(view) == [None, None]
    view.attendance.mark(view.register.rows[0].student.id, FRIDAY, AttendanceStatus.LATE)
    view.refresh()
    QTest.keyClick(view.table, Qt.Key.Key_Delete)
    assert _statuses(view) == ["late", None]

    view.find_edit.clear()  # everyone shown again: the keys work as before
    QTest.keyClick(view.table, Qt.Key.Key_A)
    assert _statuses(view) == ["absent", None]


def test_find_ignores_accents_and_name_order(window: MainWindow, roster: RosterService):
    view = _page(window, roster, ("José Martí", "Grace Hopper"))
    view.find_edit.setText("jose")
    assert [view.table.isRowHidden(i) for i in range(2)] == [True, False]  # Hopper, Martí
    view.find_edit.setText("Marti, Jose")
    assert [view.table.isRowHidden(i) for i in range(2)] == [True, False]
    view.find_edit.setText("")
    assert [view.table.isRowHidden(i) for i in range(2)] == [False, False]


def _shortcut(view, keys: str):
    from PySide6.QtGui import QKeySequence, QShortcut

    return next(s for s in view.findChildren(QShortcut) if s.key() == QKeySequence(keys))


def test_ctrl_shift_c_copies_nothing_before_anyone_is_marked(window: MainWindow, roster: RosterService):
    view = _page(window, roster)
    QApplication.clipboard().setText("before")
    _shortcut(view, "Ctrl+Shift+C").activated.emit()
    assert QApplication.clipboard().text() == "before"  # as the Copy absences button, which is disabled
    assert not view.status_label.text().startswith("Copied")

    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    _shortcut(view, "Ctrl+Shift+C").activated.emit()
    assert "Grace Hopper" in QApplication.clipboard().text()
    assert view.status_label.text().startswith("Copied")


def test_mark_the_rest_present_asks_first_on_a_weekend(
    window: MainWindow, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QMessageBox

    view = _page(window, roster, day=date(2026, 11, 7))  # a Saturday
    asked = []

    def answer(_parent, _title, text, *args):
        asked.append(text)
        return reply

    monkeypatch.setattr(QMessageBox, "question", answer)
    reply = QMessageBox.StandardButton.No
    view.mark_rest_button.click()
    assert asked == ["Saturday 7 November is a weekend day. Mark everyone who isn't marked as present anyway?"]
    assert _statuses(view) == [None, None]

    reply = QMessageBox.StandardButton.Yes
    view.mark_rest_button.click()
    assert _statuses(view) == ["present", "present"]

    view.set_day(FRIDAY)  # a school day in the past: no question
    view.mark_rest_button.click()
    assert len(asked) == 2 and _statuses(view) == ["present", "present"]


def test_h_on_the_month_tab_shows_the_students_history(window: MainWindow, roster: RosterService):
    view = _page(window, roster)
    month = view.month_view
    view.tabs.setCurrentWidget(month)
    shown = []
    month.history_requested.disconnect()  # instead of the dialog, which would wait for a click
    month.history_requested.connect(shown.append)
    month.table.setCurrentCell(1, 1 + month.register.days.index(FRIDAY))  # Lovelace, on a day
    QTest.keyClick(month.table, Qt.Key.Key_H)
    assert shown == [month.register.rows[1].student.id]
    assert _statuses(view) == [None, None]  # H marks nothing

    month.table.setCurrentCell(len(month.register.rows), 1)  # the "Absent that day" row: no student
    QTest.keyClick(month.table, Qt.Key.Key_H)
    assert len(shown) == 1


def test_a_first_day_past_the_last_moves_the_last_along(qapp: QApplication):
    from PySide6.QtCore import QDate

    from app.ui.dialogs.mark_days_dialog import MarkDaysDialog
    from app.ui.dialogs.period_dialog import PeriodDialog

    marks = MarkDaysDialog("Ada Lovelace", "Daily (homeroom)", FRIDAY, today=FRIDAY)
    period = PeriodDialog("Export", date(2026, 11, 2), FRIDAY, today=FRIDAY)
    for dialog in (marks, period):
        dialog.start_edit.setDate(QDate(2026, 11, 10))
        assert (dialog.start, dialog.end) == (date(2026, 11, 10), date(2026, 11, 10))
        dialog.start_edit.setDate(QDate(2026, 11, 9))  # back before the last day: the last stays
        assert dialog.end == date(2026, 11, 10)
        dialog.end_edit.setDate(QDate(2026, 11, 5))  # a last day before the first is still pointed out
        assert dialog.start == date(2026, 11, 9)
    assert marks.days_label.text() == "The last day is before the first."
    assert period.problem.text() == "The last day is before the first."
    marks.deleteLater()
    period.deleteLater()
