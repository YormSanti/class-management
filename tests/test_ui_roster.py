"""The Manage classes page and its dialogs: classes, subjects and students."""

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.models import SchoolClass
from app.services.roster import RosterService
from tests.test_ui_smoke import qapp  # noqa: F401  (fixture)


def test_new_year_dialog_asks_before_using_a_mistyped_school_year(
    qapp: QApplication, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from app.ui.dialogs.new_year_dialog import NewYearDialog

    roster.save_class(SchoolClass(name="7B", term="2025-2026"))
    asked: list[str] = []
    answer = QMessageBox.StandardButton.No

    def ask(_parent, _title, text, *args):
        asked.append(text)
        return answer

    monkeypatch.setattr(QMessageBox, "question", ask)
    dialog = NewYearDialog(roster, "2025-2026")
    dialog.new_term.setText("2026-207")
    dialog.accept()
    assert "only three digits" in asked[-1]
    assert dialog.created == [] and roster.list_terms() == ["2025-2026"]

    answer = QMessageBox.StandardButton.Yes
    dialog.accept()
    assert [c.term for c in dialog.created] == ["2026-207"]


def test_new_year_dialog_does_not_ask_about_the_suggested_year(
    qapp: QApplication, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from app.ui.dialogs.new_year_dialog import NewYearDialog

    roster.save_class(SchoolClass(name="7B", term="2025-2026"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("asked"))
    dialog = NewYearDialog(roster, "2025-2026")
    dialog.accept()
    assert [c.term for c in dialog.created] == ["2026-2027"]


def test_paste_preview_points_out_a_name_too_long_to_add(qapp: QApplication, roster: RosterService):
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    dialog = PasteStudentsDialog(roster, class_id, text="Ada\tLovelace\nGrace\t" + "H" * 61 + "\n")
    assert "Line 2: A last name can be at most 60 characters" in dialog.problems.text()
    assert not dialog._ok.isEnabled()


def test_enter_in_the_student_search_goes_to_the_first_student_found(
    qapp: QApplication, roster: RosterService, monkeypatch: pytest.MonkeyPatch
):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from app.models import Student
    from app.ui.views import roster_view
    from app.ui.views.roster_view import RosterView

    edited: list[str] = []

    class FakeDialog:
        def __init__(self, save, class_id, student=None, parent=None, **kwargs):
            edited.append(student.full_name)

        def exec(self):
            return False

    monkeypatch.setattr(roster_view, "StudentDialog", FakeDialog)
    class_id = roster.save_class(SchoolClass(name="7B")).id
    for first, last in (("Ada", "Lovelace"), ("Alan", "Turing"), ("Tim", "Turner")):
        roster.save_student(Student(class_id=class_id, first_name=first, last_name=last))
    view = RosterView(roster)
    view.set_class(class_id)
    view.show()
    view.activateWindow()
    assert QTest.qWaitForWindowActive(view)
    view.search.setFocus()
    QTest.keyClicks(view.search, "tur")
    QTest.keyClick(view.search, Qt.Key.Key_Return)
    assert edited == []  # Enter in the search box doesn't edit anyone yet
    assert view._selected_student().full_name == "Alan Turing"
    assert qapp.focusWidget() is view.table
    QTest.keyClick(view.table, Qt.Key.Key_Enter)  # the number pad Enter
    assert edited == ["Alan Turing"]
    view.close()


def test_paste_summary_names_a_few_students_already_in_the_class(qapp: QApplication, roster: RosterService):
    from app.models import Student
    from app.ui.dialogs.paste_students_dialog import PasteStudentsDialog

    class_id = roster.save_class(SchoolClass(name="7B")).id
    names = [(f"Student{chr(65 + i)}", "Smith") for i in range(30)]
    for first, last in names:
        roster.save_student(Student(class_id=class_id, first_name=first, last_name=last))
    text = "".join(f"{first} {last}\n" for first, last in names) + "Ada Lovelace\n"
    dialog = PasteStudentsDialog(roster, class_id, text=text)
    summary = dialog.summary.text()
    assert summary.startswith("1 student to add. Leaving out, already in the class: StudentA Smith, ")
    assert "StudentH Smith and 22 more." in summary and "StudentI" not in summary
    assert dialog.summary.wordWrap()
