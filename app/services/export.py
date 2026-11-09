"""Write app data to files the teacher can open elsewhere, e.g. in a spreadsheet."""

import csv
import html
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from app.models import Student
from app.services.attendance import MonthRegister, PeriodSummary

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


def write_attendance_summary_csv(path: Path, summary: PeriodSummary) -> None:
    """Save each student's totals for a period, e.g. a term, with their attendance rate."""
    rows: list[Sequence[object]] = [
        ["Student #", "Last name", "First name", "Present", "Late", "Absent", "Excused", "Not marked", "Attendance %"]
    ]
    for row in summary.rows:
        s, c, rate = row.student, row.counts, row.rate
        rows.append(
            [s.student_no or "", s.last_name, s.first_name, c["present"], c["late"], c["absent"], c["excused"],
             row.unmarked, "" if rate is None else round(rate)]
        )  # fmt: skip
    _write_csv(path, rows)


STATUS_MARK = {"present": "/", "late": "L", "absent": "A", "excused": "E"}


def attendance_month_html(register: MonthRegister, title: str) -> str:
    """A printable month register: students down the side, days across, totals on the right.

    Present is "/", late "L", absent "A", excused "E"; a blank cell is not marked.
    """
    days = register.days
    cell = 'style="border: 1px solid #999; padding: 2px 3px; text-align: center;"'
    name_cell = 'style="border: 1px solid #999; padding: 2px 6px; text-align: left;"'
    head = [f"<th {cell}>No.</th>", f"<th {name_cell}>Student</th>"]
    head += [f"<th {cell}>{day:%a}<br>{day.day}</th>" for day in days]
    head += [f"<th {cell}>{label}</th>" for label in ("Abs", "Late", "Exc", "%")]
    lines = ["<tr>" + "".join(head) + "</tr>"]
    for n, row in enumerate(register.rows, start=1):
        counts, rate = row.counts(), row.rate
        cells = [f"<td {cell}>{html.escape(row.student.student_no or str(n))}</td>"]
        cells.append(f"<td {name_cell}>{html.escape(row.student.last_name)}, {html.escape(row.student.first_name)}</td>")
        for day in days:
            status = row.statuses.get(day)
            cells.append(f"<td {cell}>{STATUS_MARK[status.value] if status else ''}</td>")
        cells += [f"<td {cell}>{counts[k]}</td>" for k in ("absent", "late", "excused")]
        cells.append(f"<td {cell}>{'' if rate is None else round(rate)}</td>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    absent = [f"<td {cell}>{register.absent_on(day) or ''}</td>" for day in days]
    lines.append(
        f'<tr><td {cell}></td><td {name_cell}><b>Absent</b></td>{"".join(absent)}'
        + f"<td {cell}></td>" * 4 + "</tr>"
    )
    rate = register.rate
    students, recorded = len(register.rows), len(register.recorded_days)
    summary = f"{students} student{'' if students == 1 else 's'} · {recorded} day{'' if recorded == 1 else 's'} recorded"
    if rate is not None:
        summary += f" · attendance {rate:.0f}%"
    return (
        '<html><body style="font-family: sans-serif; font-size: 8pt;">'
        f'<h2 style="margin-bottom: 2px;">{html.escape(title)}</h2>'
        f'<p style="color: #555;">{summary}. Present /, late L, absent A, excused E; blank = not marked.</p>'
        '<table width="100%" style="border-collapse: collapse;" cellspacing="0">' + "".join(lines) + "</table>"
        "</body></html>"
    )
