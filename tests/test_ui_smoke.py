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
    assert view.status_label.text() == "2 students are not marked yet. They don't count as present."


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
    assert view.status_label.text() == "Everyone is marked."
    assert not view.mark_rest_button.isEnabled()
    assert view.rate_label.text() == "50%"

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
