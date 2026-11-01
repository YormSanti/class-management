import csv
from pathlib import Path

from app.models import Student
from app.services.export import write_roster_csv


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
