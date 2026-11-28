"""Asking where to save a file and writing PDFs, shared by every export on every page."""

import os
import re
from pathlib import Path

from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')  # not allowed in Windows file names
# Device names Windows won't use as a file name, whatever the extension ("aux.csv" too).
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{n}" for d in ("COM", "LPT") for n in range(1, 10)}
_last_folder: Path | None = None  # where the last export went, this session


def safe_filename(text: str) -> str:
    """`text` usable as a file name on every system: "7B (2026/27)" -> "7B (2026-27)".

    Trailing dots and spaces go too, since Windows drops them silently; a name with
    nothing left becomes "Untitled", and a device name such as "Aux" gets a "_".
    """
    name = _UNSAFE.sub("-", text).strip().rstrip(". ")
    if not name:
        return "Untitled"
    if name.split(".")[0].upper() in _RESERVED:
        name += "_"
    return name


def ask_save_path(
    parent: QWidget,
    title: str,
    name: str,
    file_type: str,
    suffix: str,
    folder: Path | None = None,
    others: tuple[tuple[str, str], ...] = (),
) -> Path | None:
    """Ask where to save a file, suggesting `name` + `suffix` in `folder`, or else in the
    folder of the last export this session, or else the home folder.

    `file_type` names the files for the dialog's filter, e.g. "CSV files"; `others` are
    more (file type, suffix) pairs to choose from, e.g. ("Excel workbooks", ".xlsx").
    A path ending in none of the suffixes gets the one of the filter chosen. None if
    the dialog was cancelled.
    """
    global _last_folder
    if folder is None:
        folder = _last_folder if _last_folder is not None and _last_folder.is_dir() else Path.home()
    start = folder / f"{safe_filename(name)}{suffix}"
    types = ((file_type, suffix), *others)
    filters = [f"{kind} (*{ext})" for kind, ext in types]
    path, chosen_filter = QFileDialog.getSaveFileName(parent, title, str(start), ";;".join(filters))
    if not path:
        return None
    if any(path.lower().endswith(ext.lower()) for _kind, ext in types):
        chosen = Path(path)
    else:
        ext = next((ext for (_kind, ext), f in zip(types, filters) if f == chosen_filter), suffix)
        chosen = Path(path + ext)
    _last_folder = chosen.parent
    return chosen


def write_pdf(parent: QWidget, path, title: str, page_html: str, landscape: bool) -> bool:
    """Print `page_html` to an A4 PDF at `path`; says so and returns False if it failed.

    The PDF is written next to `path` first and then renamed, so a failed save can't
    pass for a good one when an older PDF of the same name is already there, and never
    leaves half a file in its place.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    writer = QPdfWriter(str(tmp))
    writer.setTitle(title)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    orientation = QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait
    writer.setPageOrientation(orientation)
    document = QTextDocument()
    document.setHtml(page_html)
    document.print_(writer)
    del writer  # finishes the file
    try:
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise OSError("nothing could be written there")
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        QMessageBox.warning(
            parent,
            "Save PDF",
            f"The PDF could not be saved to\n{path}\n\n{exc}\n\n"
            "If a PDF of that name is open in another program, close it and try again.",
        )
        return False
    return True
