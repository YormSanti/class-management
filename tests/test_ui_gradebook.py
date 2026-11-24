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
    assert [table.item(0, c).text() for c in range(1, 4)] == ["8", "ex", "80% B"]
    assert [table.item(1, c).text() for c in range(1, 4)] == ["", "", "—"]
    assert view.summary.text() == "2 assignments · class average 80%"


def test_typing_a_score_saves_it_and_updates_the_average(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("7,5")
    assert view.grades.sheet(maths).score(test, ada) == 7.5
    assert view.table.item(0, 1).text() == "7.5"
    assert view.table.item(0, 3).text() == "75% C"
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


def test_new_assignment_opens_its_column(window: MainWindow, roster: RosterService, monkeypatch):
    from app.ui.views import gradebook_view

    maths, *_ = _graded_class(window, roster)
    view = window.gradebook_view
    seen = {}

    class FakeDialog:
        def __init__(self, save, subject_id, categories, parent=None, **defaults):
            seen.update(defaults)
            from app.models import Assignment

            self.saved = save(Assignment(subject_id, categories[0].id, "Quiz 3", 5))

        def exec(self):
            return True

    monkeypatch.setattr(gradebook_view, "AssignmentDialog", FakeDialog)
    assert view.new_button.isEnabled()
    view.new_button.click()
    assert seen["default_max"] == 5  # like the latest assignment, Homework / 5
    assert seen["default_title"] == ""  # "Homework" has no number to count on
    assert view.table.horizontalHeaderItem(3).text() == "Quiz 3\n/ 5"
    assert (view.table.currentRow(), view.table.currentColumn()) == (0, 3)


def test_double_clicking_a_header_edits_its_assignment(window: MainWindow, roster: RosterService, monkeypatch):
    from dataclasses import replace
    from datetime import date

    from app.ui.views import gradebook_view

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view

    class FakeDialog:
        def __init__(self, save, subject_id, categories, assignment, parent=None):
            self.saved = save(replace(assignment, title="Test 1 (fractions)", date=date(2026, 9, 1)))

        def exec(self):
            return True

    monkeypatch.setattr(gradebook_view, "AssignmentDialog", FakeDialog)
    view.table.horizontalHeader().sectionDoubleClicked.emit(2)  # Homework, now dated, moves first
    assert view.table.horizontalHeaderItem(1).text() == "Test 1 (fractions)\n/ 5"
    assert view.table.currentColumn() == 1
    view.table.horizontalHeader().sectionDoubleClicked.emit(0)  # the names: nothing to edit


def test_header_menu_deletes_an_assignment_after_asking(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("9")
    assert view.header_menu(0) is None and view.header_menu(3) is None
    menu = view.header_menu(1)
    assert [a.text() for a in menu.actions()] == ["&Edit…", "&Fill empty cells…", "&Delete…"]

    questions = []
    answer = QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", lambda *a: questions.append(a[2]) or answer)
    menu.actions()[2].trigger()
    assert questions == ["Delete Test 1 with its 1 score?\n\nThis can't be undone."]
    assert view.table.columnCount() == 4
    answer = QMessageBox.StandardButton.Yes
    menu.actions()[2].trigger()
    assert view.table.columnCount() == 3
    assert view.table.horizontalHeaderItem(1).text() == "Homework\n/ 5"


def test_header_tooltip_describes_the_assignment(window: MainWindow, roster: RosterService):
    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    assert view.table.horizontalHeaderItem(1).toolTip().splitlines()[:2] == [
        "Tests · out of 10", "0 of 2 scores entered"]  # fmt: skip
    view.table.item(0, 1).setText("7")
    assert view.table.horizontalHeaderItem(1).toolTip().splitlines()[1] == "Class average 70% · 1 of 2 scores entered"


def test_enter_saves_a_score_and_goes_to_the_next_student(window: MainWindow, roster: RosterService):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit

    maths, ada, test, homework = _graded_class(window, roster)
    window.show_page("Gradebook")
    view = window.gradebook_view
    view.table.setFocus()
    view.table.setCurrentCell(0, 1)
    QTest.keyClicks(view.table, "9")  # starts editing with the 9
    QTest.keyClick(view.table.viewport().findChild(QLineEdit), Qt.Key.Key_Return)
    QApplication.processEvents()  # the editor is closed by a queued call
    assert view.grades.sheet(maths).score(test, ada) == 9
    assert (view.table.currentRow(), view.table.currentColumn()) == (1, 1)
    QTest.keyClick(view.table, Qt.Key.Key_Up)
    QTest.keyClick(view.table, Qt.Key.Key_Return)  # not editing: just moves down
    assert view.table.currentRow() == 1


def test_delete_clears_the_selected_scores(window: MainWindow, roster: RosterService):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QTableWidgetSelectionRange

    maths, ada, test, homework = _graded_class(window, roster)
    window.show_page("Gradebook")
    view = window.gradebook_view
    view.table.item(0, 1).setText("8")
    view.table.item(0, 2).setText("4")
    view.table.item(1, 1).setText("6")
    view.table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, 3), True)  # Ada's whole row
    view.clear_selected()
    assert [view.table.item(0, c).text() for c in range(1, 4)] == ["", "", "—"]
    assert view.table.item(1, 1).text() == "6"
    assert view.table.item(0, 0).text() == "Ada Lovelace"  # names and averages aren't scores


def test_pasted_block_of_scores_is_entered(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: messages.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: messages.append(a[2]))

    view.table.setCurrentCell(0, 0)
    view.paste_scores("8")
    assert messages.pop() == "Select the score cell to paste into first."

    view.table.setCurrentCell(0, 1)
    view.paste_scores("8\tx\r\n6\t3\r\n")
    assert [view.table.item(0, c).text() for c in range(1, 4)] == ["8", "ex", "80% B"]
    assert [view.table.item(1, c).text() for c in range(1, 4)] == ["6", "3", "60% D"]
    assert messages == []

    view.paste_scores("1\n2\n3")  # one student too many
    assert view.table.item(1, 1).text() == "2"
    assert "1 value didn't fit" in messages.pop()

    view.paste_scores("5\nfive")
    assert messages.pop().startswith("Nothing was pasted.\n\nBob Smith, Test 1: 'five' isn't a score")
    assert view.table.item(0, 1).text() == "1"


def test_selected_cells_are_copied_for_a_spreadsheet(window: MainWindow, roster: RosterService):
    from PySide6.QtWidgets import QTableWidgetSelectionRange

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.setCurrentCell(0, 1)
    view.table.item(0, 1).setText("8")
    view.table.clearSelection()
    view.table.setRangeSelected(QTableWidgetSelectionRange(0, 1, 1, 1), True)
    assert view.selection_text() == "8\n\n"
    view.table.selectAll()
    assert view.selection_text() == (
        "Student\tTest 1\tHomework\tAverage\nAda Lovelace\t8\t\t80% B\nBob Smith\t\t\t—\n")


def test_score_changes_can_be_undone_and_redone(window: MainWindow, roster: RosterService):
    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("8")
    view.table.setCurrentCell(0, 1)
    view.paste_scores("5\n6")
    assert [view.table.item(r, 1).text() for r in range(2)] == ["5", "6"]
    view.undo()
    assert [view.table.item(r, 1).text() for r in range(2)] == ["8", ""]
    assert view.summary.text().startswith("Undid 2 scores")
    view.undo()
    assert view.table.item(0, 1).text() == ""
    view.undo()  # nothing more to undo
    view.redo()
    view.redo()
    assert [view.table.item(r, 1).text() for r in range(2)] == ["5", "6"]
    view.undo()
    view.table.item(1, 2).setText("4")  # a new change forgets what was undone
    view.redo()
    assert view.table.item(0, 1).text() == "8"


def test_replaced_data_forgets_the_score_undo(window: MainWindow, roster: RosterService):
    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("8")
    window._data_replaced()  # e.g. after Restore
    view.undo()
    assert view.table.item(0, 1).text() == "8"


def test_failing_average_is_shown_in_the_danger_colour(window: MainWindow, roster: RosterService):
    from app.ui import style

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("4")
    average = view.table.item(0, 3)
    assert average.text() == "40% F"
    assert average.foreground().color() == style.color(view, "danger")
    assert average.toolTip() == "Under the pass mark of 60%\nTests (weight 100): 40%"
    view.table.item(0, 1).setText("6")
    assert average.toolTip() == "Tests (weight 100): 60%"
    assert average.foreground().color() != style.color(view, "danger")


def test_pass_mark_set_in_settings_is_used_by_the_gradebook(window: MainWindow, roster: RosterService):
    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("6")
    assert view.table.item(1, 3).toolTip() == "Nothing scored yet"
    window.select_class(window.class_id)  # the dashboard shows it too
    assert not view.table.item(0, 3).toolTip().startswith("Under")
    window.settings_view.pass_mark.setValue(65)
    assert window.config.pass_mark == 65
    assert view.table.item(0, 3).toolTip().startswith("Under the pass mark of 65%")
    summary = window.dashboard_view.dashboard.summary(window.class_id)
    assert summary.subjects[0].below_pass == 1


def test_bonus_and_exempt_scores_are_explained(window: MainWindow, roster: RosterService):
    from app.ui import style

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    cell = view.table.item(0, 1)
    cell.setText("12")
    assert cell.foreground().color() == style.color(view, "info")
    assert cell.toolTip() == "2 bonus points above the maximum of 10"
    cell.setText("ex")
    assert cell.toolTip() == "Exempt: left out of the average"
    cell.setText("10")
    assert cell.toolTip() == ""


def test_empty_cells_of_an_assignment_can_be_filled(window: MainWindow, roster: RosterService, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("8")
    prompts = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: prompts.append((a[2], k["text"])) or ("0", True))
    view.ask_fill_empty(test)
    assert prompts[0][1] == "10"
    assert prompts[0][0].startswith("Score for the 1 student without one in Test 1")
    assert [view.table.item(r, 1).text() for r in range(2)] == ["8", "0"]
    assert not view.header_menu(1).actions()[1].isEnabled()  # nothing left to fill
    view.undo()
    assert view.table.item(1, 1).text() == ""


def test_assignments_can_be_filtered_by_category(window: MainWindow, roster: RosterService):
    from app.models import Assignment, Category

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    quizzes = view.grades.save_category(Category(maths, "Quizzes", 20)).id
    view.grades.save_assignment(Assignment(maths, quizzes, "Quiz 1", 5))
    view.refresh()
    combo = view.category_filter
    assert [combo.itemText(i) for i in range(combo.count())] == ["All categories", "Tests", "Quizzes"]
    combo.setCurrentIndex(2)
    assert [view.table.isColumnHidden(c) for c in range(5)] == [False, True, True, False, False]
    view.refresh()  # the choice is kept
    assert combo.currentText() == "Quizzes" and view.table.isColumnHidden(1)
    combo.setCurrentIndex(0)
    assert not any(view.table.isColumnHidden(c) for c in range(5))


def test_going_to_a_hidden_assignment_shows_every_category(window: MainWindow, roster: RosterService):
    from app.models import Category

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.grades.save_category(Category(maths, "Quizzes", 20))
    view.refresh()
    view.category_filter.setCurrentIndex(2)  # Quizzes: Test 1 is hidden
    view.go_to_assignment(test)
    assert view.category_filter.currentIndex() == 0
    assert not view.table.isColumnHidden(1) and view.table.currentColumn() == 1


def test_find_shows_only_matching_students(window: MainWindow, roster: RosterService):
    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.search.setText("smi")
    assert [view.table.isRowHidden(r) for r in range(2)] == [True, False]
    view.refresh()  # kept after reloading
    assert view.table.isRowHidden(0)
    view.search.clear()
    assert not view.table.isRowHidden(0)


def test_enter_skips_students_hidden_by_find(window: MainWindow, roster: RosterService):
    from app.models import Student

    maths, ada, test, homework = _graded_class(window, roster)
    roster.save_student(Student(roster.get_subject(maths).class_id, "Dan", "Zed"))
    view = window.gradebook_view
    view.refresh()
    view.search.setText("a")  # Ada Lovelace and Dan Zed, not Bob Smith between them
    view.table.setCurrentCell(0, 1)
    view.table._next_row()
    assert view.table.currentRow() == 2
    view.table._next_row()  # the last one: stays
    assert view.table.currentRow() == 2


def test_clicking_average_ranks_students_and_student_puts_names_back(window: MainWindow, roster: RosterService):
    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("6")  # Ada 60 %
    view.table.item(1, 1).setText("9")  # Bob 90 %
    view.table.horizontalHeader().sectionClicked.emit(3)
    assert [view.table.item(r, 0).text() for r in range(2)] == ["Bob Smith", "Ada Lovelace"]
    view.table.item(1, 1).setText("7")  # edits still reach Ada, now on the second row
    assert view.grades.sheet(maths).score(test, ada) == 7
    view.search.setText("ada")
    assert [view.table.isRowHidden(r) for r in range(2)] == [True, False]
    view.table.horizontalHeader().sectionClicked.emit(1)  # an assignment: no change
    assert view.by_average
    view.table.horizontalHeader().sectionClicked.emit(0)
    assert [view.table.item(r, 0).text() for r in range(2)] == ["Ada Lovelace", "Bob Smith"]


def test_gradebook_order_is_remembered(qapp, conn, roster: RosterService, tmp_path):
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
    first.gradebook_view.set_order(by_average=True)
    first.close()
    second = MainWindow(roster, dashboard, _attendance(conn), _grades(conn), AppConfig(data_dir=tmp_path), settings)
    assert second.gradebook_view.by_average
    second.close()


def test_export_saves_the_gradebook_as_csv(window: MainWindow, roster: RosterService, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("8")
    asked, infos = [], []
    target = tmp_path / "grades.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: asked.append(a[2]) or (str(target), ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[2]))
    assert view.export_button.isEnabled()
    view.export_button.click()
    assert asked[0].endswith("7B (2026-2027) Maths grades.csv")
    assert target.read_text(encoding="utf-8-sig").splitlines()[1] == ",Lovelace,Ada,8,,80.0,80.0,B"
    assert infos[0].startswith("Saved the grades of 2 students")


def test_lowering_a_maximum_below_scores_says_they_are_bonus(window: MainWindow, roster: RosterService, monkeypatch):
    from dataclasses import replace

    from PySide6.QtWidgets import QMessageBox

    from app.ui.views import gradebook_view

    maths, ada, test, homework = _graded_class(window, roster)
    view = window.gradebook_view
    view.table.item(0, 1).setText("9")
    view.table.item(1, 1).setText("5")

    class FakeDialog:
        def __init__(self, save, subject_id, categories, assignment, parent=None):
            self.saved = save(replace(assignment, max_score=8))

        def exec(self):
            return True

    infos = []
    monkeypatch.setattr(gradebook_view, "AssignmentDialog", FakeDialog)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: infos.append(a[2]))
    view.edit_assignment(test)
    assert infos == ["1 score is now above the maximum of 8 and counts as bonus points."]
