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
