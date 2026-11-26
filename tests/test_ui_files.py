"""Saving files from any page: file names and PDFs."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextDocument  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.ui.files import write_pdf  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_write_pdf_replaces_an_older_pdf(qapp, tmp_path: Path):
    path = tmp_path / "plan.pdf"
    path.write_bytes(b"old")
    assert write_pdf(None, path, "Plan", "<p>Hello</p>", landscape=False)
    assert path.read_bytes().startswith(b"%PDF")
    assert list(tmp_path.iterdir()) == [path]  # no temp file left behind


def test_write_pdf_that_fails_says_so_even_over_an_older_pdf(qapp, tmp_path: Path, monkeypatch):
    path = tmp_path / "plan.pdf"
    path.write_bytes(b"last week's plan")
    warnings = []
    monkeypatch.setattr(QTextDocument, "print_", lambda self, writer: None)  # nothing gets printed
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    assert not write_pdf(None, path, "Plan", "<p>Hello</p>", landscape=True)
    assert warnings and str(path) in warnings[0]
    assert path.read_bytes() == b"last week's plan"  # untouched
    assert list(tmp_path.iterdir()) == [path]
