"""Asking where to save a file, shared by every export on every page."""

import re
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget

_UNSAFE = re.compile(r'[\\/:*?"<>|]+')  # not allowed in Windows file names


def safe_filename(text: str) -> str:
    """`text` usable as a file name on every system: "7B (2026/27)" -> "7B (2026-27)"."""
    return _UNSAFE.sub("-", text).strip()


def ask_save_path(
    parent: QWidget, title: str, name: str, file_type: str, suffix: str, folder: Path | None = None
) -> Path | None:
    """Ask where to save a file, suggesting `name` + `suffix` in `folder` (default: home).

    `file_type` names the files for the dialog's filter, e.g. "CSV files". The suffix is
    added if the teacher leaves it off. None if the dialog was cancelled.
    """
    start = (folder or Path.home()) / f"{safe_filename(name)}{suffix}"
    path, _filter = QFileDialog.getSaveFileName(parent, title, str(start), f"{file_type} (*{suffix})")
    if not path:
        return None
    return Path(path) if path.lower().endswith(suffix.lower()) else Path(path + suffix)
