"""Write app data to files the teacher can open elsewhere, e.g. in a spreadsheet."""

import csv
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from app.models import Student
from app.services.attendance import MonthRegister

ROSTER_COLUMNS = ("Student #", "Last name", "First name", "Status", "Notes")


def _write_csv(path: Path, rows: Sequence[Sequence[object]]) -> None:
    """UTF-8 with a byte-order mark so Excel shows accented names correctly. The file
    is written next to `path` first and renamed, so a failed export never leaves
    half a file behind.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".export-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_roster_csv(path: Path, students: Sequence[Student]) -> None:
    """Save students as CSV, in the order given."""
    rows: list[Sequence[object]] = [ROSTER_COLUMNS]
    for s in students:
        rows.append((s.student_no or "", s.last_name, s.first_name, "Active" if s.active else "Inactive", s.notes))
    _write_csv(path, rows)


def write_attendance_csv(path: Path, register: MonthRegister) -> None:
    """Save a month of attendance: one column per day with P, L, A or E (blank = not
    marked), then each student's totals and attendance rate."""
    header = ["Student #", "Last name", "First name"]
    header += [day.isoformat() for day in register.days]
    header += ["Absent", "Late", "Excused", "Attendance %"]
    rows: list[Sequence[object]] = [header]
    for row in register.rows:
        s, counts, rate = row.student, row.counts(), row.rate
        line: list[object] = [s.student_no or "", s.last_name, s.first_name]
        line += [row.statuses[day].value[0].upper() if day in row.statuses else "" for day in register.days]
        line += [counts["absent"], counts["late"], counts["excused"], "" if rate is None else round(rate)]
        rows.append(line)
    _write_csv(path, rows)
