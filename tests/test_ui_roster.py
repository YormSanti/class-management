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
