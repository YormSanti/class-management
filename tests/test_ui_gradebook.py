"""The Gradebook page, built in the real window offscreen."""

from PySide6.QtWidgets import QApplication

from app.models import SchoolClass, Subject
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
    assert view.pages.currentWidget() is view.sheet_page
    assert view.subtitle.text() == "Maths · 7B (2026-2027)"
