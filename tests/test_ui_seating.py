"""The Seating page, built in the real window offscreen."""

from app.models import SchoolClass, SeatLayout, Student
from app.services.roster import RosterService
from app.ui.main_window import MainWindow
from tests.test_ui_smoke import qapp, window  # noqa: F401  (fixtures)


def _seated_class(window: MainWindow, roster: RosterService, rows: int = 2, cols: int = 3) -> tuple[int, int, dict[str, int]]:
    """7B with Ada, Bob and Cy and a "Tests" plan of `rows` × `cols`.
    Returns (class id, layout id, {first name: student id})."""
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    ids = {
        first: roster.save_student(Student(class_id, first, last)).id
        for first, last in (("Ada", "Lovelace"), ("Bob", "Smith"), ("Cy", "Young"))
    }
    layout = window.seating_view.seating.save_layout(SeatLayout(class_id, "Tests", rows, cols)).id
    window.select_class(class_id)
    return class_id, layout, ids


def _grid(window: MainWindow) -> list[list[str]]:
    grid = window.seating_view.grid
    return [[grid.item(r, c).text() for c in range(grid.columnCount())] for r in range(grid.rowCount())]


def _unseated(window: MainWindow) -> list[str]:
    unseated = window.seating_view.unseated
    return [unseated.item(i).text() for i in range(unseated.count())]


def test_seating_asks_for_a_class_then_a_plan(window: MainWindow, roster: RosterService, monkeypatch):
    from app.ui.views import seating_view

    view = window.seating_view
    window.show_page("Seating")
    assert window.stack.currentWidget() is view
    assert "No class selected" in view.empty_label.text()
    assert view.empty_button.isHidden() and not view.new_button.isEnabled()

    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    window.select_class(class_id)
    assert "No seating plan yet" in view.empty_label.text()
    assert not view.empty_button.isHidden()

    class FakeDialog:
        def __init__(self, save, class_id, layout=None, parent=None, default_name=""):
            assert default_name == "Seating plan"
            self.saved = save(SeatLayout(class_id, default_name, 4, 5))

        def exec(self):
            return True

    monkeypatch.setattr(seating_view, "LayoutDialog", FakeDialog)
    view.empty_button.click()
    assert view.pages.currentWidget() is view.plan_page
    assert view.layout_combo.currentText() == "Seating plan (4 × 5)"
    assert (view.grid.rowCount(), view.grid.columnCount()) == (4, 5)


def test_seating_shows_the_room_front_at_the_bottom(window: MainWindow, roster: RosterService):
    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Ada"], 0, 0)  # front row, left
    view.seating.place(layout, ids["Bob"], 1, 2)  # back row, right
    view.refresh()
    assert _grid(window) == [["", "", "Bob Smith"], ["Ada Lovelace", "", ""]]
    assert _unseated(window) == ["Cy Young"]
    assert view.unseated_label.text() == "Not seated (1)"
    assert view.summary.text() == "2 of 3 students seated · 4 free seats"
    assert view.grid.verticalHeaderItem(1).text() == "1"  # row 1 is the front


def test_seating_lists_the_class_plans(window: MainWindow, roster: RosterService):
    class_id, layout, _ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.save_layout(SeatLayout(class_id, "Group work", 3, 4))
    view.refresh()
    assert [view.layout_combo.itemText(i) for i in range(view.layout_combo.count())] == [
        "Group work (3 × 4)",
        "Tests (2 × 3)",
    ]
    assert view.layout_id == layout  # still the plan shown
    view.layout_combo.setCurrentIndex(0)
    assert (view.grid.rowCount(), view.grid.columnCount()) == (3, 4)


def test_shrinking_the_room_asks_before_unseating_students(window: MainWindow, roster: RosterService, monkeypatch):
    from dataclasses import replace

    from PySide6.QtWidgets import QMessageBox

    from app.services.seating import SeatingError
    from app.ui.views import seating_view

    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Bob"], 1, 2)
    view.refresh()
    asked, answers = [], [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(QMessageBox, "question", lambda *a: asked.append(a[2]) or answers.pop(0))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    results = []

    class FakeDialog:
        def __init__(self, save, class_id, layout=None, parent=None, default_name=""):
            try:
                self.saved = save(replace(layout, rows=1))
                results.append("saved")
            except SeatingError:
                results.append("kept")

        def exec(self):
            return results[-1] == "saved"

    monkeypatch.setattr(seating_view, "LayoutDialog", FakeDialog)
    view.edit_button.click()
    assert results == ["kept"] and "no seat for Bob Smith" in asked[0]
    assert view.grid.rowCount() == 2
    view.edit_button.click()
    assert results == ["kept", "saved"]
    assert view.grid.rowCount() == 1
    assert "Bob Smith" in _unseated(window)


def test_a_plan_is_deleted_after_asking(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    class_id, layout, _ids = _seated_class(window, roster)
    view = window.seating_view
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(QMessageBox, "question", lambda *a: answers.pop(0))
    view.delete_button.click()
    assert view.layout_id == layout
    view.delete_button.click()
    assert view.seating.list_layouts(class_id) == []
    assert "No seating plan yet" in view.empty_label.text()
    assert not view.edit_button.isEnabled() and not view.delete_button.isEnabled()


def _click_seat(window: MainWindow, row: int, col: int) -> None:
    """Click seat (row, col) of the room, row 0 being the front."""
    view = window.seating_view
    view.grid.cellClicked.emit(*view.cell_of(row, col))


def test_a_student_is_seated_by_clicking_them_then_a_seat(window: MainWindow, roster: RosterService):
    _class_id, _layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.unseated.itemClicked.emit(view.unseated.item(0))  # Ada
    assert view.picked == ids["Ada"]
    assert view.hint.text() == "Now click a seat for Ada Lovelace · Esc cancels"
    _click_seat(window, 0, 1)
    assert _grid(window)[1] == ["", "Ada Lovelace", ""]
    assert _unseated(window) == ["Bob Smith", "Cy Young"]
    assert view.picked is None


def test_a_seated_student_is_moved_or_swapped(window: MainWindow, roster: RosterService):
    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Ada"], 0, 0)
    view.seating.place(layout, ids["Bob"], 1, 0)
    view.refresh()
    _click_seat(window, 0, 0)  # pick up Ada
    assert view.hint.text().startswith("Now click where Ada Lovelace should sit")
    _click_seat(window, 0, 2)
    assert _grid(window) == [["Bob Smith", "", ""], ["", "", "Ada Lovelace"]]
    _click_seat(window, 1, 0)  # Bob onto Ada: they swap
    _click_seat(window, 0, 2)
    assert _grid(window) == [["Ada Lovelace", "", ""], ["", "", "Bob Smith"]]


def test_clicking_an_empty_seat_with_nobody_picked_does_nothing(window: MainWindow, roster: RosterService):
    _class_id, _layout, _ids = _seated_class(window, roster)
    _click_seat(window, 0, 0)
    assert window.seating_view.picked is None
    assert _grid(window) == [["", "", ""], ["", "", ""]]


def test_escape_puts_the_picked_student_down(window: MainWindow, roster: RosterService):
    from app.ui.views.seating_view import HINT

    _class_id, _layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.pick(ids["Bob"])
    view.pick(None)
    assert view.picked is None and view.hint.text() == HINT


def test_leaving_the_page_puts_the_picked_student_down(window: MainWindow, roster: RosterService):
    from app.ui.views.seating_view import HINT

    _class_id, _layout, ids = _seated_class(window, roster)
    view = window.seating_view
    window.show_page("Seating")
    view.pick(ids["Bob"])
    window.show_page("Dashboard")
    window.show_page("Seating")
    assert view.picked is None
    assert view.hint.text() == HINT  # not still asking for a seat for Bob


def test_seat_the_rest_shuffle_clear_and_undo(window: MainWindow, roster: RosterService):
    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Bob"], 1, 2)
    view.refresh()
    view.fill_button.click()
    assert _grid(window) == [["", "", "Bob Smith"], ["Ada Lovelace", "Cy Young", ""]]
    assert not view.fill_button.isEnabled()  # everyone is seated

    view.shuffle_button.click()
    assert _unseated(window) == []
    assert all(name for name in _grid(window)[1])  # the front row is full

    view.clear_button.click()
    assert _grid(window) == [["", "", ""], ["", "", ""]] and len(_unseated(window)) == 3
    assert not view.clear_button.isEnabled()

    view.undo()  # the shuffle is back
    assert _unseated(window) == []
    view.undo()
    view.undo()
    assert _grid(window) == [["", "", "Bob Smith"], ["", "", ""]]
    view.undo()  # nothing more to undo
    view.redo()
    assert _grid(window) == [["", "", "Bob Smith"], ["Ada Lovelace", "Cy Young", ""]]


def test_moves_can_be_undone(window: MainWindow, roster: RosterService):
    _class_id, _layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.pick(ids["Ada"])
    _click_seat(window, 0, 0)
    view.undo()
    assert _unseated(window) == ["Ada Lovelace", "Bob Smith", "Cy Young"]
    view.redo()
    assert _grid(window)[1][0] == "Ada Lovelace"


def test_seat_the_rest_says_who_did_not_fit(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _seated_class(window, roster, rows=1, cols=2)
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[2]))
    window.seating_view.fill_button.click()
    assert infos == ["There's no free seat for Cy Young. Add seats with Edit…"]


def test_a_student_is_taken_out_of_their_seat(window: MainWindow, roster: RosterService):
    from PySide6.QtGui import QKeySequence, QShortcut

    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Ada"], 0, 0)
    view.seating.place(layout, ids["Bob"], 0, 1)
    view.refresh()
    view.grid.setCurrentCell(*view.cell_of(0, 0))
    delete = [x for x in view.grid.findChildren(QShortcut) if x.key() == QKeySequence("Delete")]
    delete[0].activated.emit()  # offscreen, key presses don't reach shortcuts
    assert _grid(window)[1] == ["", "Bob Smith", ""]
    assert "Ada Lovelace" in _unseated(window)
    view.undo()
    assert _grid(window)[1] == ["Ada Lovelace", "Bob Smith", ""]

    menu = view.seat_menu(0, 1)
    assert [a.text() for a in menu.actions()] == ["&Move Bob Smith…", "&Take out of the seat\tDelete"]
    menu.actions()[0].trigger()
    assert view.picked == ids["Bob"]
    view.seat_menu(0, 0).actions()[1].trigger()
    assert _grid(window)[1] == ["", "Bob Smith", ""]


def test_a_plan_is_saved_as_pdf(window: MainWindow, roster: RosterService, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Ada"], 0, 0)
    view.refresh()
    target = tmp_path / "plan.pdf"
    asked, infos = [], []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: asked.append(a[2]) or (str(target), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[2]))
    view.pdf_button.click()
    assert asked[0].endswith("7B (2026-2027) Tests seating.pdf")
    assert target.read_bytes().startswith(b"%PDF")
    assert infos[0].startswith("Saved the seating plan to")


def test_each_class_keeps_the_plan_shown_in_it(window: MainWindow, roster: RosterService):
    class_id, tests, _ids = _seated_class(window, roster)
    view = window.seating_view
    groups = view.seating.save_layout(SeatLayout(class_id, "Group work", 3, 4)).id
    view.show_layout(tests)
    assert view.layout_id == tests
    other = roster.save_class(SchoolClass(name="7C", term="2026-2027")).id
    window.select_class(other)
    assert view.layout_id is None
    view.show_layout(groups)  # not a plan of 7C
    assert view.layout_id is None
    window.select_class(class_id)
    assert view.layout_id == tests


def test_the_plan_shown_is_remembered(qapp, conn, roster: RosterService, tmp_path):
    from PySide6.QtCore import QSettings

    from app.config import AppConfig
    from app.repositories.dashboard_repo import DashboardRepository
    from app.repositories.student_repo import StudentRepository
    from app.repositories.subject_repo import SubjectRepository
    from app.services.dashboard import DashboardService
    from tests.test_ui_smoke import _attendance, _grades

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    first = MainWindow(roster, dashboard, _attendance(conn), _grades(conn), AppConfig(data_dir=tmp_path), settings)
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    first.select_class(class_id)
    seating = first.seating_view.seating
    seating.save_layout(SeatLayout(class_id, "A plan", 2, 2))
    tests = seating.save_layout(SeatLayout(class_id, "Tests", 2, 2)).id
    first.seating_view.show_layout(tests)
    first.close()
    second = MainWindow(roster, dashboard, _attendance(conn), _grades(conn), AppConfig(data_dir=tmp_path), settings)
    assert second.seating_view.layout_id == tests
    second.close()


def test_a_plan_is_copied_under_a_new_name(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Ada"], 0, 0)
    view.refresh()
    asked = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: asked.append(k["text"]) or ("Exams", True))
    view.copy_button.click()
    assert asked == ["Tests (copy)"]
    assert view.layout_combo.currentText() == "Exams (2 × 3)"
    assert _grid(window)[1][0] == "Ada Lovelace"


def test_a_desk_is_taken_away_and_put_back(window: MainWindow, roster: RosterService):
    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    menu = view.seat_menu(0, 1)
    assert [a.text() for a in menu.actions()] == ["&No desk here, e.g. an aisle"]
    menu.actions()[0].trigger()
    item = view.grid.item(*view.cell_of(0, 1))
    assert item.toolTip().startswith("No desk here")
    assert view.summary.text().endswith("5 free seats")
    view.pick(ids["Ada"])
    _click_seat(window, 0, 1)  # no desk to sit at
    assert view.picked == ids["Ada"]
    view.fill_button.click()
    assert _grid(window)[1] == ["Ada Lovelace", "", "Bob Smith"]
    view.seat_menu(0, 1).actions()[0].trigger()  # put the desk back
    assert view.plan.gaps == set()
    assert view.grid.item(*view.cell_of(0, 1)).toolTip() == ""


def test_find_selects_a_students_seat_or_them_under_not_seated(window: MainWindow, roster: RosterService):
    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Bob"], 1, 2)
    view.refresh()
    view.search.setText("smi")
    assert view.seat_at(view.grid.currentRow(), view.grid.currentColumn()) == (1, 2)
    assert view.grid.currentItem().isSelected()
    view.search.setText("young")
    assert view.unseated.currentItem().text() == "Cy Young"
    assert not view.grid.selectedItems()
    view.search.setText("nobody")
    assert view.unseated.currentItem().text() == "Cy Young"  # nothing found: stays


def test_undo_after_a_student_was_deleted_seats_the_others(window: MainWindow, roster: RosterService):
    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    window.show_page("Seating")
    view.pick(ids["Ada"])
    _click_seat(window, 0, 0)
    view.pick(ids["Bob"])
    _click_seat(window, 0, 1)
    view.unseat_at(0, 0)
    roster.delete_student(ids["Ada"])  # added by mistake, nothing recorded now
    window.show_page("Classes")
    window.show_page("Seating")
    view.undo()  # Ada's seat was put back before, which failed: she no longer exists
    assert _grid(window)[1] == ["", "Bob Smith", ""]


def test_taking_a_desk_away_can_be_undone(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _class_id, layout, ids = _seated_class(window, roster)
    view = window.seating_view
    view.seating.place(layout, ids["Ada"], 0, 0)
    view.refresh()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    view.set_desk(0, 1, False)
    view.set_desk(0, 0, False)  # Ada sits there: refused, so nothing to undo
    assert warnings == ["Ada Lovelace sits there. Take them out of the seat first."]
    assert view.plan.gaps == {(0, 1)}
    view.undo()
    assert view.plan.gaps == set() and view.plan.seats == {(0, 0): ids["Ada"]}
    view.redo()
    assert view.plan.gaps == {(0, 1)} and view.plan.seats == {(0, 0): ids["Ada"]}
