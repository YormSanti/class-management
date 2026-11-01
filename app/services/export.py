"""Write app data to files the teacher can open elsewhere, e.g. in a spreadsheet."""

import csv
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from app.models import Student

ROSTER_COLUMNS = ("Student #", "Last name", "First name", "Status", "Notes")


def write_roster_csv(path: Path, students: Sequence[Student]) -> None:
    """Save students as CSV, in the order given.

    UTF-8 with a byte-order mark so Excel shows accented names correctly. The file
    is written next to `path` first and renamed, so a failed export never leaves
    half a file behind.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".export-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(ROSTER_COLUMNS)
            for s in students:
                writer.writerow(
                    (s.student_no or "", s.last_name, s.first_name, "Active" if s.active else "Inactive", s.notes)
                )
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
