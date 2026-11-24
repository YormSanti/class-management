"""The Gradebook page, built in the real window offscreen."""

from PySide6.QtWidgets import QApplication

from app.models import Assignment, Category, SchoolClass, Student, Subject
from app.services.roster import RosterService
from app.ui.main_window import MainWindow
from tests.test_ui_smoke import qapp, window  # noqa: F401  (fixtures)


def test_gradebook_asks_for_a_class_then_a_subject(window: MainWindow, roster: RosterService):
    view = window.gradebook_view
    window.show_page("Gradebook")
    assert view.pages.currentIndex() == 0
    assert "No class selected" in view.empty_label.text()
    assert view.empty_button.isHidden()

    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    window.select_class(class_id)
    assert "No subject yet" in view.empty_label.text()
    view.empty_button.click()
    assert window.stack.currentWidget() is window.classes_view
    assert window.classes_view.tabs.currentWidget() is window.classes_view.subject_box

    maths = roster.save_subject(Subject(class_id=class_id, name="Maths")).id
    window.select_subject(maths)
    assert view.subtitle.text() == "Maths · 7B (2026-2027)"
    assert "How is Maths graded?" in view.empty_label.text()
    assert "Tests 50, Quizzes 20, Homework 20, Participation 10" in view.empty_label.text()
    assert not view.own_categories_button.isHidden()
    view.empty_button.click()
    assert view.pages.currentWidget() is view.sheet_page
    assert len(view.sheet.categories) == 4


def _graded_class(window: MainWindow, roster: RosterService) -> tuple[int, int, int, int]:
    """7B with Ada and Bob, Maths with Test 1 (/ 10) and Homework (/ 5). Returns (subject, ada, test, homework)."""
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace")).id
    roster.save_student(Student(class_id, "Bob", "Smith"))
    maths = roster.save_subject(Subject(class_id=class_id, name="Maths")).id
    grades = window.gradebook_view.grades
    tests = grades.save_category(Category(maths, "Tests", 100)).id
    test = grades.save_assignment(Assignment(maths, tests, "Test 1", 10)).id
    homework = grades.save_assignment(Assignment(maths, tests, "Homework", 5)).id
    window.select_class(class_id)
    return maths, ada, test, homework


def test_gradebook_shows_scores_and_averages(window: MainWindow, roster: RosterService):
    maths, ada, test, homework = _graded_class(window, roster)
    grades = window.gradebook_view.grades
    grades.enter_score(test, ada, "8")
    grades.enter_score(homework, ada, "ex")
    view = window.gradebook_view
    view.refresh()
    table = view.table
    assert table.columnCount() == 4
    assert table.horizontalHeaderItem(1).text() == "Test 1\n/ 10"
    assert [table.item(r, 0).text() for r in range(2)] == ["Ada Lovelace", "Bob Smith"]
    assert [table.item(0, c).text() for c in range(1, 4)] == ["8", "ex", "80%"]
    assert [table.item(1, c).text() for c in range(1, 4)] == ["", "", "—"]
    assert view.summary.text() == "2 assignments · class average 80%"


def test_typing_a_score_saves_it_and_updates_the_average(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("7,5")
    assert view.grades.sheet(maths).score(test, ada) == 7.5
    assert view.table.item(0, 1).text() == "7.5"
    assert view.table.item(0, 3).text() == "75%"
    view.table.item(0, 2).setText("EX")
    assert view.table.item(0, 2).text() == "ex"

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    view.table.item(0, 1).setText("seven")
    assert "isn't a score" in warnings[0]
    assert view.table.item(0, 1).text() == "7.5"  # the saved score is back
    view.table.item(0, 1).setText("")
    assert not view.grades.sheet(maths).is_entered(test, ada)
    assert view.table.item(0, 3).text() == "—"


def test_category_dialog_saves_a_new_category(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.ui.dialogs.category_dialog import CategoryDialog

    maths, *_ = _graded_class(window, roster)
    grades = window.gradebook_view.grades
    dialog = CategoryDialog(grades.save_category, maths)
    dialog.name.setText(" Homework ")
    dialog.weight.setValue(20)
    dialog.accept()
    assert dialog.saved.name == "Homework" and dialog.saved.weight == 20

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    again = CategoryDialog(grades.save_category, maths)
    again.name.setText("tests")
    again.accept()
    assert "already has a category called Tests" in warnings[0]
    assert again.saved is None


def test_categories_dialog_adds_edits_and_deletes(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from app.ui.dialogs import categories_dialog
    from app.ui.dialogs.categories_dialog import CategoriesDialog

    maths, *_ = _graded_class(window, roster)
    grades = window.gradebook_view.grades
    dialog = CategoriesDialog(grades, maths)
    assert dialog.windowTitle() == "Categories of Maths"
    assert [dialog.table.item(0, c).text() for c in range(4)] == ["Tests", "100", "100%", "2"]
    assert not dialog.delete_button.isEnabled()

    class FakeDialog:  # stands in for CategoryDialog: saves straight away
        def __init__(self, save, subject_id, category=None, parent=None):
            from app.models import Category

            self.saved = save(Category(subject_id, "Homework", 25) if category is None else category)

        def exec(self):
            return True

    monkeypatch.setattr(categories_dialog, "CategoryDialog", FakeDialog)
    dialog.add_category()
    assert dialog.changed
    assert [dialog.table.item(1, c).text() for c in range(4)] == ["Homework", "25", "20%", "0"]
    assert dialog.selected_id() == dialog.table.item(1, 0).data(categories_dialog.CATEGORY_ID)

    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[2]))
    dialog.table.selectRow(0)
    dialog.delete_category()
    assert "Tests can't be deleted: it has 2 assignments" in infos[0]
    dialog.table.selectRow(1)
    dialog.delete_category()
    assert dialog.table.rowCount() == 1


def test_assignment_dialog_saves_a_new_assignment(window: MainWindow, roster: RosterService):
    from datetime import date

    from app.ui.dialogs.assignment_dialog import AssignmentDialog

    maths, *_ = _graded_class(window, roster)
    grades = window.gradebook_view.grades
    categories = grades.list_categories(maths)
    dialog = AssignmentDialog(grades.save_assignment, maths, categories, default_max=20, today=date(2026, 11, 24))
    dialog.title.setText("Quiz 3")
    assert dialog.max_score.value() == 20
    dialog.max_score.setValue(15)
    dialog.accept()
    assert dialog.saved.title == "Quiz 3"
    assert dialog.saved.max_score == 15
    assert dialog.saved.date == date(2026, 11, 24)
    assert dialog.saved.category_id == categories[0].id

    edit = AssignmentDialog(grades.save_assignment, maths, categories, dialog.saved)
    assert edit.title.text() == "Quiz 3"
    edit.dated.setChecked(False)
    edit.accept()
    assert grades.get_assignment(dialog.saved.id).date is None
