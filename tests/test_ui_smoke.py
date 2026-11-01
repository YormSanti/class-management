"""Build the real window offscreen and click through it, so UI wiring errors show up in pytest."""

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import AppConfig  # noqa: E402
from app.models import SchoolClass, Student, Subject  # noqa: E402
from app.repositories.dashboard_repo import DashboardRepository  # noqa: E402
from app.repositories.student_repo import StudentRepository  # noqa: E402
from app.repositories.subject_repo import SubjectRepository  # noqa: E402
from app.services.dashboard import DashboardService  # noqa: E402
from app.services.roster import RosterService  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
) -> Iterator[MainWindow]:
    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    window = MainWindow(roster, dashboard, AppConfig(data_dir=tmp_path))
    window.show()
    yield window
    window.close()
    window.deleteLater()


def test_window_opens_without_classes(window: MainWindow):
    assert window.class_id is None
    assert window.windowTitle() == "Classroom Manager"


def test_every_page_can_be_shown(window: MainWindow, roster: RosterService):
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027"), "Maths").id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    window.select_class(class_id)
    for name, page in window.pages:
        window.show_page(name)
        assert window.stack.currentWidget() is page


def test_selecting_class_and_subject_updates_title(window: MainWindow, roster: RosterService):
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    science = roster.save_subject(Subject(class_id=class_id, name="Science")).id
    window.select_class(class_id)
    window.select_subject(science)
    assert window.windowTitle() == "Classroom Manager — 7B (2026-2027) · Science"
    assert window.classes_view.class_table.rowCount() == 1
    assert window.classes_view.subject_table.rowCount() == 1


def test_roster_lists_students_of_current_class(window: MainWindow, roster: RosterService):
    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    window.select_class(class_id)
    roster_view = window.classes_view.roster_view
    assert roster_view.model.rowCount() == 1
    assert roster_view.count_label.text() == "1 student"
