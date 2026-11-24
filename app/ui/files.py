"""Asking where to save a file and writing PDFs, shared by every export on every page."""

import re
from pathlib import Path

from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

_UNSAFE = re.compile(r'[\\/:*?"<>|]+')  # not allowed in Windows file names
_last_folder: Path | None = None  # where the last export went, this session


def safe_filename(text: str) -> str:
    """`text` usable as a file name on every system: "7B (2026/27)" -> "7B (2026-27)"."""
    return _UNSAFE.sub("-", text).strip()


def ask_save_path(
    parent: QWidget, title: str, name: str, file_type: str, suffix: str, folder: Path | None = None
) -> Path | None:
    """Ask where to save a file, suggesting `name` + `suffix` in `folder`, or else in the
    folder of the last export this session, or else the home folder.

    `file_type` names the files for the dialog's filter, e.g. "CSV files". The suffix is
    added if the teacher leaves it off. None if the dialog was cancelled.
    """
    global _last_folder
    if folder is None:
        folder = _last_folder if _last_folder is not None and _last_folder.is_dir() else Path.home()
    start = folder / f"{safe_filename(name)}{suffix}"
    path, _filter = QFileDialog.getSaveFileName(parent, title, str(start), f"{file_type} (*{suffix})")
    if not path:
        return None
    chosen = Path(path) if path.lower().endswith(suffix.lower()) else Path(path + suffix)
    _last_folder = chosen.parent
    return chosen


def write_pdf(parent: QWidget, path, title: str, page_html: str, landscape: bool) -> bool:
    """Print `page_html` to an A4 PDF at `path`; says so and returns False if it failed."""
    writer = QPdfWriter(str(path))
    writer.setTitle(title)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    orientation = QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait
    writer.setPageOrientation(orientation)
    document = QTextDocument()
    document.setHtml(page_html)
    document.print_(writer)
    del writer  # finishes the file
    if not path.exists() or path.stat().st_size == 0:
        QMessageBox.warning(parent, "Save PDF", f"The PDF could not be saved to\n{path}")
        return False
    return True
