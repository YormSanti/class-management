"""Build the real window offscreen and click through it, so UI wiring errors show up in pytest."""

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.config import AppConfig  # noqa: E402
from app.models import SchoolClass, Student, Subject  # noqa: E402
from app.repositories.attendance_repo import AttendanceRepository  # noqa: E402
from app.repositories.dashboard_repo import DashboardRepository  # noqa: E402
from app.repositories.student_repo import StudentRepository  # noqa: E402
from app.repositories.subject_repo import SubjectRepository  # noqa: E402
from app.services.attendance import AttendanceService  # noqa: E402
from app.services.dashboard import DashboardService  # noqa: E402
from app.services.roster import RosterService  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def _attendance(conn: sqlite3.Connection) -> AttendanceService:
    return AttendanceService(AttendanceRepository(conn), StudentRepository(conn), SubjectRepository(conn))


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
) -> Iterator[MainWindow]:
    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    window = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path))
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


def test_student_dialog_hints_the_next_free_number_for_a_student_without_one(
    qapp: QApplication, roster: RosterService
):
    from app.ui.dialogs.student_dialog import StudentDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace", student_no="S04"))
    alan = roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing"))
    dialog = StudentDialog(roster.save_student, class_id, alan, suggest_no=lambda: roster.suggest_student_no(class_id))
    assert dialog.student_no.text() == ""  # a hint only: saving leaves the student without a number
    assert dialog.student_no.placeholderText() == "None yet; the next free one is S05"


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


def test_paste_dialog_shows_notes_only_when_pasted(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = PasteStudentsDialog(roster, class_id)
    dialog.text.setPlainText("Ada Lovelace")
    assert dialog.preview.isColumnHidden(3)
    dialog.text.setPlainText("1\tAda\tLovelace\tAllergic to nuts")
    assert not dialog.preview.isColumnHidden(3)
    assert dialog.preview.item(0, 3).text() == "Allergic to nuts"


def test_paste_dialog_points_out_numbers_already_used(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace", student_no="7"))
    dialog = PasteStudentsDialog(roster, class_id)
    dialog.text.setPlainText("7 Alan Turing")
    assert "number 7 is already used by Ada Lovelace" in dialog.problems.text()
    assert not dialog._ok.isEnabled()


def test_paste_dialog_counts_the_problems_not_shown(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = PasteStudentsDialog(roster, class_id)
    dialog.text.setPlainText("\n".join(["Plato", "<Socrates>"] * 4))
    assert dialog.problems.text().count("<br>") == 5
    assert dialog.problems.text().endswith("and 3 more lines to fix")
    assert "&lt;Socrates&gt;" in dialog.problems.text()


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


def test_roster_export_follows_the_table_order(
    window: MainWindow, roster: RosterService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    class_id = roster.save_class(SchoolClass(name="7B")).id
    for first, last, no in (("Ada", "Lovelace", "3"), ("Grace", "Hopper", "1"), ("Alan", "Turing", "2")):
        roster.save_student(Student(class_id=class_id, first_name=first, last_name=last, student_no=no))
    window.select_class(class_id)
    view = window.classes_view.roster_view
    view.search.setText("Ada")  # the search doesn't limit the export
    view.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "out.csv"), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    view.export_csv()
    lines = (tmp_path / "out.csv").read_text(encoding="utf-8-sig").splitlines()
    assert [line.split(",")[1] for line in lines[1:]] == ["Lovelace", "Turing", "Hopper"]


def test_roster_sorts_numbers_as_people_read_them(window: MainWindow, roster: RosterService):
    from PySide6.QtCore import Qt

    class_id = roster.save_class(SchoolClass(name="7B")).id
    for first, no in (("Ada", "S10"), ("Bea", None), ("Cy", "S2"), ("Dan", "S1")):
        roster.save_student(Student(class_id=class_id, first_name=first, last_name="X", student_no=no))
    window.select_class(class_id)
    view = window.classes_view.roster_view
    view.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    shown = [view.proxy.index(row, 2).data() for row in range(view.proxy.rowCount())]
    assert shown == ["Dan", "Cy", "Ada", "Bea"]  # without a number last


def test_roster_numbers_the_students_without_one(
    window: MainWindow, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    window.select_class(class_id)
    view = window.classes_view.roster_view
    assert view.number_button.isHidden()  # the class uses no numbers
    roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing", student_no="S07"))
    roster.save_student(Student(class_id=class_id, first_name="Grace", last_name="Hopper"))
    view.refresh()
    assert not view.number_button.isHidden()
    assert view.number_button.text() == "Number 2 students…"
    asked, told = [], []
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, text: asked.append(text) or ("S08", True))
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text: told.append(text))
    view.number_students()
    assert asked == ["S08"]
    assert {s.first_name: s.student_no for s in roster.list_students(class_id)} == {
        "Grace": "S08", "Ada": "S09", "Alan": "S07"
    }
    assert told == ["New student numbers:\n\nS08  Grace Hopper\nS09  Ada Lovelace"]
    assert view.number_button.isHidden()


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


def test_roster_move_to_class_says_the_new_number(
    window: MainWindow, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    class_id = roster.save_class(SchoolClass(name="7B")).id
    other = roster.save_class(SchoolClass(name="7C")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace", student_no="S05"))
    roster.save_student(Student(class_id=other, first_name="Alan", last_name="Turing", student_no="S05"))
    window.select_class(class_id)
    roster_view = window.classes_view.roster_view
    roster_view.table.selectRow(0)
    told = []
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("7C", True))
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text: told.append(text))
    roster_view.transfer_selected()
    assert told[0].endswith("Student number S05 is already used in 7C, so they are S06 there.")


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
    assert roster_view.count_label.text() == "2 students · 1 inactive"


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


def test_settings_is_pinned_to_the_bottom_of_the_sidebar(window: MainWindow):
    top = [window.nav.item(r).text() for r in range(window.nav.count())]
    assert "Settings" not in top
    assert [window.nav_bottom.item(r).text() for r in range(window.nav_bottom.count())] == ["Settings"]
    sidebar = window.nav.parentWidget()
    assert window.nav_bottom.geometry().bottom() > sidebar.height() - 30  # at the bottom left

    window.nav_bottom.setCurrentRow(0)  # clicking Settings
    assert window.stack.currentWidget() is window.settings_view
    assert not window.nav.selectedItems()  # only one page is highlighted
    window.nav.setCurrentRow(1)
    assert window.stack.currentWidget() is window.attendance_view
    assert not window.nav_bottom.selectedItems()
    window.show_page("Settings")
    assert window.nav_bottom.currentRow() == 0 and not window.nav.selectedItems()
    window.nav.setFocus()  # focusing the top list must not jump back to a page there
    QApplication.processEvents()
    assert window.stack.currentWidget() is window.settings_view
    window.nav.item(0).setSelected(True)  # clicking the Dashboard
    assert window.stack.currentWidget() is window.dashboard_view
    assert not window.nav_bottom.selectedItems()


def test_window_size_and_splitter_are_remembered(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
):
    from PySide6.QtCore import QSettings

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    first = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    first.show()
    # Restoring keeps the window on screen, and the offscreen screen is only 800x600.
    first.resize(first.minimumSizeHint().width(), 520)
    first.splitter.setSizes([300, 460])
    qapp.processEvents()
    size, sizes = first.size(), first.splitter.sizes()
    first.close()

    second = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    second.show()
    qapp.processEvents()
    assert second.size() == size and size.height() == 520
    assert second.splitter.sizes() == sizes
    second.close()


def test_last_page_is_remembered(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
):
    from PySide6.QtCore import QSettings

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    first = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    first.show_page("Settings")
    first.close()

    second = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    assert second.stack.currentWidget() is second.settings_view
    assert second.nav_bottom.selectedItems()
    second.close()

    settings.setValue("session/page", "No such page")  # e.g. a page renamed in a later version
    third = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    assert third.stack.currentWidget() is third.dashboard_view
    third.close()


def test_attendance_tab_is_remembered(qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path):
    from PySide6.QtCore import QSettings

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    roster.save_class(SchoolClass(name="7B"))
    first = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    first.show_page("Attendance")
    first.attendance_view.tabs.setCurrentWidget(first.attendance_view.month_view)
    first.close()

    second = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    assert second.attendance_view.tabs.currentWidget() is second.attendance_view.month_view
    second.close()

    settings.setValue("session/attendance_tab", 9)
    third = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    assert third.attendance_view.tabs.currentIndex() == 0
    third.close()


def test_class_and_subject_are_remembered(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
):
    from PySide6.QtCore import QSettings

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    roster.save_class(SchoolClass(name="7A", term="2026-2027"), "Art")
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027"), "Art").id
    science = roster.save_subject(Subject(class_id=class_id, name="Science")).id

    first = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    first.select_class(class_id)
    first.select_subject(science)
    first.close()

    second = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    assert (second.class_id, second.subject_id) == (class_id, science)
    second.close()

    roster.delete_class(class_id)  # a deleted class falls back to the first one
    third = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    assert roster.get_class(third.class_id).name == "7A"
    third.close()


def test_back_up_now_copies_the_database(
    qapp: QApplication,
    conn: sqlite3.Connection,
    roster: RosterService,
    db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from PySide6.QtWidgets import QFileDialog

    roster.save_class(SchoolClass(name="7B"))
    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    window = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=db_path.parent))
    usb = tmp_path / "usb"
    usb.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(usb / "before trip"), ""))
    window.back_up_now()
    copy = sqlite3.connect(usb / "before trip.db")
    assert copy.execute("SELECT name FROM classes").fetchall() == [("7B",)]
    copy.close()
    assert "File" in [a.text().replace("&", "") for a in window.menuBar().actions()]
    window.close()


def test_dashboard_can_show_every_student_needing_attention(
    window: MainWindow, roster: RosterService, conn: sqlite3.Connection
):
    from datetime import date, timedelta

    from app.ui.views.dashboard_view import ATTENTION_SHOWN

    class_id = roster.save_class(SchoolClass(name="7B")).id
    today = date.today()
    for i in range(ATTENTION_SHOWN + 3):
        sid = roster.save_student(Student(class_id=class_id, first_name=f"S{i}", last_name="Test")).id
        for days_ago in range(3):
            day = (today - timedelta(days=days_ago)).isoformat()
            conn.execute("INSERT INTO attendance (student_id, date, status) VALUES (?, ?, 'absent')", (sid, day))
    window.select_class(class_id)
    view = window.dashboard_view

    def rows() -> int:
        layout = view.attention_list
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        return sum(w.objectName() == "AttentionRow" for w in widgets)

    assert rows() == ATTENTION_SHOWN
    view._toggle_attention()
    assert rows() == ATTENTION_SHOWN + 3
    view.refresh()  # stays expanded for the same class
    assert rows() == ATTENTION_SHOWN + 3
    view._toggle_attention()
    assert rows() == ATTENTION_SHOWN


# --- attendance ----------------------------------------------------------------


def _attendance_page(window: MainWindow, roster: RosterService, names=("Ada Lovelace", "Grace Hopper")):
    from datetime import date

    class_id = roster.save_class(SchoolClass(name="7B"), "Maths").id
    for name in names:
        first, last = name.split()
        roster.save_student(Student(class_id=class_id, first_name=first, last_name=last))
    window.select_class(class_id)
    window.show_page("Attendance")
    view = window.attendance_view
    view.set_day(date(2026, 11, 6))
    return view


def _statuses(view) -> list[str | None]:
    return [row.status.value if row.status else None for row in view.register.rows]


def test_attendance_buttons_mark_and_clear(window: MainWindow, roster: RosterService):
    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    assert view.table.rowCount() == 2
    assert view.count_labels["unmarked"].text() == "2"

    buttons, note = view._row_widgets[0]
    assert not note.isEnabled()
    buttons.buttons[AttendanceStatus.LATE].click()
    assert _statuses(view) == ["late", None]
    assert buttons.buttons[AttendanceStatus.LATE].isChecked()
    assert note.isEnabled()
    assert view.count_labels["late"].text() == "1"

    buttons.buttons[AttendanceStatus.LATE].click()  # clicking the chosen one again clears it
    assert _statuses(view) == [None, None]
    assert not buttons.buttons[AttendanceStatus.LATE].isChecked()


def test_attendance_keys_mark_and_move_down(window: MainWindow, roster: RosterService, qapp):
    from PySide6.QtCore import Qt

    from app.models import AttendanceStatus
    from PySide6.QtTest import QTest

    view = _attendance_page(window, roster, ("Ada Lovelace", "Grace Hopper", "Alan Turing"))
    view.table.setCurrentCell(0, 1)
    QTest.keyClick(view.table, Qt.Key.Key_A)
    QTest.keyClick(view.table, Qt.Key.Key_P)
    assert _statuses(view) == ["absent", "present", None]  # Hopper, Lovelace, Turing
    assert view.table.currentRow() == 2
    QTest.keyClick(view.table, Qt.Key.Key_Up)
    QTest.keyClick(view.table, Qt.Key.Key_Delete)
    assert _statuses(view) == ["absent", None, None]
    assert view.status_label.text() == "Not marked yet: Ada Lovelace and Alan Turing. They don't count as present."
    view._row_widgets[1][0].buttons[AttendanceStatus.LATE].click()
    assert view.status_label.text() == "Not marked yet: Alan Turing. They don't count as present."


def test_attendance_note_is_saved(window: MainWindow, roster: RosterService):
    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    buttons, note = view._row_widgets[0]
    buttons.buttons[AttendanceStatus.ABSENT].click()
    note.setText("Dentist")
    note.editingFinished.emit()
    view.refresh()
    assert view.register.rows[0].note == "Dentist"
    assert view._row_widgets[0][1].text() == "Dentist"


def test_attendance_mark_rest_and_registers(window: MainWindow, roster: RosterService):
    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    view.mark_rest_button.click()
    assert _statuses(view) == ["absent", "present"]
    assert view.status_label.text() == "Marked 1 student present. Everyone is marked."
    assert not view.mark_rest_button.isEnabled()
    assert view.rate_label.text() == "50%"
    assert view.rate_label.toolTip().endswith("\nHere: 1 of 2.")

    assert [view.register_combo.itemText(i) for i in range(view.register_combo.count())] == [
        "Daily (homeroom)",
        "Maths",
    ]
    view.register_combo.setCurrentIndex(1)
    assert _statuses(view) == [None, None]  # the Maths register is separate
    window.select_class(window.class_id)
    assert view.register_combo.currentText() == "Maths"  # remembered for the class


def test_attendance_day_buttons_skip_weekends(window: MainWindow, roster: RosterService):
    from datetime import date

    view = _attendance_page(window, roster)  # Friday 6 November 2026
    view.next_button.click()
    assert view.day == date(2026, 11, 9)
    assert view.date_label.text() == "MONDAY, 9 NOVEMBER 2026"
    view.prev_button.click()
    assert view.day == date(2026, 11, 6)
    view.today_button.click()
    assert view.day == date.today() and not view.today_button.isEnabled()


def test_attendance_undo(window: MainWindow, roster: RosterService, monkeypatch):
    from datetime import date

    from PySide6.QtWidgets import QMessageBox

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    assert not view.undo_button.isEnabled()
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    note = view._row_widgets[0][1]
    note.setText("Dentist")
    note.editingFinished.emit()
    view.mark_rest_button.click()
    assert view.undo_button.toolTip().startswith("Undo: mark the rest present")

    view.undo()
    assert _statuses(view) == ["absent", None]
    view.undo()
    assert view.register.rows[0].note == ""
    view.undo()
    assert _statuses(view) == [None, None] and not view.undo_button.isEnabled()

    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    view.mark_rest_button.click()
    view.set_day(date(2026, 11, 9))  # undo goes back to the day the change was made
    view.clear_day()  # nothing to clear on the 9th, but it is remembered all the same
    view.undo()
    view.undo()
    assert view.day == date(2026, 11, 6) and _statuses(view) == [None, None]


def test_attendance_history_dialog(window: MainWindow, roster: RosterService, monkeypatch):
    from datetime import date

    from app.models import AttendanceStatus
    from app.ui.dialogs.attendance_history_dialog import AttendanceHistoryDialog

    view = _attendance_page(window, roster)
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    view.set_day(date(2026, 11, 5))
    view._row_widgets[0][0].buttons[AttendanceStatus.PRESENT].click()

    shown = []

    def pick_first_day(dialog):
        shown.append(dialog)
        dialog.table.cellDoubleClicked.emit(0, 0)
        return dialog.result()

    monkeypatch.setattr(AttendanceHistoryDialog, "exec", pick_first_day)
    view.table.cellDoubleClicked.emit(0, 1)
    dialog = shown[0]
    assert dialog.windowTitle() == "Attendance · Grace Hopper"
    assert dialog.totals_label.text() == "1 present · 1 absent · 0 late · 0 excused · attendance 50%"
    assert dialog.table.rowCount() == 1 and dialog.table.item(0, 1).text() == "Absent"
    assert view.day == date(2026, 11, 6)  # the day picked in the dialog opened
    dialog.show_all.setChecked(True)
    assert [dialog.table.item(i, 1).text() for i in range(2)] == ["Absent", "Present"]  # newest first
    assert dialog.list_caption.text() == "EVERY MARKED DAY"
    dialog.table.cellDoubleClicked.emit(1, 0)
    assert dialog.chosen_day == date(2026, 11, 5)


def test_attendance_warns_about_future_and_weekend_days(window: MainWindow, roster: RosterService):
    from datetime import date, timedelta

    view = _attendance_page(window, roster)  # Friday 6 November 2026, in the past
    assert view.day_notice.isHidden()
    view.set_day(date(2026, 11, 7))
    assert not view.day_notice.isHidden()
    assert view.day_notice.text().startswith("Saturday is a weekend day")
    view.set_day(date.today() + timedelta(days=1))
    assert view.day_notice.text().startswith("This day is in the future (tomorrow)")


def test_attendance_class_picker_switches_class(window: MainWindow, roster: RosterService):
    view = _attendance_page(window, roster)
    older = roster.save_class(SchoolClass(name="6A", term="2025-2026")).id
    newer = roster.save_class(SchoolClass(name="8C", term="2026-2027")).id
    roster.save_student(Student(class_id=newer, first_name="Alan", last_name="Turing"))
    window.select_class(window.class_id)  # reload after adding classes

    names = [view.class_combo.itemText(i) for i in range(view.class_combo.count())]
    assert names == ["8C (2026-2027)", "6A (2025-2026)", "7B"]  # newest year first
    assert view.class_combo.currentText() == "7B"

    view.class_combo.setCurrentIndex(0)
    view.class_combo.activated.emit(0)
    assert window.class_id == newer
    assert view.title_label.text() == "Attendance · 8C"
    assert view.table.rowCount() == 1
    assert window.windowTitle() == "Classroom Manager — 8C (2026-2027)"
    assert older in [view.class_combo.itemData(i) for i in range(view.class_combo.count())]


def test_attendance_month_tab(window: MainWindow, roster: RosterService, tmp_path: Path, monkeypatch):
    from datetime import date

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)  # Friday 6 November 2026
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    month = view.month_view
    view.tabs.setCurrentWidget(month)
    assert month.month_label.text() == "November 2026"  # follows the day shown
    assert len(month.register.days) == 21
    assert month.table.rowCount() == 3  # two students and the "Absent that day" row
    friday = 1 + month.register.days.index(date(2026, 11, 6))
    assert month.table.item(0, friday).text() == "A"
    assert month.table.item(2, friday).text() == "1"
    assert month.table.item(2, friday).toolTip() == "Absent Fri 6 Nov: Grace Hopper"
    not_marked = month.table.columnCount() - 2
    assert month.table.horizontalHeaderItem(not_marked).text() == "Not m."
    assert [month.table.item(r, not_marked).text() for r in range(3)] == ["–", "1", "1"]  # Lovelace on Friday
    rate = month.table.item(0, not_marked + 1)
    assert rate.text() == "0%" and rate.toolTip() == "Under 90%"

    month.prev_button.click()
    assert month.month_label.text() == "October 2026"
    view.refresh()  # e.g. coming back to the page keeps the month picked by hand
    assert month.month_label.text() == "October 2026"

    month.next_button.click()
    month._open_cell(0, friday - 1)  # double-click Thursday
    assert view.tabs.currentIndex() == 0 and view.day == date(2026, 11, 5)

    saved = tmp_path / "november"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(saved), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    month.export_csv()
    assert (tmp_path / "november.csv").read_text(encoding="utf-8-sig").splitlines()[1].startswith(
        ",Hopper,Grace,"
    )


def test_settings_page_shows_data_and_backups(window: MainWindow, db_path: Path):
    from datetime import datetime

    from app.services.backup import auto_backup

    window.config.backup_dir.mkdir(parents=True, exist_ok=True)
    for hour in (8, 9):
        auto_backup(db_path, window.config.backup_dir, now=datetime(2026, 11, 6, hour, 30))
    window.show_page("Settings")
    view = window.settings_view
    assert view.data_path_label.text() == str(window.config.db_path)
    assert view.backup_summary.text() == "2 backups · newest Friday 6 November 2026, 09:30"
    assert view.backup_table.rowCount() == 2
    assert view.backup_table.item(0, 0).text() == "Fri 6 Nov 2026, 09:30"


def test_settings_page_saves_ranking_method(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
):
    from app.config import load_config, save_config

    path = tmp_path / "config.json"
    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    window = MainWindow(
        roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), save_config=lambda c: save_config(c, path)
    )
    try:
        view = window.settings_view
        assert view.ranking_buttons["competition"].isChecked()
        view.ranking_buttons["dense"].click()
        assert window.config.ranking_method == "dense"
        assert load_config(path).ranking_method == "dense"
    finally:
        window.close()
        window.deleteLater()


def test_settings_page_keeps_old_choice_when_saving_fails(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    def fail(_config):
        raise OSError("disk full")

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    window = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), save_config=fail)
    try:
        view = window.settings_view
        view.ranking_buttons["dense"].click()
        assert warnings and "disk full" in warnings[0]
        assert view.ranking_buttons["competition"].isChecked()
        assert window.config.ranking_method == "competition"
    finally:
        window.close()
        window.deleteLater()


def test_attendance_export_period(window: MainWindow, roster: RosterService, tmp_path: Path, monkeypatch):
    import csv
    from datetime import date

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from app.models import AttendanceStatus
    from app.ui.dialogs.period_dialog import PeriodDialog

    view = _attendance_page(window, roster)
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    view.mark_rest_button.click()
    month = view.month_view
    assert (month.year, month.month) == (2026, 11)

    def pick_period(dialog):
        assert (dialog.start, dialog.end) == (date(2026, 11, 1), date(2026, 11, 30))  # the shown month
        dialog.end_edit.setDate(dialog.start_edit.date().addDays(-1))
        assert not dialog.buttons.buttons()[0].isEnabled()  # the end is before the start
        dialog.start_edit.setDate(dialog.start_edit.date().addMonths(-2))  # 1 September
        dialog.end_edit.setDate(dialog.end_edit.date().addMonths(1))  # 30 November
        return True

    saved = tmp_path / "term.csv"
    monkeypatch.setattr(PeriodDialog, "exec", pick_period)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(saved), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    month.export_period()
    with saved.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1][1:] == ["Hopper", "Grace", "0", "0", "1", "0", "0", "0"]
    assert rows[2][1:] == ["Lovelace", "Ada", "1", "0", "0", "0", "0", "100"]


def test_attendance_month_saves_pdf(window: MainWindow, roster: RosterService, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    view = _attendance_page(window, roster)
    view.mark_rest_button.click()
    saved = tmp_path / "november"
    shown = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(saved), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: shown.append(args[2]))
    view.month_view.save_pdf()
    pdf = tmp_path / "november.pdf"  # the extension is added
    assert pdf.read_bytes().startswith(b"%PDF")
    assert shown and shown[0].startswith("Saved November 2026")


def test_settings_page_restores_a_backup(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, db_path: Path, tmp_path: Path, monkeypatch
):
    from datetime import datetime

    from PySide6.QtWidgets import QMessageBox

    from app.services.backup import auto_backup, restore_backup

    config = AppConfig(data_dir=tmp_path)
    seventh = roster.save_class(SchoolClass(name="7B")).id
    auto_backup(db_path, config.backup_dir, now=datetime(2026, 11, 2, 8, 0))
    eighth = roster.save_class(SchoolClass(name="8C")).id

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    window = MainWindow(
        roster, dashboard, _attendance(conn), config,
        restore_backup=lambda backup: restore_backup(backup, conn, config.db_path, config.backup_dir),
    )  # fmt: skip
    questions, infos = [], []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: questions.append(a[2]) or QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[2]))
    try:
        window.select_class(eighth)
        view = window.settings_view
        window.show_page("Settings")
        assert not view.restore_button.isEnabled()
        view.backup_table.selectRow(0)
        assert view.restore_button.isEnabled()
        view.restore_button.click()

        assert "Monday 2 November 2026 at 08:00" in questions[0]
        assert [c.name for c in roster.list_classes()] == ["7B"]
        assert window.class_id == seventh  # 8C is gone, so the window falls back to 7B
        assert view.backup_table.rowCount() == 2  # the data from before the restore was kept
        assert view.backup_table.item(0, 0).text().endswith(" · from just before a restore")
        assert infos and infos[0].startswith("Your data is back as it was")
    finally:
        window.close()
        window.deleteLater()


def _window_saving_config(conn, roster, tmp_path, path):
    from app.config import save_config

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    return MainWindow(
        roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), save_config=lambda c: save_config(c, path)
    )


def test_settings_page_moves_data(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from app.config import load_config

    roster.save_class(SchoolClass(name="7B"))
    config_path = tmp_path / "config.json"
    new_dir = tmp_path / "usb" / "Classroom"
    new_dir.mkdir(parents=True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(new_dir))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    window = _window_saving_config(conn, roster, tmp_path, config_path)
    window.show()
    closed = []
    window.settings_view.close_requested.connect(lambda: closed.append(True))
    try:
        window.settings_view.move_button.click()
        copied = sqlite3.connect(new_dir / "classroom.db")
        assert [r[0] for r in copied.execute("SELECT name FROM classes")] == ["7B"]
        copied.close()
        assert load_config(config_path).data_dir == new_dir
        assert window.config.data_dir == new_dir and closed
        assert not window.isVisible()  # the app closes to start again on the new folder
    finally:
        window.deleteLater()


def test_settings_page_switches_to_existing_data_without_overwriting(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from app.config import load_config

    other = tmp_path / "other"
    other.mkdir()
    (other / "classroom.db").write_bytes(b"theirs")
    questions = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(other))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: questions.append(a[2]) or QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    window = _window_saving_config(conn, roster, tmp_path, tmp_path / "config.json")
    try:
        window.settings_view.move_data()
        assert "already has Classroom Manager data" in questions[0]
        assert (other / "classroom.db").read_bytes() == b"theirs"
        assert load_config(tmp_path / "config.json").data_dir == other
    finally:
        window.close()
        window.deleteLater()


def test_settings_page_switches_theme(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
):
    from app.config import load_config
    from app.ui import style

    config_path = tmp_path / "config.json"
    window = _window_saving_config(conn, roster, tmp_path, config_path)
    window.show()
    view = window.settings_view
    try:
        assert view.theme_buttons["system"].isChecked()
        view.theme_buttons["dark"].click()
        qapp.processEvents()  # widgets get the new palette from the event loop
        assert style.is_dark(window.attendance_view)
        assert qapp.style().name().lower() == "fusion"
        assert load_config(config_path).theme == "dark"
        view.theme_buttons["light"].click()
        qapp.processEvents()
        assert not style.is_dark(window.attendance_view)
    finally:
        view.theme_buttons["system"].click()  # leave the app as other tests expect it
        qapp.processEvents()
        window.close()
        window.deleteLater()


def test_dashboard_says_whether_todays_register_is_taken(window: MainWindow, roster: RosterService, monkeypatch):
    from datetime import date

    from app.models import AttendanceStatus
    from app.ui.views import dashboard_view

    class Friday(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 6)

    monkeypatch.setattr(dashboard_view, "date", Friday)
    view = _attendance_page(window, roster)  # on Friday 6 November 2026
    dashboard = window.dashboard_view
    dashboard.refresh()
    link = ' <a href="take">Take attendance now</a>'
    assert dashboard.today_label.text() == "Today's register hasn't been taken yet." + link
    view._row_widgets[0][0].buttons[AttendanceStatus.LATE].click()
    dashboard.refresh()
    assert dashboard.today_label.text() == "Today's register: 1 of 2 students marked." + link
    view.mark_rest_button.click()
    dashboard.refresh()
    assert dashboard.today_label.text() == "Today's register is done: 1 present · 1 late."
    assert not dashboard.today_label.isHidden()


def test_paste_dialog_points_out_names_listed_twice(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = PasteStudentsDialog(roster, class_id)
    dialog.text.setPlainText("Ada Lovelace\nAlan Turing\nada lovelace\n")
    assert "Listed twice: Ada Lovelace." in dialog.summary.text()


def test_paste_dialog_leaves_out_students_already_in_the_class(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    dialog = PasteStudentsDialog(roster, class_id)
    dialog.text.setPlainText("Grace Hopper\n")
    assert dialog.skip_existing.isHidden()

    dialog.text.setPlainText("Ada Lovelace\nGrace Hopper\n")
    assert not dialog.skip_existing.isHidden() and dialog.skip_existing.isChecked()
    assert dialog.preview.rowCount() == 1
    assert "Leaving out, already in the class: Ada Lovelace." in dialog.summary.text()
    assert dialog._ok.text() == "Add 1 student"

    dialog.skip_existing.setChecked(False)
    assert dialog.preview.rowCount() == 2 and dialog._ok.text() == "Add 2 students"
    dialog.skip_existing.setChecked(True)
    dialog.accept()
    assert sorted(s.full_name for s in roster.list_students(class_id)) == ["Ada Lovelace", "Grace Hopper"]


def test_paste_dialog_numbers_students_without_one(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = PasteStudentsDialog(roster, class_id)
    dialog.text.setPlainText("Ada Lovelace\nGrace Hopper")
    assert dialog.number_missing.isHidden()  # neither the class nor the list uses numbers
    dialog.text.setPlainText("S01 Ada Lovelace\nGrace Hopper\nAlan Turing")
    assert not dialog.number_missing.isHidden()
    assert dialog.number_missing.text() == "Give the 2 students without a number the next free numbers, S02 to S03"
    assert [dialog.preview.item(row, 0).text() for row in range(3)] == ["S01", "S02", "S03"]
    dialog.number_missing.setChecked(False)
    assert [dialog.preview.item(row, 0).text() for row in range(3)] == ["S01", "", ""]
    dialog.number_missing.setChecked(True)
    dialog.accept()
    assert [s.student_no for s in dialog.added] == ["S01", "S02", "S03"]


def test_paste_dialog_fixes_names_typed_in_capitals(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = PasteStudentsDialog(roster, class_id)
    dialog.text.setPlainText("Ada McDonald\n")
    assert dialog.fix_case.isHidden()

    dialog.text.setPlainText("LOVELACE, ADA\ngrace hopper\n")
    assert not dialog.fix_case.isHidden() and dialog.fix_case.isChecked()
    assert [dialog.preview.item(r, 2).text() for r in range(2)] == ["Lovelace", "Hopper"]
    dialog.fix_case.setChecked(False)
    assert [dialog.preview.item(r, 2).text() for r in range(2)] == ["LOVELACE", "hopper"]
    dialog.fix_case.setChecked(True)
    dialog.accept()
    assert sorted(s.full_name for s in roster.list_students(class_id)) == ["Ada Lovelace", "Grace Hopper"]


def test_roster_deletes_a_student_without_records(
    window: MainWindow, roster: RosterService, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QMessageBox

    class_id = roster.save_class(SchoolClass(name="7B")).id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    alan = roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing"))
    conn.execute("INSERT INTO attendance (student_id, date, status) VALUES (?, '2026-09-01', 'absent')", (alan.id,))
    window.select_class(class_id)
    view = window.classes_view.roster_view
    view._select(alan.id)
    assert not view.delete_button.isEnabled()
    view._select(ada.id)
    assert view.delete_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    view.delete_selected()
    assert [s.full_name for s in roster.list_students(class_id)] == ["Alan Turing"]
    assert window.classes_view.tabs.tabText(0) == "Students (1)"


def test_delete_key_deletes_or_deactivates_the_selected_student(
    window: MainWindow, roster: RosterService, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    class_id = roster.save_class(SchoolClass(name="7B")).id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    alan = roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing"))
    conn.execute("INSERT INTO attendance (student_id, date, status) VALUES (?, '2026-09-01', 'absent')", (alan.id,))
    window.show_page("Manage classes")
    window.select_class(class_id)
    view = window.classes_view.roster_view
    asked: list[str] = []

    def answer_yes(_parent, title, *args):
        asked.append(title)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer_yes)
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window)
    view.table.setFocus()
    view._select(alan.id)
    QTest.keyClick(view.table, Qt.Key.Key_Delete)
    view._select(ada.id)
    QTest.keyClick(view.table, Qt.Key.Key_Delete)

    assert asked == ["Deactivate student", "Delete student"]
    assert roster.list_students(class_id) == []
    assert [s.full_name for s in roster.list_students(class_id, include_inactive=True)] == ["Alan Turing"]


def test_ctrl_v_pastes_the_clipboard_into_the_class_list(
    window: MainWindow, roster: RosterService, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.ui.views import roster_view

    class_id = roster.save_class(SchoolClass(name="7B")).id
    window.show_page("Manage classes")
    window.select_class(class_id)
    view = window.classes_view.roster_view
    opened: list[str] = []

    class FakeDialog:
        def __init__(self, _roster, _class_id, parent=None, text=""):
            opened.append(text)
            self.added = []

        def exec(self):
            return 0

    monkeypatch.setattr(roster_view, "PasteStudentsDialog", FakeDialog)
    qapp.clipboard().setText("Ada Lovelace\nAlan Turing")
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window)
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert opened == ["Ada Lovelace\nAlan Turing"]


def test_escape_clears_the_roster_search(window: MainWindow, roster: RosterService):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    window.select_class(class_id)
    view = window.classes_view.roster_view
    view.search.setText("zzz")
    assert view.model.rowCount() == 0
    QTest.keyClick(view.search, Qt.Key.Key_Escape)
    assert view.search.text() == ""
    assert view.model.rowCount() == 1


def test_roster_copies_the_students_shown(window: MainWindow, roster: RosterService, qapp: QApplication):
    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing"))
    window.select_class(class_id)
    view = window.classes_view.roster_view
    view.search.setText("turing")
    view.copy_list()
    assert qapp.clipboard().text().splitlines()[1:] == ["\tTuring\tAlan\tActive\t"]


def test_ask_save_path_suggests_a_safe_name_and_adds_the_suffix(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QFileDialog

    from app.ui.files import ask_save_path, safe_filename

    assert safe_filename('7B (2026/27): "Maths"') == "7B (2026-27)- -Maths-"
    asked: list[str] = []

    def pick(_parent, _title, start, _filter):
        asked.append(start)
        return str(tmp_path / "chosen"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", pick)
    assert ask_save_path(None, "Export", "7B/7C list", "CSV files", ".csv", tmp_path) == tmp_path / "chosen.csv"
    assert asked == [str(tmp_path / "7B-7C list.csv")]
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    assert ask_save_path(None, "Export", "list", "CSV files", ".csv") is None


def test_exports_open_in_the_folder_used_last(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from PySide6.QtWidgets import QFileDialog

    from app.ui import files

    monkeypatch.setattr(files, "_last_folder", None)
    asked: list[str] = []

    def pick(_parent, _title, start, _filter):
        asked.append(start)
        return str(tmp_path / "reports" / "october.csv"), ""

    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", pick)
    files.ask_save_path(None, "Export", "october", "CSV files", ".csv")
    files.ask_save_path(None, "Save PDF", "november", "PDF files", ".pdf")
    assert asked == [str(Path.home() / "october.csv"), str(tmp_path / "reports" / "november.pdf")]


def test_back_up_now_remembers_the_folder(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import re

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QFileDialog

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    usb = tmp_path / "usb"
    usb.mkdir()
    asked: list[str] = []

    def pick(_parent, _title, start, _filter):
        asked.append(start)
        return str(usb / "copy"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", pick)
    first = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    first.back_up_now()
    first.close()
    assert (usb / "copy.db").exists()
    assert Path(asked[0]).parent == Path.home()
    assert re.fullmatch(r"Classroom backup \d{4}-\d\d-\d\d \d\d-\d\d\.db", Path(asked[0]).name)

    second = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    second.back_up_now()
    second.close()
    assert Path(asked[1]).parent == usb


def test_attendance_month_tooltip_shows_the_note(window: MainWindow, roster: RosterService):
    from datetime import date

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)  # Friday 6 November 2026
    view._row_widgets[0][0].buttons[AttendanceStatus.EXCUSED].click()
    view._row_widgets[0][1].setText("Dentist")
    view._save_note(0)
    view.refresh()
    month = view.month_view
    friday = 1 + month.register.days.index(date(2026, 11, 6))
    assert month.table.item(0, friday).toolTip() == "Grace Hopper, Fri 6 Nov: Excused\nNote: Dentist"
    assert month.table.item(1, friday).toolTip() == "Ada Lovelace, Fri 6 Nov: Not marked"


def test_attendance_note_fields_suggest_earlier_notes(window: MainWindow, roster: RosterService):
    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    view._row_widgets[0][0].buttons[AttendanceStatus.EXCUSED].click()
    view._row_widgets[0][1].setText("Dentist")
    view._save_note(0)
    view.refresh()
    assert view.note_completer.model().stringList()[0] == "Dentist"
    assert view._row_widgets[1][1].completer() is view.note_completer


def test_attendance_note_tooltip_shows_the_whole_note(window: MainWindow, roster: RosterService):
    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    long_note = "Left at 10:30 for a hospital appointment, mother phoned the office beforehand"
    view._row_widgets[0][0].buttons[AttendanceStatus.EXCUSED].click()
    view._row_widgets[0][1].setText(long_note)
    view._save_note(0)
    view.refresh()
    assert view._row_widgets[0][1].toolTip() == long_note
    assert view._row_widgets[1][1].toolTip() == ""


def test_attendance_month_exports_are_off_without_students(window: MainWindow, roster: RosterService):
    view = _attendance_page(window, roster, names=())
    month = view.month_view
    assert not month.export_button.isEnabled()
    assert not month.pdf_button.isEnabled()
    roster.save_student(Student(class_id=window.class_id, first_name="Ada", last_name="Lovelace"))
    view.refresh()
    assert month.export_button.isEnabled() and month.pdf_button.isEnabled()


def test_attendance_month_highlights_today(window: MainWindow, roster: RosterService):
    from datetime import date

    view = _attendance_page(window, roster)
    month = view.month_view
    month._today = lambda: date(2026, 11, 6)
    month.refresh()
    friday = 1 + month.register.days.index(date(2026, 11, 6))
    header = month.table.horizontalHeaderItem(friday)
    assert header.font().bold() and "(today)" in header.toolTip()
    assert not month.table.horizontalHeaderItem(friday - 1).font().bold()


def test_attendance_month_this_month_button(window: MainWindow, roster: RosterService):
    from datetime import date

    view = _attendance_page(window, roster)
    month = view.month_view
    month._today = lambda: date(2026, 11, 6)
    month.refresh()
    assert not month.this_month_button.isEnabled()
    month.prev_button.click()
    month.prev_button.click()
    assert month.month_label.text() == "September 2026" and month.this_month_button.isEnabled()
    month.this_month_button.click()
    assert month.month_label.text() == "November 2026"


def test_attendance_month_enter_opens_the_day(window: MainWindow, roster: RosterService):
    from datetime import date

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = _attendance_page(window, roster)
    month = view.month_view
    view.tabs.setCurrentWidget(month)
    monday = 1 + month.register.days.index(date(2026, 11, 2))
    month.table.setCurrentCell(0, monday)
    QTest.keyClick(month.table, Qt.Key.Key_Return)
    assert view.tabs.currentIndex() == 0 and view.day == date(2026, 11, 2)


def test_marking_the_rest_present_on_a_future_day_asks_first(
    window: MainWindow, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from datetime import date, timedelta

    from PySide6.QtWidgets import QMessageBox

    view = _attendance_page(window, roster)
    view.set_day(date.today() + timedelta(days=7))
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answers.pop(0))
    view.mark_rest_present()
    assert _statuses(view) == [None, None]
    view.mark_rest_present()
    assert _statuses(view) == ["present", "present"]


def test_period_dialog_presets(qapp: QApplication):
    from datetime import date

    from app.ui.dialogs.period_dialog import PeriodDialog, preset_periods

    today = date(2026, 3, 10)  # a Tuesday
    assert preset_periods(today) == {
        "This week": (date(2026, 3, 9), date(2026, 3, 13)),
        "Last week": (date(2026, 3, 2), date(2026, 3, 6)),
        "Last 30 days": (date(2026, 2, 9), date(2026, 3, 10)),
        "This month": (date(2026, 3, 1), date(2026, 3, 31)),
        "Last month": (date(2026, 2, 1), date(2026, 2, 28)),
        "This year": (date(2026, 1, 1), date(2026, 12, 31)),
    }
    dialog = PeriodDialog("Export", date(2026, 1, 1), date(2026, 1, 31), today=today)
    dialog.preset_buttons["Last month"].click()
    assert (dialog.start, dialog.end) == (date(2026, 2, 1), date(2026, 2, 28))
    assert dialog.problem.text() == "20 school days, weekends left out"
    dialog.set_period(date(2026, 3, 2), date(2026, 3, 1))
    assert dialog.problem.text() == "The last day is before the first."


def test_attendance_title_names_the_subject_register(window: MainWindow, roster: RosterService):
    view = _attendance_page(window, roster)
    assert view.title_label.text() == "Attendance · 7B"
    view.register_combo.setCurrentIndex(view.register_combo.findText("Maths"))
    assert view.title_label.text() == "Attendance · 7B · Maths"


def test_alt_home_goes_to_today(window: MainWindow, roster: RosterService):
    from datetime import date

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = _attendance_page(window, roster)
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window)
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key.Key_Home, Qt.KeyboardModifier.AltModifier)
    assert view.day == date.today()


def test_window_lengths_in_labels_follow_the_settings(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.ui.views import attendance_view, dashboard_view

    monkeypatch.setattr(attendance_view, "RECENT_DAYS", 14)
    monkeypatch.setattr(dashboard_view, "CHART_DAYS", 5)
    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    window = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path))
    try:
        assert window.attendance_view.table.horizontalHeaderItem(4).text() == "Last 14 days"
        labels = [w.text() for w in window.dashboard_view.findChildren(QLabel)]
        assert any(t.startswith("Last 5 days with attendance") for t in labels)
    finally:
        window.close()
        window.deleteLater()


def test_clicking_a_dashboard_chart_day_opens_its_register(window: MainWindow, roster: RosterService, conn):
    from datetime import date, timedelta

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    class_id = roster.save_class(SchoolClass(name="7B"), "Maths").id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    days = [date.today() - timedelta(days=n) for n in (9, 8)]
    for day in days:
        conn.execute(
            "INSERT INTO attendance (student_id, date, status) VALUES (?, ?, 'present')", (ada.id, day.isoformat())
        )
    window.select_class(class_id)
    window.show_page("Dashboard")
    chart = window.dashboard_view.chart
    chart.resize(400, 200)
    assert [d.day for d in chart.days] == days
    QTest.mouseClick(chart, Qt.MouseButton.LeftButton, pos=QPoint(chart.width() - 10, 50))  # the second column
    assert window.stack.currentWidget() is window.attendance_view
    assert window.attendance_view.day == days[1]
    assert window.attendance_view.subject_id is None


def test_clicking_a_student_who_needs_attention_shows_their_history(
    window: MainWindow, roster: RosterService, conn, monkeypatch: pytest.MonkeyPatch
):
    from datetime import date, timedelta

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.ui.dialogs.attendance_history_dialog import AttendanceHistoryDialog
    from app.ui.views.dashboard_view import ClickableRow

    class_id = roster.save_class(SchoolClass(name="7B")).id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    for n in (1, 2, 3):
        day = (date.today() - timedelta(days=n)).isoformat()
        conn.execute("INSERT INTO attendance (student_id, date, status) VALUES (?, ?, 'absent')", (ada.id, day))
    shown: list[AttendanceHistoryDialog] = []
    monkeypatch.setattr(AttendanceHistoryDialog, "exec", lambda dialog: shown.append(dialog) or 0)
    window.select_class(class_id)
    window.show_page("Dashboard")
    (row,) = window.dashboard_view.findChildren(ClickableRow)
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.attendance_view
    assert shown and shown[0].windowTitle() == "Attendance · Ada Lovelace"


def test_dashboard_numbers_explain_themselves(window: MainWindow):
    from app.ui.views.dashboard_view import KPI_HELP

    for name, (value, sub) in window.dashboard_view.kpis.items():
        assert value.toolTip() == sub.toolTip() == KPI_HELP[name]


def test_dashboard_links_to_todays_register_until_it_is_taken(window: MainWindow, roster: RosterService, monkeypatch):
    from datetime import date

    from app.ui.views import dashboard_view

    class Friday(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 6)

    monkeypatch.setattr(dashboard_view, "date", Friday)
    view = _attendance_page(window, roster)
    view.set_day(date(2026, 11, 2))
    window.show_page("Dashboard")
    window.dashboard_view.refresh()
    window.dashboard_view.today_label.linkActivated.emit("take")
    assert window.stack.currentWidget() is window.attendance_view
    assert view.day == date(2026, 11, 6)


def test_settings_page_restores_a_backup_from_any_file(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, db_path: Path, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from app.services.backup import copy_database, restore_backup

    roster.save_class(SchoolClass(name="7B"))
    usb = tmp_path / "usb"
    copy_database(db_path, usb / "Classroom backup.db")
    roster.save_class(SchoolClass(name="8C"))
    config = AppConfig(data_dir=tmp_path)
    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    window = MainWindow(
        roster, dashboard, _attendance(conn), config,
        restore_backup=lambda backup: restore_backup(backup, conn, config.db_path, config.backup_dir),
    )  # fmt: skip
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    try:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(db_path), ""))
        window.settings_view.restore_from_file()  # the data file itself is refused
        assert len(roster.list_classes()) == 2
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(usb / "Classroom backup.db"), ""))
        window.settings_view.restore_from_file()
        assert [c.name for c in roster.list_classes()] == ["7B"]
    finally:
        window.close()
        window.deleteLater()


def test_settings_page_checks_the_data_file(window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    from PySide6.QtWidgets import QMessageBox

    from app.ui.views import settings_view

    said: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: said.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: said.append(a[2]))
    window.settings_view.check_button.click()
    assert said[-1] == "No problems found. Your data file is fine."
    monkeypatch.setattr(settings_view, "find_problems", lambda path: ["row 3 missing from index"])
    window.settings_view.check_button.click()
    assert "row 3 missing from index" in said[-1]


def test_settings_page_shows_sizes(window: MainWindow, db_path: Path):
    from datetime import datetime

    from app.services.backup import auto_backup
    from app.ui.views.settings_view import format_size

    assert [format_size(n) for n in (0, 300, 320_000, 5 * 1024 * 1024)] == ["0 KB", "1 KB", "312 KB", "5.0 MB"]
    auto_backup(db_path, window.config.backup_dir, now=datetime(2026, 11, 6, 8, 30))
    view = window.settings_view
    view.refresh()
    assert view.data_size_label.text() == format_size(db_path.stat().st_size)
    assert view.backup_summary.toolTip().endswith(" in all")


def test_settings_page_lists_every_backup_on_request(window: MainWindow, db_path: Path):
    from datetime import datetime

    from app.services.backup import auto_backup
    from app.ui.views.settings_view import SHOWN_BACKUPS

    view = window.settings_view
    auto_backup(db_path, window.config.backup_dir, now=datetime(2026, 11, 1, 8, 0))
    view.refresh()
    assert view.show_all_button.isHidden()

    for day in range(2, 13):
        auto_backup(db_path, window.config.backup_dir, now=datetime(2026, 11, day, 8, 0))
    view.refresh()
    assert view.backup_table.rowCount() == SHOWN_BACKUPS
    assert not view.show_all_button.isHidden() and view.show_all_button.text() == "Show all 12"
    view.show_all_button.click()
    assert view.backup_table.rowCount() == 12
    assert view.backup_table.item(11, 0).text().startswith("Sun 1 Nov 2026")
    view.show_all_button.click()
    assert view.backup_table.rowCount() == SHOWN_BACKUPS


def test_help_menu_lists_the_keyboard_shortcuts(window: MainWindow, monkeypatch: pytest.MonkeyPatch):
    from app.ui.dialogs.shortcuts_dialog import SHORTCUTS, ShortcutsDialog

    shown: list[ShortcutsDialog] = []
    monkeypatch.setattr(ShortcutsDialog, "exec", lambda dialog: shown.append(dialog) or 0)
    (action,) = [a for a in window.menuBar().actions() if a.text() == "&Help"][0].menu().actions()[:1]
    assert action.shortcut().toString() == "F1"
    action.trigger()
    table = shown[0].table
    assert table.rowCount() == len(SHORTCUTS)
    assert any(table.item(r, 1).text() == "Ctrl+Shift+B" for r in range(table.rowCount()))


def test_f5_reloads_the_page_shown(window: MainWindow, roster: RosterService):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    class_id = roster.save_class(SchoolClass(name="7B")).id
    window.select_class(class_id)
    window.show_page("Manage classes")
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))  # e.g. by another page
    assert window.classes_view.roster_view.model.rowCount() == 0
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window)
    QTest.keyClick(window, Qt.Key.Key_F5)
    assert window.classes_view.roster_view.model.rowCount() == 1


def test_file_menu_opens_the_log_file(window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from PySide6.QtGui import QDesktopServices

    from app.ui import main_window

    opened: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    monkeypatch.setattr(main_window, "settings_dir", lambda: tmp_path)
    window.open_log_file()  # no log yet: the folder opens
    (tmp_path / "classroom.log").write_text("log")
    window.open_log_file()
    assert opened == [str(tmp_path), str(tmp_path / "classroom.log")]


def test_paste_dialog_shows_problems_in_the_danger_colour(qapp: QApplication, roster: RosterService):
    from PySide6.QtGui import QPalette

    from app.ui import style
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = PasteStudentsDialog(roster, class_id)
    dialog.text.setPlainText("Plato\n")
    assert "needs a first and a last name" in dialog.problems.text()
    shown = dialog.problems.palette().color(QPalette.ColorRole.WindowText)
    assert shown == style.color(dialog, "danger")


def test_new_year_dialog_ticks_or_unticks_every_class(qapp: QApplication, roster: RosterService):
    from PySide6.QtCore import Qt

    from app.ui.dialogs.new_year_dialog import NewYearDialog

    for name in ("7A", "7B", "7C"):
        roster.save_class(SchoolClass(name=name, term="2025-2026"))
    dialog = NewYearDialog(roster, "2025-2026")
    assert dialog.tick_all_button.text() == "Untick all"
    dialog.tick_all_button.click()
    assert dialog.plan() == [] and dialog.tick_all_button.text() == "Tick all"
    dialog.table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    assert [name for _id, name in dialog.plan()] == ["7B"]
    dialog.tick_all_button.click()
    assert len(dialog.plan()) == 3 and dialog.tick_all_button.text() == "Untick all"


def test_subject_dialog_offers_names_from_other_classes(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.subject_dialog import SubjectDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = SubjectDialog(roster.save_subject, class_id, names=["Maths", "Science"], teachers=["Mr Lee"])
    assert dialog.name.completer().model().rowCount() == 2
    assert dialog.teacher.completer().model().rowCount() == 1


def test_manage_classes_renames_the_school_year_shown(
    window: MainWindow, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QInputDialog

    class_id = roster.save_class(SchoolClass(name="7B", term="2026-207")).id
    roster.save_class(SchoolClass(name="8C", term="2026-207"))
    window.select_class(class_id)
    view = window.classes_view
    asked: list[str] = []

    def answer(_parent, _title, label, *args, text=""):
        asked.append(label + " | " + text)
        return "2026-2027", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    assert view.rename_year_button.isEnabled()
    view.rename_year_button.click()
    assert asked == ["New school year for the 2 classes of 2026-207: | 2026-207"]
    assert roster.list_terms() == ["2026-2027"]
    assert window.windowTitle() == "Classroom Manager — 7B (2026-2027)"

    # A year picked in the list is the one renamed.
    view.year_combo.setCurrentIndex(view.year_combo.findData("2026-2027"))
    view._on_year_picked(view.year_combo.currentIndex())
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("2027", True))
    view.rename_year_button.click()
    assert roster.list_terms() == ["2027"]
    assert view.year_combo.currentText() == "2027"


def test_manage_classes_copies_subjects_from_another_class(
    window: MainWindow, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtWidgets import QInputDialog

    source = roster.save_class(SchoolClass(name="7A", term="2026"), "Maths").id
    roster.save_subject(Subject(class_id=source, name="Science", teacher="Mr Smith"))
    target = roster.save_class(SchoolClass(name="7B", term="2026")).id
    window.select_class(target)
    offered: list[list[str]] = []

    def pick(_parent, _title, _label, items, *args):
        offered.append(list(items))
        return items[0], True

    monkeypatch.setattr(QInputDialog, "getItem", pick)
    window.classes_view.copy_subjects_button.click()
    assert offered == [["7A (2026) · 2 subjects"]]
    assert [s.name for s in roster.list_subjects(target)] == ["Maths", "Science"]
    assert window.classes_view.subject_table.rowCount() == 2
    assert window.subject_id == roster.list_subjects(target)[0].id


def test_history_dialog_exports_the_students_marks(
    qapp: QApplication, roster: RosterService, conn: sqlite3.Connection, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from datetime import date

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from app.ui.dialogs.attendance_history_dialog import AttendanceHistoryDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace")).id
    service = _attendance(conn)
    assert not AttendanceHistoryDialog(service.student_history(ada), "Daily (homeroom)").export_button.isEnabled()
    service.mark(ada, date(2026, 11, 2), "absent")
    service.mark(ada, date(2026, 11, 3), "present")
    dialog = AttendanceHistoryDialog(service.student_history(ada), "Daily (homeroom)")
    suggested: list[str] = []

    def save_name(_parent, _title, start, _filter):
        suggested.append(start)
        return str(tmp_path / "ada"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_name)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    dialog.export_button.click()
    assert Path(suggested[0]).name == "Ada Lovelace attendance Daily (homeroom).csv"
    assert (tmp_path / "ada.csv").read_text(encoding="utf-8-sig").splitlines()[1:] == [
        "2026-11-02,Monday,Absent,", "2026-11-03,Tuesday,Present,"
    ]


def test_attendance_copies_the_days_absences(
    window: MainWindow, roster: RosterService, conn: sqlite3.Connection, qapp: QApplication
):
    from datetime import date

    class_id = roster.save_class(SchoolClass(name="7B")).id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace")).id
    roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing"))
    window.select_class(class_id)
    window.show_page("Attendance")
    view = window.attendance_view
    view.set_day(date(2026, 11, 2))
    assert not view.copy_button.isEnabled()
    _attendance(conn).mark(ada, date(2026, 11, 2), "absent")
    view.refresh()
    view.copy_button.click()
    assert qapp.clipboard().text() == (
        "7B · Daily (homeroom) · Monday 2 November 2026\nAbsent (1): Ada Lovelace\nNot marked (1): Alan Turing\n"
        "In class: 0 of 2.\n"
    )
    assert view.status_label.text().startswith("Copied")

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    qapp.clipboard().clear()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert qapp.clipboard().text().startswith("7B · Daily (homeroom)")


def test_status_bar_reminds_to_back_up_elsewhere(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from datetime import datetime, timedelta

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QFileDialog

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)

    def open_window() -> MainWindow:
        return MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)

    empty = open_window()  # nothing to back up yet
    assert empty.statusBar().currentMessage().startswith("Data file:")
    empty.close()

    roster.save_class(SchoolClass(name="7B"))
    never = open_window()
    assert never.statusBar().currentMessage().startswith("Your data has never been backed up elsewhere.")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "copy.db"), ""))
    never.back_up_now()
    never.close()

    recent = open_window()
    assert recent.statusBar().currentMessage().startswith("Data file:")
    recent.close()

    settings.setValue("backup/last", (datetime.now() - timedelta(days=40)).isoformat())
    old = open_window()
    assert "last backed up elsewhere 40 days ago" in old.statusBar().currentMessage()
    old.close()


def test_attendance_shows_absences_in_a_row(window: MainWindow, roster: RosterService):
    from datetime import date

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster, ("Ada Lovelace",))
    ada = view.register.rows[0].student.id
    for day in (date(2026, 11, 4), date(2026, 11, 5)):
        view.attendance.mark(ada, day, AttendanceStatus.ABSENT)
    view.refresh()
    recent = view.table.item(0, 4)
    assert recent.text() == "2 absences (2 in a row)"
    assert "last 2 registers" in recent.toolTip()


def test_attendance_subject_register_copies_from_daily(window: MainWindow, roster: RosterService):
    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    assert view.daily_button.isHidden()  # the daily register itself
    view._row_widgets[1][0].buttons[AttendanceStatus.ABSENT].click()  # Lovelace
    view.register_combo.setCurrentIndex(1)  # Maths
    assert not view.daily_button.isHidden()
    assert view.daily_button.text() == "Copy from daily (1)"

    view.daily_button.click()
    assert _statuses(view) == [None, "absent"]
    assert view.status_label.text() == "Marked 1 student as in the daily register"
    assert view.daily_button.text() == "Copy from daily" and not view.daily_button.isEnabled()
    view.copy_from_daily()
    assert view.status_label.text().startswith("No one")
    view.undo()
    assert _statuses(view) == [None, None]


def test_attendance_marks_a_student_for_several_days(window: MainWindow, roster: RosterService, monkeypatch, qapp):
    from datetime import date

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.models import AttendanceStatus
    from app.ui.dialogs.mark_days_dialog import MarkDaysDialog

    view = _attendance_page(window, roster)  # Friday 6 November 2026
    dialog_seen = {}

    def fake_exec(dialog: MarkDaysDialog) -> int:
        assert (dialog.start, dialog.end) == (date(2026, 11, 6), date(2026, 11, 6))
        dialog.set_period(date(2026, 11, 6), date(2026, 11, 7))
        assert dialog.days_label.text() == "1 school day"
        dialog.set_period(date(2026, 11, 7), date(2026, 11, 8))
        assert not dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
        dialog.set_period(date(2026, 11, 4), date(2026, 11, 10))
        assert dialog.days_label.text() == "5 school days"
        dialog_seen["title"] = dialog.windowTitle()
        dialog.note_edit.setText("Sick note")
        return 1

    monkeypatch.setattr(MarkDaysDialog, "exec", fake_exec)
    view._row_widgets[1][0].buttons[AttendanceStatus.PRESENT].click()  # Lovelace, already marked today
    view.table.setCurrentCell(1, 1)
    QTest.keyClick(view.table, Qt.Key.Key_D)
    assert dialog_seen["title"] == "Mark several days · Ada Lovelace"
    assert _statuses(view) == [None, "present"]  # kept
    assert view.status_label.text() == "Marked Ada Lovelace excused on 4 days · 1 day already marked kept as before"
    history = view.attendance.student_history(view.register.rows[1].student.id)
    assert [r.date.day for r in history.records] == [10, 9, 6, 5, 4]
    assert history.records[0].note == "Sick note"

    view.set_day(date(2026, 11, 20))
    view.undo()  # every day goes back, and the page shows the first of them
    assert view.day == date(2026, 11, 4)
    history = view.attendance.student_history(view.register.rows[1].student.id)
    assert [r.date.day for r in history.records] == [6]


def test_attendance_find_shows_matching_students(window: MainWindow, roster: RosterService, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = _attendance_page(window, roster, ("Ada Lovelace", "Grace Hopper", "Alan Turing", "Alan Kay"))
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    QTest.keyClick(view.table, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert view.find_edit.hasFocus()

    QTest.keyClicks(view.find_edit, "alan")
    shown = [view.register.rows[i].student.full_name for i in view._visible_rows()]
    assert shown == ["Alan Kay", "Alan Turing"]  # the list is sorted by last name

    QTest.keyClick(view.find_edit, Qt.Key.Key_Return)  # back to the list, on the first student found
    assert view.table.hasFocus()
    assert view.register.rows[view.table.currentRow()].student.full_name == "Alan Kay"
    QTest.keyClick(view.table, Qt.Key.Key_A)  # marks and moves to the next student shown
    assert view.register.rows[view.table.currentRow()].student.full_name == "Alan Turing"
    QTest.keyClick(view.table, Qt.Key.Key_P)
    assert _statuses(view) == [None, "absent", None, "present"]

    view.refresh()  # stays filtered after a change
    assert len(view._visible_rows()) == 2
    view.find_edit.setFocus()
    QTest.keyClick(view.find_edit, Qt.Key.Key_Escape)
    assert view.find_edit.text() == "" and len(view._visible_rows()) == 4


def test_attendance_clear_the_day_says_what_goes(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    note = view._row_widgets[0][1]
    note.setText("Flu")
    note.editingFinished.emit()
    view.mark_rest_button.click()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, text: asked.append(text) or QMessageBox.StandardButton.No)
    view.clear_day()
    assert asked[0].startswith("Remove 2 marks and 1 note for Friday 6 November in the Daily (homeroom) register?")
    assert _statuses(view) == ["absent", "present"]


def test_attendance_redo(window: MainWindow, roster: RosterService):
    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    assert not view.redo_button.isEnabled()
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    view.mark_rest_button.click()
    view.undo()
    view.undo()
    assert _statuses(view) == [None, None]
    assert view.redo_button.toolTip().startswith("Redo: mark Grace Hopper absent")
    view.redo()
    assert _statuses(view) == ["absent", None]
    view.redo()
    assert _statuses(view) == ["absent", "present"] and not view.redo_button.isEnabled()
    view.undo()
    view._row_widgets[1][0].buttons[AttendanceStatus.LATE].click()  # a new change: nothing left to redo
    assert not view.redo_button.isEnabled()
    view.redo()
    assert _statuses(view) == ["absent", "late"]

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert _statuses(view) == ["absent", None]
    QTest.keyClick(view.table, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert _statuses(view) == ["absent", "late"]


def test_attendance_u_goes_to_the_next_student_not_marked(window: MainWindow, roster: RosterService, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster, ("Ada Lovelace", "Grace Hopper", "Alan Turing", "Alan Kay"))
    for i in (1, 2):  # Kay, Lovelace
        view._row_widgets[i][0].buttons[AttendanceStatus.PRESENT].click()
    view.table.setCurrentCell(0, 1)
    QTest.keyClick(view.table, Qt.Key.Key_U)
    assert view.table.currentRow() == 3  # Turing
    QTest.keyClick(view.table, Qt.Key.Key_U)
    assert view.table.currentRow() == 0  # round to the top: Hopper


def test_attendance_row_menu(window: MainWindow, roster: RosterService):
    view = _attendance_page(window, roster)
    menu = view.row_menu(0)
    actions = {a.text().split("\t")[0]: a for a in menu.actions() if a.text()}
    assert list(actions) == [
        "Present", "Late", "Absent", "Excused", "Clear the mark", "Write a note", "Mark several days…", "Show history…"
    ]
    assert not actions["Clear the mark"].isEnabled() and not actions["Write a note"].isEnabled()
    actions["Absent"].trigger()
    assert _statuses(view) == ["absent", None]
    menu = view.row_menu(0)
    actions = {a.text().split("\t")[0]: a for a in menu.actions() if a.text()}
    assert actions["Absent"].isChecked() and actions["Clear the mark"].isEnabled()
    actions["Clear the mark"].trigger()
    assert _statuses(view) == [None, None]


def test_attendance_hides_the_number_column_without_numbers(window: MainWindow, roster: RosterService):
    view = _attendance_page(window, roster)
    assert view.table.isColumnHidden(0)
    student = view.register.rows[0].student
    student.student_no = "S01"
    roster.save_student(student)
    view.refresh()
    assert not view.table.isColumnHidden(0)
    assert view.table.item(0, 0).text() == "S01"


def test_attendance_sorts_by_number_and_remembers_it(
    qapp: QApplication, conn: sqlite3.Connection, roster: RosterService, tmp_path: Path
):
    from PySide6.QtCore import QSettings

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    first = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    view = _attendance_page(first, roster)
    for row, no in zip(view.register.rows, ("10", "2")):  # Hopper 10, Lovelace 2
        row.student.student_no = no
        roster.save_student(row.student)
    view.table.horizontalHeader().sectionClicked.emit(0)
    assert [r.student.student_no for r in view.register.rows] == ["2", "10"]
    assert view.table.item(0, 1).text() == "Ada Lovelace"
    view.table.horizontalHeader().sectionClicked.emit(1)
    assert [r.student.last_name for r in view.register.rows] == ["Hopper", "Lovelace"]
    view.table.horizontalHeader().sectionClicked.emit(0)
    first.close()

    second = MainWindow(roster, dashboard, _attendance(conn), AppConfig(data_dir=tmp_path), settings)
    assert second.attendance_view.by_number
    second.close()


def test_attendance_shows_a_dash_for_a_student_without_a_number(window: MainWindow, roster: RosterService):
    view = _attendance_page(window, roster)
    assert view.table.isColumnHidden(0)  # nobody has a number
    hopper = view.register.rows[0].student
    hopper.student_no = "S01"
    roster.save_student(hopper)
    view.refresh()
    assert not view.table.isColumnHidden(0)
    assert [view.table.item(i, 0).text() for i in range(2)] == ["S01", "—"]
    assert "No student number" in view.table.item(1, 0).toolTip()
    assert view.table.item(0, 0).toolTip() == ""


def test_attendance_name_tooltip_shows_the_last_mark(window: MainWindow, roster: RosterService):
    from datetime import date

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)  # Friday 6 November
    ada = view.register.rows[1].student.id
    view.attendance.mark(ada, date(2026, 11, 3), AttendanceStatus.PRESENT)
    view.attendance.mark(ada, date(2026, 11, 5), AttendanceStatus.LATE)
    view.attendance.mark(ada, date(2026, 11, 9), AttendanceStatus.ABSENT)  # after the day shown
    view.refresh()
    assert view.table.item(1, 1).toolTip() == "Not marked yet\nLast marked late on Thu 5 Nov"
    assert view.table.item(0, 1).toolTip() == "Not marked yet"


def test_attendance_number_keys_and_space_mark(window: MainWindow, roster: RosterService, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = _attendance_page(window, roster, ("Ada Lovelace", "Grace Hopper", "Alan Turing", "Alan Kay", "Kim Lee"))
    view.table.setCurrentCell(0, 1)
    QTest.keyClick(view.table, Qt.Key.Key_3)
    QTest.keyClick(view.table, Qt.Key.Key_2, Qt.KeyboardModifier.KeypadModifier)
    QTest.keyClick(view.table, Qt.Key.Key_4)
    QTest.keyClick(view.table, Qt.Key.Key_1)
    QTest.keyClick(view.table, Qt.Key.Key_Space)
    assert _statuses(view) == ["absent", "late", "excused", "present", "present"]


def test_attendance_arrows_move_between_notes(window: MainWindow, roster: RosterService, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster, ("Ada Lovelace", "Grace Hopper", "Alan Turing"))
    for i in (0, 1):
        view._row_widgets[i][0].buttons[AttendanceStatus.LATE].click()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    first, second = view._row_widgets[0][1], view._row_widgets[1][1]
    first.setFocus()
    QTest.keyClicks(first, "Bus")
    QTest.keyClick(first, Qt.Key.Key_Down)
    assert second.hasFocus() and view.table.currentRow() == 1
    assert view.register.rows[0].note == "Bus"  # saved on leaving
    QTest.keyClick(second, Qt.Key.Key_Down)  # Turing isn't marked: back to the list
    assert view.table.hasFocus() and view.table.currentRow() == 2


def test_attendance_goes_on_to_the_new_day_after_midnight(window: MainWindow, roster: RosterService):
    from datetime import date

    view = _attendance_page(window, roster)
    view._clock = lambda: date(2026, 11, 6)
    view.refresh()
    view._clock = lambda: date(2026, 11, 7)
    view.follow_today()
    assert view.day == date(2026, 11, 7)

    view._clock = lambda: date(2026, 11, 9)
    view.set_day(date(2026, 11, 2))  # an earlier day picked on purpose stays
    view.follow_today()
    assert view.day == date(2026, 11, 2)


def test_attendance_register_picker_names_the_teacher(window: MainWindow, roster: RosterService):
    view = _attendance_page(window, roster)
    roster.save_subject(Subject(class_id=window.class_id, name="Science", teacher="Mr Dara"))
    view.set_subject(None)
    assert [view.register_combo.itemText(i) for i in range(view.register_combo.count())] == [
        "Daily (homeroom)", "Maths", "Science · Mr Dara"
    ]
    view.register_combo.setCurrentIndex(2)
    assert view.register_name == "Science"
    assert view.title_label.text() == "Attendance · 7B · Science"


def test_attendance_without_students_links_to_manage_classes(window: MainWindow, roster: RosterService):
    view = _attendance_page(window, roster, ())
    assert view.status_label.text().startswith("No active students in this class.")
    view.status_label.linkActivated.emit("Manage classes")
    assert window.stack.currentWidget() is window.classes_view


def test_attendance_month_cells_can_be_marked(window: MainWindow, roster: RosterService, qapp):
    from datetime import date

    from app.models import AttendanceStatus

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = _attendance_page(window, roster)  # Friday 6 November 2026
    view.tabs.setCurrentWidget(view.month_view)
    month = view.month_view
    col = 1 + month.register.days.index(date(2026, 11, 4))
    month.table.setCurrentCell(0, col)
    QTest.keyClick(month.table, Qt.Key.Key_A)
    QTest.keyClick(month.table, Qt.Key.Key_L)
    assert [r.statuses.get(date(2026, 11, 4)) for r in month.register.rows] == [
        AttendanceStatus.ABSENT, AttendanceStatus.LATE
    ]
    assert month.table.currentRow() == 1 and month.table.currentColumn() == col
    QTest.keyClick(month.table, Qt.Key.Key_Delete)
    assert month.register.rows[1].statuses == {}
    month.table.setCurrentCell(0, 0)  # a name: nothing to mark
    QTest.keyClick(month.table, Qt.Key.Key_P)
    assert month.register.rows[0].statuses == {date(2026, 11, 4): AttendanceStatus.ABSENT}

    view.undo()  # the clearing
    assert month.register.rows[1].statuses == {date(2026, 11, 4): AttendanceStatus.LATE}
    assert view.day == date(2026, 11, 4)  # undo shows the day it changes
    view.undo()
    view.undo()
    assert month.register.rows[0].statuses == {}


def test_attendance_month_name_opens_the_history(window: MainWindow, roster: RosterService, monkeypatch):
    from app.ui.views import attendance_view

    shown = []

    class FakeDialog:
        chosen_day = None

        def __init__(self, history, register_name, *_args):
            shown.append((history.student.full_name, register_name))

        def exec(self):
            return 0

    monkeypatch.setattr(attendance_view, "AttendanceHistoryDialog", FakeDialog)
    view = _attendance_page(window, roster)
    view.month_view.table.cellDoubleClicked.emit(1, 0)
    assert shown == [("Ada Lovelace", "Daily (homeroom)")]
    view.month_view.table.cellDoubleClicked.emit(2, 0)  # the "Absent that day" row
    assert len(shown) == 1


def test_attendance_month_shades_weekend_days(window: MainWindow, roster: RosterService):
    from datetime import date

    from PySide6.QtCore import Qt

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    saturday = date(2026, 11, 7)
    view.attendance.mark(view.register.rows[0].student.id, saturday, AttendanceStatus.PRESENT)
    view.refresh()
    month = view.month_view
    col = 1 + month.register.days.index(saturday)
    assert "(weekend)" in month.table.horizontalHeaderItem(col).toolTip()
    no_brush = Qt.BrushStyle.NoBrush
    assert month.table.item(1, col).background().style() != no_brush  # Lovelace isn't marked: shaded
    friday = 1 + month.register.days.index(date(2026, 11, 6))
    assert month.table.item(1, friday).background().style() == no_brush


def test_attendance_month_names_days_without_a_register(window: MainWindow, roster: RosterService):
    from datetime import date

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    month = view.month_view
    month._today = lambda: date(2026, 11, 6)
    student = view.register.rows[0].student.id
    for day in (2, 3, 5):
        view.attendance.mark(student, date(2026, 11, day), AttendanceStatus.PRESENT)
    view.refresh()
    assert not month.not_taken_label.isHidden()
    assert month.not_taken_label.text().startswith("No register taken on Wed 4, Fri 6.")
    for day in (4, 6):
        view.attendance.mark(student, date(2026, 11, day), AttendanceStatus.PRESENT)
    view.refresh()
    assert month.not_taken_label.isHidden()

    month._today = lambda: date(2026, 11, 30)
    month.refresh()
    assert " and 8 more." in month.not_taken_label.text()  # 16 school days left in November


def test_attendance_month_copies_as_a_table(window: MainWindow, roster: RosterService, qapp):
    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()
    view.month_view.copy_button.click()
    lines = qapp.clipboard().text().splitlines()
    assert lines[0].startswith("Student #\tLast name\tFirst name\t2026-11-02\t")
    assert lines[1].split("\t")[1:3] == ["Hopper", "Grace"]
    assert "\tA\t" in lines[1]
    assert lines[-1].split("\t")[1] == "Whole class"


def test_attendance_month_keys_change_the_month(window: MainWindow, roster: RosterService, qapp):
    from datetime import date

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = _attendance_page(window, roster)
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    view.tabs.setCurrentWidget(view.month_view)
    month = view.month_view
    month.table.setFocus()
    QTest.keyClick(month.table, Qt.Key.Key_PageDown)
    assert month.month_label.text() == "December 2026"
    QTest.keyClick(month.table, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    QTest.keyClick(month.table, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert month.month_label.text() == "October 2026"
    assert view.day == date(2026, 11, 6)  # the Day tab keeps its day
    QTest.keyClick(month.table, Qt.Key.Key_Home, Qt.KeyboardModifier.AltModifier)
    today = date.today()
    assert (month.year, month.month) == (today.year, today.month)
    assert view.day == date(2026, 11, 6)


def test_attendance_history_dialog_shows_absence_runs(qapp: QApplication):
    from datetime import date

    from app.models import AttendanceRecord, AttendanceStatus
    from app.services.attendance import StudentHistory
    from app.ui.dialogs.attendance_history_dialog import AttendanceHistoryDialog

    student = Student(class_id=1, first_name="Ada", last_name="Lovelace", id=1)
    A, P = AttendanceStatus.ABSENT, AttendanceStatus.PRESENT
    statuses = [A, A, P, A, A, A]  # newest first
    records = [AttendanceRecord(1, date(2026, 11, 20 - n), s) for n, s in enumerate(statuses)]
    dialog = AttendanceHistoryDialog(StudentHistory(student, records), "Daily (homeroom)")
    assert dialog.runs_label.text() == "Absent the last 2 marked days in a row · longest run of absences: 3 days"
    dialog = AttendanceHistoryDialog(StudentHistory(student, records[2:3]), "Daily (homeroom)")
    assert dialog.runs_label.isHidden()


def test_attendance_history_dialog_by_month(qapp: QApplication):
    from datetime import date

    from app.models import AttendanceRecord, AttendanceStatus
    from app.services.attendance import StudentHistory
    from app.ui.dialogs.attendance_history_dialog import AttendanceHistoryDialog

    student = Student(class_id=1, first_name="Ada", last_name="Lovelace", id=1)
    A, P, L = AttendanceStatus.ABSENT, AttendanceStatus.PRESENT, AttendanceStatus.LATE
    records = [AttendanceRecord(1, date(2026, 11, 3), A), AttendanceRecord(1, date(2026, 11, 2), P),
               AttendanceRecord(1, date(2026, 10, 30), L)]  # fmt: skip
    dialog = AttendanceHistoryDialog(StudentHistory(student, records), "Daily (homeroom)")
    table = dialog.months_table
    rows = [[table.item(r, c).text() for c in range(6)] for r in range(table.rowCount())]
    assert rows == [["November 2026", "1", "0", "1", "0", "50%"], ["October 2026", "0", "1", "0", "0", "100%"]]
    empty = AttendanceHistoryDialog(StudentHistory(student, []), "Daily (homeroom)")
    assert not empty.tabs.isTabEnabled(1)


def test_attendance_history_dialog_enter_opens_the_day(qapp: QApplication):
    from datetime import date

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.models import AttendanceRecord, AttendanceStatus
    from app.services.attendance import StudentHistory
    from app.ui.dialogs.attendance_history_dialog import AttendanceHistoryDialog

    student = Student(class_id=1, first_name="Ada", last_name="Lovelace", id=1)
    records = [AttendanceRecord(1, date(2026, 11, 4), AttendanceStatus.LATE),
               AttendanceRecord(1, date(2026, 11, 3), AttendanceStatus.ABSENT)]  # fmt: skip
    dialog = AttendanceHistoryDialog(StudentHistory(student, records), "Daily (homeroom)")
    dialog.table.setCurrentCell(1, 0)
    QTest.keyClick(dialog.table, Qt.Key.Key_Return)
    assert dialog.chosen_day == date(2026, 11, 3) and dialog.result() == dialog.DialogCode.Accepted


def test_attendance_ctrl_enter_marks_the_rest_present(window: MainWindow, roster: RosterService, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = _attendance_page(window, roster)
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    view.table.setFocus()
    QTest.keyClick(view.table, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert _statuses(view) == ["present", "present"]


def test_attendance_history_dialog_switches_register(window: MainWindow, roster: RosterService, monkeypatch):
    from datetime import date

    from app.models import AttendanceStatus
    from app.ui.dialogs.attendance_history_dialog import AttendanceHistoryDialog

    view = _attendance_page(window, roster)  # Friday 6 November
    grace = view.register.rows[0].student.id
    maths = view.register_combo.itemData(1)
    view.attendance.mark(grace, date(2026, 11, 4), AttendanceStatus.ABSENT, maths)
    seen = []

    def pick_in_maths(dialog):
        seen.append(dialog.subtitle.text())
        dialog.register_combo.setCurrentIndex(1)
        seen.append(dialog.subtitle.text())
        dialog.table.cellDoubleClicked.emit(0, 0)
        return dialog.result()

    monkeypatch.setattr(AttendanceHistoryDialog, "exec", pick_in_maths)
    view.show_history(0)
    assert seen == ["Daily (homeroom) register · 0 marked days", "Maths register · 1 marked day"]
    assert view.register_name == "Maths" and view.day == date(2026, 11, 4)


def test_attendance_export_period_as_pdf(window: MainWindow, roster: RosterService, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from app.models import AttendanceStatus
    from app.ui.dialogs.period_dialog import PeriodDialog

    view = _attendance_page(window, roster)
    view._row_widgets[0][0].buttons[AttendanceStatus.ABSENT].click()

    def press_pdf(dialog):
        dialog.pdf_button.click()
        return dialog.result()

    saved = tmp_path / "term.pdf"
    told = []
    monkeypatch.setattr(PeriodDialog, "exec", press_pdf)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(saved), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: told.append(args[2]))
    view.month_view.export_period()
    assert saved.read_bytes().startswith(b"%PDF")
    assert told == [f"Saved 1 recorded day to\n{saved}"]


def test_attendance_month_scrolls_to_today(window: MainWindow, roster: RosterService, qapp):
    from datetime import date

    view = _attendance_page(window, roster)
    month = view.month_view
    month._today = lambda: date(2026, 11, 30)
    view.tabs.setCurrentWidget(month)
    month.table.setFixedWidth(400)  # a small screen: the month doesn't fit
    qapp.processEvents()
    month.step(1)
    month.step(-1)  # November opened again
    bar = month.table.horizontalScrollBar()
    assert bar.maximum() > 0 and bar.value() > bar.maximum() // 2  # the 30th is near the end


def test_roster_opens_a_students_attendance_history(window: MainWindow, roster: RosterService, monkeypatch):
    from app.ui.views import attendance_view

    shown = []

    class FakeDialog:
        chosen_day = None

        def __init__(self, history, register_name, *_args):
            shown.append((history.student.full_name, register_name))

        def exec(self):
            return 0

    monkeypatch.setattr(attendance_view, "AttendanceHistoryDialog", FakeDialog)
    class_id = roster.save_class(SchoolClass(name="7B")).id
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace"))
    window.select_class(class_id)
    window.show_page("Manage classes")
    view = window.classes_view.roster_view
    assert not view.history_button.isEnabled()
    view.table.selectRow(0)
    view.history_button.click()
    assert shown == [("Ada Lovelace", "Daily (homeroom)")]


def test_attendance_week_strip(window: MainWindow, roster: RosterService):
    from datetime import date

    from app.models import AttendanceStatus

    view = _attendance_page(window, roster)  # Friday 6 November
    view.mark_rest_button.click()
    view.attendance.mark(view.register.rows[0].student.id, date(2026, 11, 4), AttendanceStatus.ABSENT)
    view.refresh()
    assert [b.text() for b in view.week_buttons] == ["Mon", "Tue", "Wed •", "Thu", "Fri ✓"]
    assert view.week_buttons[4].isChecked()
    assert view.week_buttons[2].toolTip() == "Wednesday 4 November: 1 of 2 marked"
    view.week_buttons[2].click()
    assert view.day == date(2026, 11, 4) and view.week_buttons[2].isChecked()
    assert not view.week_buttons[4].isChecked()


def test_mark_days_dialog_says_when_days_are_still_ahead(qapp: QApplication):
    from datetime import date

    from app.ui.dialogs.mark_days_dialog import MarkDaysDialog

    friday = date(2026, 11, 6)
    dialog = MarkDaysDialog("Ada Lovelace", "Daily (homeroom)", friday, today=friday)
    dialog.set_period(date(2026, 11, 4), date(2026, 11, 10))
    assert dialog.days_label.text() == "5 school days, 2 of them still ahead"
    dialog.set_period(date(2026, 11, 4), friday)
    assert dialog.days_label.text() == "3 school days"
    dialog.set_period(date(1990, 1, 1), friday)
    assert dialog.start == date(2000, 1, 1)  # no earlier than the service allows
