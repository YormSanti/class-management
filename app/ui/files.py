"""Asking where to save a file, shared by every export on every page."""

import re
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget

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
