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


def test_dashboard_subject_hint_opens_subjects_tab(window: MainWindow, roster: RosterService):
    class_id = roster.save_class(SchoolClass(name="7B")).id
    window.select_class(class_id)
    window.dashboard_view.manage_subjects_requested.emit()
    assert window.stack.currentWidget() is window.classes_view
    assert window.classes_view.tabs.currentWidget() is window.classes_view.subject_box


def test_new_year_dialog_lists_classes_with_student_counts(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.new_year_dialog import NewYearDialog

    class_id = roster.save_class(SchoolClass(name="7B", term="2025-2026")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    dialog = NewYearDialog(roster, "2025-2026")
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == "1"
    assert dialog.new_term.text() == "2026-2027"


def test_student_dialog_asks_before_saving_a_duplicate_name(
    qapp: QApplication, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QMessageBox

    from app.ui.dialogs.student_dialog import StudentDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    asked: list[str] = []

    def answer_no(_parent, _title, text, *args):
        asked.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", answer_no)
    dialog = StudentDialog(roster.save_student, class_id, same_name=roster.same_name_students)
    dialog.first_name.setText("Ada")
    dialog.last_name.setText("Lovelace")
    dialog.accept()
    assert "already has Ada Lovelace" in asked[0]
    assert dialog.saved is None
    assert len(roster.list_students(class_id)) == 1


def test_student_dialog_save_and_add_another(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.student_dialog import StudentDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace", student_no="01"))
    dialog = StudentDialog(
        roster.save_student, class_id, suggest_no=lambda: roster.suggest_student_no(class_id)
    )
    assert dialog.student_no.text() == "02"
    for first, last in (("Alan", "Turing"), ("Grace", "Hopper")):
        dialog.first_name.setText(first)
        dialog.last_name.setText(last)
        dialog.save_and_add_another()
    assert [s.full_name for s in dialog.added] == ["Alan Turing", "Grace Hopper"]
    assert dialog.student_no.text() == "04"
    assert dialog.first_name.text() == "" and dialog.status.text() == "Added Grace Hopper."
    assert [s.student_no for s in roster.list_students(class_id)] == ["03", "01", "02"]


def test_paste_students_dialog_previews_and_adds(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = PasteStudentsDialog(roster, class_id)
    assert not dialog._ok.isEnabled()

    dialog.text.setPlainText("Ada Lovelace\nPlato")
    assert dialog.preview.rowCount() == 1
    assert "Line 2" in dialog.problems.text()
    assert not dialog._ok.isEnabled()

    dialog.text.setPlainText("Ada Lovelace\nHopper, Grace")
    assert dialog._ok.text() == "Add 2 students" and dialog._ok.isEnabled()
    dialog.accept()
    assert [s.full_name for s in dialog.added] == ["Ada Lovelace", "Grace Hopper"]
    assert len(roster.list_students(class_id)) == 2


def test_roster_export_writes_csv(
    window: MainWindow, roster: RosterService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    class_id = roster.save_class(SchoolClass(name="7/B", term="2026")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    window.select_class(class_id)
    suggested: list[str] = []

    def save_name(_parent, _title, start, _filter):
        suggested.append(start)
        return str(tmp_path / "out"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_name)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    window.classes_view.roster_view.export_csv()
    assert Path(suggested[0]).name == "7-B (2026) students.csv"
    assert "Lovelace" in (tmp_path / "out.csv").read_text(encoding="utf-8-sig")


def test_roster_move_to_class(window: MainWindow, roster: RosterService, monkeypatch: pytest.MonkeyPatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    class_id = roster.save_class(SchoolClass(name="7B")).id
    other = roster.save_class(SchoolClass(name="7C")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    window.select_class(class_id)
    roster_view = window.classes_view.roster_view
    roster_view.table.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("7C", True))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    roster_view.transfer_selected()
    assert roster_view.model.rowCount() == 0
    assert [s.full_name for s in roster.list_students(other)] == ["Ada Lovelace"]


def test_roster_count_mentions_hidden_inactive_students(window: MainWindow, roster: RosterService):
    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    gone = roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing"))
    roster.deactivate_student(gone.id)
    window.select_class(class_id)
    roster_view = window.classes_view.roster_view
    assert roster_view.count_label.text() == "1 student · 1 inactive hidden"
    roster_view.search.setText("Ada")
    assert roster_view.count_label.text() == "1 student matches your search"
    roster_view.search.clear()
    roster_view.show_inactive.setChecked(True)
    assert roster_view.count_label.text() == "2 students"


def test_ctrl_number_switches_page(window: MainWindow):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window.activateWindow()
    assert QTest.qWaitForWindowActive(window)
    QTest.keyClick(window, Qt.Key.Key_6, Qt.KeyboardModifier.ControlModifier)
    assert window.stack.currentWidget() is window.classes_view
    QTest.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert window.stack.currentWidget() is window.dashboard_view
    assert window.nav.item(5).toolTip() == "Manage classes (Ctrl+6)"


def test_window_size_and_splitter_are_remembered(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
):
    from PySide6.QtCore import QSettings

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    first = MainWindow(roster, dashboard, AppConfig(data_dir=tmp_path), settings)
    first.show()
    # Restoring keeps the window on screen, and the offscreen screen is only 800x600.
    first.resize(first.minimumSizeHint().width(), 520)
    first.splitter.setSizes([300, 460])
    qapp.processEvents()
    size, sizes = first.size(), first.splitter.sizes()
    first.close()

    second = MainWindow(roster, dashboard, AppConfig(data_dir=tmp_path), settings)
    second.show()
    qapp.processEvents()
    assert second.size() == size and size.height() == 520
    assert second.splitter.sizes() == sizes
    second.close()


def test_class_and_subject_are_remembered(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
):
    from PySide6.QtCore import QSettings

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    roster.save_class(SchoolClass(name="7A", term="2026-2027"), "Art")
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027"), "Art").id
    science = roster.save_subject(Subject(class_id=class_id, name="Science")).id

    first = MainWindow(roster, dashboard, AppConfig(data_dir=tmp_path), settings)
    first.select_class(class_id)
    first.select_subject(science)
    first.close()

    second = MainWindow(roster, dashboard, AppConfig(data_dir=tmp_path), settings)
    assert (second.class_id, second.subject_id) == (class_id, science)
    second.close()

    roster.delete_class(class_id)  # a deleted class falls back to the first one
    third = MainWindow(roster, dashboard, AppConfig(data_dir=tmp_path), settings)
    assert roster.get_class(third.class_id).name == "7A"
    third.close()
