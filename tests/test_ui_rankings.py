"""The Rankings page, built in the real window offscreen."""

from app.models import Assignment, Category, SchoolClass, Student, Subject
from app.services.roster import RosterService
from app.ui.main_window import MainWindow
from tests.test_ui_smoke import qapp, window  # noqa: F401  (fixtures)


def _ranked_class(window: MainWindow, roster: RosterService) -> tuple[int, int, dict[str, int]]:
    """7B with Ada, Bob, Cy and Dee, and Maths with Test 1 (/ 10).
    Returns (class id, test id, {first name: student id})."""
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    ids = {
        first: roster.save_student(Student(class_id, first, last)).id
        for first, last in (("Ada", "Lovelace"), ("Bob", "Smith"), ("Cy", "Young"), ("Dee", "Ward"))
    }
    maths = roster.save_subject(Subject(class_id=class_id, name="Maths")).id
    grades = window.gradebook_view.grades
    tests = grades.save_category(Category(maths, "Tests", 100)).id
    test = grades.save_assignment(Assignment(maths, tests, "Test 1", 10)).id
    window.select_class(class_id)
    return class_id, test, ids


def _rows(window: MainWindow) -> list[list[str]]:
    table = window.rankings_view.table
    return [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]


def test_rankings_ask_for_a_class_a_subject_then_scores(window: MainWindow, roster: RosterService):
    view = window.rankings_view
    window.show_page("Rankings")
    assert window.stack.currentWidget() is view
    assert "No class selected" in view.empty_label.text()
    assert view.empty_button.isHidden()

    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    window.select_class(class_id)
    assert "No subject yet" in view.empty_label.text()
    view.empty_button.click()
    assert window.classes_view.tabs.currentWidget() is window.classes_view.subject_box

    maths = roster.save_subject(Subject(class_id=class_id, name="Maths")).id
    window.select_subject(maths)
    window.show_page("Rankings")
    assert "Nothing scored in Maths yet" in view.empty_label.text()
    view.empty_button.click()
    assert window.stack.currentWidget() is window.gradebook_view


def test_rankings_list_students_best_first_then_those_unscored(window: MainWindow, roster: RosterService):
    _class_id, test, ids = _ranked_class(window, roster)
    window.gradebook_view.grades.enter_scores(
        [(test, ids["Ada"], "7"), (test, ids["Bob"], "9"), (test, ids["Cy"], "5.5")]
    )
    view = window.rankings_view
    view.refresh()
    assert view.pages.currentWidget() is view.ranking_page
    assert view.subtitle.text() == "Maths · 7B (2026-2027)"
    assert _rows(window) == [
        ["1", "Bob Smith", "90.0%", "A"],
        ["2", "Ada Lovelace", "70.0%", "C"],
        ["3", "Cy Young", "55.0%", "F"],
        ["—", "Dee Ward", "—", ""],
    ]
    assert view.summary.text() == "3 students ranked · 1 with nothing scored yet, listed last"
    assert view.table.item(3, 1).toolTip() == "Nothing scored yet"


def test_rankings_follow_scores_entered_in_the_gradebook(window: MainWindow, roster: RosterService):
    _class_id, test, ids = _ranked_class(window, roster)
    window.show_page("Gradebook")
    window.gradebook_view.grades.enter_scores([(test, ids["Ada"], "7"), (test, ids["Bob"], "9")])
    window.show_page("Rankings")
    assert [row[1] for row in _rows(window)][:2] == ["Bob Smith", "Ada Lovelace"]
    window.show_page("Gradebook")
    window.gradebook_view.grades.enter_score(test, ids["Ada"], "10")
    window.show_page("Rankings")
    assert [row[1] for row in _rows(window)][:2] == ["Ada Lovelace", "Bob Smith"]


def test_rank_by_all_subjects_or_one(window: MainWindow, roster: RosterService):
    class_id, test, ids = _ranked_class(window, roster)
    grades = window.gradebook_view.grades
    art = roster.save_subject(Subject(class_id=class_id, name="Art")).id
    drawing = grades.save_assignment(Assignment(art, grades.save_category(Category(art, "Work", 1)).id, "Drawing", 10)).id
    grades.enter_scores([(test, ids["Ada"], "6"), (test, ids["Bob"], "9"), (drawing, ids["Ada"], "10")])
    window.select_class(class_id)
    window.show_page("Rankings")
    view = window.rankings_view
    assert [view.scope.itemText(i) for i in range(view.scope.count())] == ["All subjects", "Art", "Maths"]
    assert view.scope.currentText() == "Maths"  # the current subject
    assert [row[1] for row in _rows(window)] == ["Bob Smith", "Ada Lovelace", "Dee Ward", "Cy Young"]

    view.scope.setCurrentIndex(view.scope.findText("All subjects"))
    assert view.overall
    assert view.subtitle.text() == "All subjects · 7B (2026-2027)"
    assert _rows(window)[:2] == [["1", "Bob Smith", "90.0%", "A"], ["2", "Ada Lovelace", "80.0%", "B"]]
    assert "all 2 subjects" in view.table.item(1, 2).toolTip()
    assert "1 of the 2 subjects" in view.table.item(0, 2).toolTip()

    view.scope.setCurrentIndex(view.scope.findText("Art"))
    assert not view.overall
    assert window.subject_id == art  # Art is now the current subject everywhere
    assert "Art" in window.windowTitle()
    assert view.scope.currentText() == "Art"
    assert [row[1] for row in _rows(window)] == ["Ada Lovelace", "Bob Smith", "Dee Ward", "Cy Young"]


def test_rank_by_all_subjects_is_kept_when_the_subject_changes(window: MainWindow, roster: RosterService):
    class_id, test, ids = _ranked_class(window, roster)
    window.gradebook_view.grades.enter_score(test, ids["Ada"], "6")
    view = window.rankings_view
    view.set_overall(True)
    roster.save_subject(Subject(class_id=class_id, name="Art"))
    window.select_class(class_id)
    assert view.overall and view.scope.currentText() == "All subjects"


def test_rank_by_is_off_without_subjects(window: MainWindow, roster: RosterService):
    window.select_class(roster.save_class(SchoolClass(name="7B", term="2026-2027")).id)
    view = window.rankings_view
    view.set_overall(True)
    assert not view.scope.isEnabled() and view.scope.count() == 0
    assert "No subject yet" in view.empty_label.text()


def test_rank_by_all_subjects_is_remembered(qapp, conn, roster: RosterService, tmp_path):
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
    first.rankings_view.set_overall(True)
    first.close()
    second = MainWindow(roster, dashboard, _attendance(conn), _grades(conn), AppConfig(data_dir=tmp_path), settings)
    assert second.rankings_view.overall
    second.close()


def test_rankings_number_shared_places_as_settings_say(window: MainWindow, roster: RosterService):
    _class_id, test, ids = _ranked_class(window, roster)
    window.gradebook_view.grades.enter_scores(
        [(test, ids["Ada"], "9"), (test, ids["Bob"], "9"), (test, ids["Cy"], "5")]
    )
    window.show_page("Rankings")
    assert [row[0] for row in _rows(window)][:3] == ["1=", "1=", "3"]
    window.settings_view.ranking_buttons["dense"].click()
    assert [row[0] for row in _rows(window)][:3] == ["1=", "1=", "2"]
    assert window.rankings_view.table.item(0, 0).toolTip() == "Shared with Bob Smith"


def test_rankings_start_with_the_saved_method(qapp, conn, roster: RosterService, tmp_path):
    from app.config import AppConfig
    from app.repositories.dashboard_repo import DashboardRepository
    from app.repositories.student_repo import StudentRepository
    from app.repositories.subject_repo import SubjectRepository
    from app.services.dashboard import DashboardService
    from tests.test_ui_smoke import _attendance, _grades

    dashboard = DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    config = AppConfig(data_dir=tmp_path, ranking_method="dense")
    window = MainWindow(roster, dashboard, _attendance(conn), _grades(conn), config)
    assert window.rankings_view.rankings.method == "dense"
    window.close()


def test_rankings_point_out_averages_under_the_pass_mark(window: MainWindow, roster: RosterService):
    from app.ui import style

    _class_id, test, ids = _ranked_class(window, roster)
    window.gradebook_view.grades.enter_scores([(test, ids["Ada"], "9"), (test, ids["Bob"], "5.5")])
    window.show_page("Rankings")
    view = window.rankings_view
    danger = style.color(view, "danger")
    assert view.table.item(1, 2).foreground().color() == danger
    assert view.table.item(1, 2).toolTip() == "Under the pass mark of 60%"
    assert view.table.item(0, 2).foreground().color() != danger
    assert view.table.item(0, 2).toolTip() == ""

    window.settings_view.pass_mark.setValue(50)
    assert view.table.item(1, 2).foreground().color() != danger


def test_export_saves_the_ranking_as_csv(window: MainWindow, roster: RosterService, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    _class_id, test, ids = _ranked_class(window, roster)
    view = window.rankings_view
    window.show_page("Rankings")
    assert not view.export_button.isEnabled()  # nothing scored yet
    window.gradebook_view.grades.enter_scores([(test, ids["Ada"], "7"), (test, ids["Bob"], "9")])
    view.refresh()
    asked, infos = [], []
    target = tmp_path / "ranking.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: asked.append(a[2]) or (str(target), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[2]))
    assert view.export_button.isEnabled()
    view.export_button.click()
    assert asked[0].endswith("Maths 7B (2026-2027) ranking.csv")
    assert target.read_text(encoding="utf-8-sig").splitlines()[1:3] == [
        "1,,Smith,Bob,90.0,A",
        "2,,Lovelace,Ada,70.0,C",
    ]
    assert infos[0].startswith("Saved the ranking of 2 students")
