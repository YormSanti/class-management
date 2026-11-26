"""The Settings page on its own, without the main window."""

import os
import sqlite3
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from app.config import AppConfig  # noqa: E402
from app.ui.views.settings_view import SettingsView  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_move_data_wont_switch_to_a_file_the_app_cant_open(
    qapp, conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    other = tmp_path / "usb"
    other.mkdir()
    (other / "classroom.db").write_bytes(b"half a file " * 1000)  # e.g. copied while being written
    saved, warnings = [], []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(other))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: pytest.fail("shouldn't offer to switch"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    view = SettingsView(AppConfig(data_dir=tmp_path), save=saved.append)
    try:
        view.move_data()
        assert "is damaged" in warnings[0] and "Your data stays where it is" in warnings[0]
        assert saved == [] and view.config.data_dir == tmp_path
    finally:
        view.deleteLater()


def test_typed_pass_mark_is_saved_once_on_enter(qapp, tmp_path: Path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    saved = []
    view = SettingsView(AppConfig(data_dir=tmp_path), save=saved.append)
    try:
        view.pass_mark.lineEdit().selectAll()
        QTest.keyClicks(view.pass_mark.lineEdit(), "75")
        assert saved == []  # not 7 on the way to 75
        QTest.keyClick(view.pass_mark.lineEdit(), Qt.Key.Key_Return)
        assert [c.pass_mark for c in saved] == [75.0]
        assert view.config.pass_mark == 75.0
    finally:
        view.deleteLater()
