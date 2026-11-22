"""Write app data to files the teacher can open elsewhere, e.g. in a spreadsheet."""

import csv
import html
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from app.models import AttendanceStatus, Student
from app.services.attendance import DayRegister, MonthRegister, PeriodSummary, RegisterRow, StudentHistory
from app.services.dashboard import attendance_rate

ROSTER_COLUMNS = ("Student #", "Last name", "First name", "Status", "Notes")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: object) -> object:
    """Text that a spreadsheet would run as a formula, e.g. a note "=1+1", gets a leading
    apostrophe so it shows as typed. Numbers are left alone."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _write_csv(path: Path, rows: Sequence[Sequence[object]]) -> None:
    """UTF-8 with a byte-order mark so Excel shows accented names correctly. The file
    is written next to `path` first and renamed, so a failed export never leaves
    half a file behind.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".export-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows([_safe_cell(v) for v in row] for row in rows)
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


def roster_tsv(students: Sequence[Student]) -> str:
    """Students as tab-separated text with a heading row, to paste into a spreadsheet."""
    rows = [ROSTER_COLUMNS]
    for s in students:
        rows.append((s.student_no or "", s.last_name, s.first_name, "Active" if s.active else "Inactive",
                     " ".join(s.notes.split())))  # fmt: skip
    return "".join("\t".join(str(_safe_cell(v)) for v in row) + "\n" for row in rows)


WHOLE_CLASS = "Whole class"  # the last name of the totals row in attendance CSVs


def _rate_cell(rate: float | None) -> object:
    return "" if rate is None else round(rate)


def _month_rows(register: MonthRegister) -> list[Sequence[object]]:
    """One column per day with P, L, A or E (blank = not marked), then each student's totals
    and attendance rate. A last "Whole class" row gives how many were absent each recorded
    day and the class's totals, as on screen."""
    header = ["Student #", "Last name", "First name"]
    header += [day.isoformat() for day in register.days]
    header += ["Present", "Absent", "Late", "Excused", "Attendance %"]
    rows: list[Sequence[object]] = [header]
    for row in register.rows:
        s, counts, rate = row.student, row.counts(), row.rate
        line: list[object] = [s.student_no or "", s.last_name, s.first_name]
        line += [row.statuses[day].value[0].upper() if day in row.statuses else "" for day in register.days]
        line += [counts["present"], counts["absent"], counts["late"], counts["excused"]]
        line.append(_rate_cell(rate))
        rows.append(line)
    if register.rows:
        recorded, totals = set(register.recorded_days), register.counts()
        line = ["", WHOLE_CLASS, ""]
        line += [register.absent_on(day) if day in recorded else "" for day in register.days]
        line += [totals["present"], totals["absent"], totals["late"], totals["excused"], _rate_cell(register.rate)]
        rows.append(line)
    return rows


def write_attendance_csv(path: Path, register: MonthRegister) -> None:
    """Save a month of attendance as CSV; see _month_rows()."""
    _write_csv(path, _month_rows(register))


def attendance_month_tsv(register: MonthRegister) -> str:
    """A month of attendance as tab-separated text, to paste into a spreadsheet."""
    return "".join("\t".join(str(_safe_cell(v)) for v in row) + "\n" for row in _month_rows(register))


def write_attendance_summary_csv(path: Path, summary: PeriodSummary) -> None:
    """Save each student's totals for a period, e.g. a term, with their attendance rate,
    and a last "Whole class" row with the class's totals and rate."""
    rows: list[Sequence[object]] = [
        ["Student #", "Last name", "First name", "Present", "Late", "Absent", "Excused", "Not marked", "Attendance %"]
    ]
    for row in summary.rows:
        s, c, rate = row.student, row.counts, row.rate
        rows.append(
            [s.student_no or "", s.last_name, s.first_name, c["present"], c["late"], c["absent"], c["excused"],
             row.unmarked, _rate_cell(rate)]
        )  # fmt: skip
    if summary.rows:
        totals = {key: sum(row.counts[key] for row in summary.rows) for key in ("present", "late", "absent", "excused")}
        rows.append(
            ["", WHOLE_CLASS, "", totals["present"], totals["late"], totals["absent"], totals["excused"],
             sum(row.unmarked for row in summary.rows), _rate_cell(attendance_rate(totals))]
        )  # fmt: skip
    _write_csv(path, rows)


def write_student_history_csv(path: Path, history: StudentHistory) -> None:
    """Save every marked day of one student in one register, oldest first, e.g. for a
    meeting with their parents."""
    rows: list[Sequence[object]] = [("Date", "Day", "Status", "Note")]
    for record in sorted(history.records, key=lambda r: r.date):
        rows.append((record.date.isoformat(), f"{record.date:%A}", record.status.value.capitalize(), record.note))
    _write_csv(path, rows)


def absence_report(register: DayRegister, title: str) -> str:
    """The day's register as short text for the school office, e.g.

    7B · Daily (homeroom) · Monday 2 November 2026
    Absent (2): Ada Lovelace (Flu, 3rd day), Alan Turing
    Late (1): Grace Hopper
    In class: 22 of 24.

    An absence that runs on from earlier registers says which day of it this is.
    Students not marked yet are named last, since they don't count as present.
    """
    day = register.day
    lines = [f"{title} · {day:%A} {day.day} {day:%B} {day.year}"]
    groups = [(s.value.capitalize(), [r for r in register.rows if r.status is s])
              for s in (AttendanceStatus.ABSENT, AttendanceStatus.LATE, AttendanceStatus.EXCUSED)]  # fmt: skip
    groups.append(("Not marked", [r for r in register.rows if r.status is None]))
    for label, rows in groups:
        if rows:
            names = [r.student.full_name + _absence_details(r) for r in rows]
            lines.append(f"{label} ({len(rows)}): " + ", ".join(names))
    if len(lines) == 1:
        lines.append(f"Everyone present ({len(register.rows)})." if register.rows else "No students.")
    else:  # the office's headcount
        here = sum(1 for r in register.rows if r.status in (AttendanceStatus.PRESENT, AttendanceStatus.LATE))
        lines.append(f"In class: {here} of {len(register.rows)}.")  # late students are here too
    return "\n".join(lines) + "\n"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _absence_details(row: RegisterRow) -> str:
    """ " (Flu, 3rd day)", " (Flu)", " (2nd day)" or ""."""
    parts = [row.note] if row.note else []
    if row.status is AttendanceStatus.ABSENT and row.absent_streak >= 2:
        parts.append(f"{_ordinal(row.absent_streak)} day")
    return f" ({', '.join(parts)})" if parts else ""


STATUS_MARK = {"present": "/", "late": "L", "absent": "A", "excused": "E"}


def attendance_month_html(register: MonthRegister, title: str) -> str:
    """A printable month register: students down the side, days across, totals on the right.

    Present is "/", late "L", absent "A", excused "E"; a blank cell is not marked.
    The notes written that month follow the table, since a cell has no room for them.
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
        + _notes_html(register)
        + "</body></html>"
    )


def _notes_html(register: MonthRegister) -> str:
    """The month's notes, by day and then in register order; "" when there are none."""
    notes = sorted(
        ((day, n, row, note) for n, row in enumerate(register.rows) for day, note in row.notes.items()),
        key=lambda item: (item[0], item[1]),
    )
    if not notes:
        return ""
    items = []
    for day, _n, row, note in notes:
        status = row.statuses.get(day)
        mark = f" ({STATUS_MARK[status.value]})" if status else ""
        name = f"{row.student.last_name}, {row.student.first_name}"
        items.append(f"<li>{day:%a} {day.day}: {html.escape(name)}{mark}: {html.escape(note)}</li>")
    return '<h3 style="margin-bottom: 2px;">Notes</h3><ul style="margin-top: 2px;">' + "".join(items) + "</ul>"
