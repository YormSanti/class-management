import csv
from datetime import date
from pathlib import Path

from app.models import AttendanceStatus, Student
from app.services.attendance import MonthRegister, MonthRow
from app.services.export import write_attendance_csv, write_roster_csv


def test_roster_csv_opens_in_excel_with_accents(tmp_path: Path):
    path = tmp_path / "7B students.csv"
    students = [
        Student(class_id=1, first_name="Zoë", last_name="Brontë", student_no="007", notes="Line 1\nLine 2"),
        Student(class_id=1, first_name="Alan", last_name="Turing", active=False),
    ]
    write_roster_csv(path, students)

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for Excel
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [
        ["Student #", "Last name", "First name", "Status", "Notes"],
        ["007", "Brontë", "Zoë", "Active", "Line 1\nLine 2"],
        ["", "Turing", "Alan", "Inactive", ""],
    ]
    assert list(tmp_path.iterdir()) == [path]  # no temp file left behind


def test_roster_csv_replaces_existing_file(tmp_path: Path):
    path = tmp_path / "out.csv"
    path.write_text("old")
    write_roster_csv(path, [])
    assert path.read_text(encoding="utf-8-sig").strip() == "Student #,Last name,First name,Status,Notes"


def test_attendance_csv(tmp_path: Path):
    days = [date(2026, 10, 1), date(2026, 10, 2)]
    register = MonthRegister(
        class_id=1, year=2026, month=10, subject_id=None, days=days,
        rows=[
            MonthRow(Student(class_id=1, first_name="Chloé", last_name="Dubois", student_no="03"),
                     {days[0]: AttendanceStatus.PRESENT, days[1]: AttendanceStatus.ABSENT}),
            MonthRow(Student(class_id=1, first_name="Ada", last_name="Lovelace")),
        ],
    )  # fmt: skip
    path = tmp_path / "october.csv"
    write_attendance_csv(path, register)

    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM for Excel
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [
        ["Student #", "Last name", "First name", "2026-10-01", "2026-10-02", "Present", "Absent", "Late", "Excused",
         "Attendance %"],
        ["03", "Dubois", "Chloé", "P", "A", "1", "1", "0", "0", "50"],
        ["", "Lovelace", "Ada", "", "", "0", "0", "0", "0", ""],
        ["", "Whole class", "", "0", "1", "1", "1", "0", "0", "50"],
    ]


def test_attendance_summary_csv(tmp_path: Path):
    from app.services.attendance import PeriodRow, PeriodSummary
    from app.services.export import write_attendance_summary_csv

    counts = {"present": 8, "absent": 1, "late": 1, "excused": 0}
    none = {"present": 0, "absent": 0, "late": 0, "excused": 0}
    summary = PeriodSummary(
        class_id=1, start=date(2026, 10, 1), end=date(2026, 10, 31), subject_id=None, recorded_days=10,
        rows=[
            PeriodRow(Student(class_id=1, first_name="Chloé", last_name="Dubois", student_no="03"), counts, 0),
            PeriodRow(Student(class_id=1, first_name="Ada", last_name="Lovelace"), none, 10),
        ],
    )  # fmt: skip
    path = tmp_path / "term.csv"
    write_attendance_summary_csv(path, summary)
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [
        ["Student #", "Last name", "First name", "Present", "Late", "Absent", "Excused", "Not marked", "Attendance %"],
        ["03", "Dubois", "Chloé", "8", "1", "1", "0", "0", "90"],
        ["", "Lovelace", "Ada", "0", "0", "0", "0", "10", ""],
        ["", "Whole class", "", "8", "1", "1", "0", "10", "90"],
    ]


def test_attendance_month_html():
    from app.services.export import attendance_month_html

    days = [date(2026, 10, 1), date(2026, 10, 2)]
    register = MonthRegister(
        class_id=1, year=2026, month=10, subject_id=None, days=days,
        rows=[
            MonthRow(Student(class_id=1, first_name="Chloé", last_name="O<Brien", student_no="03"),
                     {days[0]: AttendanceStatus.PRESENT, days[1]: AttendanceStatus.ABSENT}),
        ],
    )  # fmt: skip
    page = attendance_month_html(register, "7B · October 2026")
    assert "<h2" in page and "7B · October 2026" in page
    assert "O&lt;Brien, Chloé" in page  # names are escaped
    assert "Thu<br>1" in page and "Fri<br>2" in page
    assert "1 student · 2 days recorded · attendance 50%" in page


def test_roster_tsv_has_a_heading_and_one_line_per_student():
    from app.services.export import roster_tsv

    students = [
        Student(class_id=1, first_name="Ada", last_name="Lovelace", student_no="001", notes="Front row\nGlasses"),
        Student(class_id=1, first_name="Alan", last_name="Turing", active=False),
    ]
    assert roster_tsv(students) == (
        "Student #\tLast name\tFirst name\tStatus\tNotes\n"
        "001\tLovelace\tAda\tActive\tFront row Glasses\n"
        "\tTuring\tAlan\tInactive\t\n"
    )


def test_text_that_looks_like_a_formula_is_written_as_text(tmp_path: Path):
    from app.services.export import roster_tsv

    student = Student(class_id=1, first_name="=HYPERLINK(1)", last_name="+Lee", notes="@home")
    path = tmp_path / "students.csv"
    write_roster_csv(path, [student])
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1] == ["", "'+Lee", "'=HYPERLINK(1)", "Active", "'@home"]
    assert "'=HYPERLINK(1)" in roster_tsv([student])


def test_attendance_csvs_have_no_totals_row_without_students(tmp_path: Path):
    from app.services.attendance import PeriodSummary
    from app.services.export import write_attendance_summary_csv

    register = MonthRegister(class_id=1, year=2026, month=10, subject_id=None, days=[date(2026, 10, 1)], rows=[])
    write_attendance_csv(tmp_path / "month.csv", register)
    summary = PeriodSummary(1, date(2026, 10, 1), date(2026, 10, 31), None, 0, [])
    write_attendance_summary_csv(tmp_path / "term.csv", summary)
    for name in ("month.csv", "term.csv"):
        assert len((tmp_path / name).read_text(encoding="utf-8-sig").splitlines()) == 1
