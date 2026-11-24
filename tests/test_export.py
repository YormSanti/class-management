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
         "Not marked", "Attendance %"],
        ["03", "Dubois", "Chloé", "P", "A", "1", "1", "0", "0", "0", "50"],
        ["", "Lovelace", "Ada", "", "", "0", "0", "0", "0", "2", ""],
        ["", "Whole class", "", "0", "1", "1", "1", "0", "0", "2", "50"],
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
    page = attendance_month_html(register, "7B · October 2026", printed=date(2026, 11, 3))
    assert "<h2" in page and "7B · October 2026" in page
    assert "O&lt;Brien, Chloé" in page  # names are escaped
    assert "Thu<br>1" in page and "Fri<br>2" in page
    assert "1 student · 2 days recorded · attendance 50% · printed 3 November 2026" in page
    assert "#e6e6e6" not in page  # no weekend days

    register.days.append(date(2026, 10, 3))  # a Saturday with a mark
    register.rows[0].statuses[date(2026, 10, 3)] = AttendanceStatus.PRESENT
    page = attendance_month_html(register, "7B")
    assert page.count("#e6e6e6") == 3  # its heading, the student's cell and the absent row
    assert "Notes" not in page


def test_printed_numbers_column_uses_a_dash_when_the_class_uses_numbers():
    from app.services.export import _numbers_column

    def students(*numbers):
        return [Student(class_id=1, first_name="A", last_name=str(i), student_no=no) for i, no in enumerate(numbers)]

    assert _numbers_column(students("S01", None, "S03")) == ["S01", "—", "S03"]  # not "2", a number of its own
    assert _numbers_column(students(None, None)) == ["1", "2"]
    assert _numbers_column([]) == []


def test_attendance_month_html_lists_the_notes_by_day():
    from app.services.export import attendance_month_html

    days = [date(2026, 10, 1), date(2026, 10, 2)]
    register = MonthRegister(
        class_id=1, year=2026, month=10, subject_id=None, days=days,
        rows=[
            MonthRow(Student(class_id=1, first_name="Chloé", last_name="Dubois"),
                     {days[0]: AttendanceStatus.LATE, days[1]: AttendanceStatus.ABSENT},
                     {days[1]: "Flu <fever>"}),
            MonthRow(Student(class_id=1, first_name="Ada", last_name="Lovelace"),
                     {days[0]: AttendanceStatus.EXCUSED}, {days[0]: "Dentist"}),
        ],
    )  # fmt: skip
    page = attendance_month_html(register, "7B · October 2026")
    notes = page[page.index("<h3"):]
    assert notes.index("Thu 1: Lovelace, Ada (E): Dentist") < notes.index("Fri 2: Dubois, Chloé (A): Flu &lt;fever&gt;")


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


def test_student_history_csv_lists_every_marked_day_oldest_first(tmp_path: Path):
    from app.models import AttendanceRecord
    from app.services.attendance import StudentHistory
    from app.services.export import write_student_history_csv

    ada = Student(class_id=1, first_name="Ada", last_name="Lovelace", id=1)
    history = StudentHistory(ada, [
        AttendanceRecord(1, date(2026, 10, 2), AttendanceStatus.ABSENT, "=Flu"),
        AttendanceRecord(1, date(2026, 10, 1), AttendanceStatus.PRESENT),
    ])  # fmt: skip
    path = tmp_path / "ada.csv"
    write_student_history_csv(path, history)
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [
        ["Date", "Day", "Status", "Note"],
        ["2026-10-01", "Thursday", "Present", ""],
        ["2026-10-02", "Friday", "Absent", "'=Flu"],
    ]


def test_absence_report_names_who_is_not_present():
    from app.services.attendance import DayRegister, RegisterRow
    from app.services.export import absence_report

    def row(first: str, status: AttendanceStatus | None, note: str = "") -> RegisterRow:
        return RegisterRow(Student(class_id=1, first_name=first, last_name="Doe"), status, note)

    rows = [row("Ada", AttendanceStatus.ABSENT, "Flu"), row("Alan", AttendanceStatus.PRESENT),
            row("Grace", AttendanceStatus.LATE), row("Kim", AttendanceStatus.ABSENT), row("Lin", None)]  # fmt: skip
    register = DayRegister(1, date(2026, 11, 2), None, rows)
    assert absence_report(register, "7B · Daily (homeroom)") == (
        "7B · Daily (homeroom) · Monday 2 November 2026\n"
        "Absent (2): Ada Doe (Flu), Kim Doe\n"
        "Late (1): Grace Doe\n"
        "Not marked (1): Lin Doe\n"
        "In class: 2 of 5.\n"
    )
    rows[0].absent_streak, rows[3].absent_streak = 3, 2
    assert "Absent (2): Ada Doe (Flu, 3rd day), Kim Doe (2nd day)\n" in absence_report(register, "7B")
    everyone = DayRegister(1, date(2026, 11, 2), None, [row("Alan", AttendanceStatus.PRESENT)])
    assert absence_report(everyone, "7B").endswith("\nEveryone present (1).\n")


def test_ordinal():
    from app.services.export import _ordinal

    assert [_ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th"
    ]


def test_history_text_lists_the_days_not_present_oldest_first():
    from app.models import AttendanceRecord
    from app.services.attendance import StudentHistory
    from app.services.export import history_text

    student = Student(class_id=1, first_name="Ada", last_name="Lovelace")
    records = [AttendanceRecord(1, date(2026, 11, 4), AttendanceStatus.LATE),
               AttendanceRecord(1, date(2026, 11, 3), AttendanceStatus.ABSENT, "Flu"),
               AttendanceRecord(1, date(2026, 11, 2), AttendanceStatus.PRESENT)]  # fmt: skip
    assert history_text(StudentHistory(student, records), "Daily (homeroom)") == (
        "Ada Lovelace · Daily (homeroom)\n"
        "1 present · 1 late · 1 absent · 0 excused · attendance 67%\n"
        "Tue 3 Nov 2026: Absent (Flu)\n"
        "Wed 4 Nov 2026: Late\n"
    )


def test_attendance_period_html():
    from app.services.attendance import PeriodRow, PeriodSummary
    from app.services.export import attendance_period_html

    counts = {"present": 18, "late": 1, "absent": 2, "excused": 1}
    summary = PeriodSummary(1, date(2026, 9, 1), date(2026, 9, 30), None, 22, [
        PeriodRow(Student(class_id=1, first_name="Ada", last_name="O<Brien"), counts, 0),
    ])  # fmt: skip
    page = attendance_period_html(summary, "7B · September", printed=date(2026, 10, 1))
    assert "O&lt;Brien, Ada" in page
    assert "1 September 2026 to 30 September 2026 · 22 days recorded · printed 1 October 2026" in page
    assert page.count("90%") == 2  # the student and the whole class


def test_year_roster_csv_has_a_class_column(tmp_path):
    from app.services.export import write_year_roster_csv

    path = tmp_path / "year.csv"
    ada = Student(class_id=1, first_name="Ada", last_name="Lovelace", student_no="1")
    alan = Student(class_id=2, first_name="Alan", last_name="Turing")
    write_year_roster_csv(path, [("7B", [ada]), ("7C", [alan])])
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines == [
        "Class,Student #,Last name,First name,Status,Notes",
        "7B,1,Lovelace,Ada,Active,",
        "7C,,Turing,Alan,Active,",
    ]


def test_gradebook_csv_has_scores_category_percents_and_averages(conn, roster, tmp_path):
    from app.models import Assignment, Category, SchoolClass, Student, Subject
    from app.repositories.gradebook_repo import GradebookRepository
    from app.repositories.student_repo import StudentRepository
    from app.repositories.subject_repo import SubjectRepository
    from app.services.export import write_gradebook_csv
    from app.services.gradebook import GradebookService

    grades = GradebookService(GradebookRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    class_id = roster.save_class(SchoolClass(name="7B")).id
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace", student_no="S1")).id
    roster.save_student(Student(class_id, "Bob", "Smith"))
    maths = roster.save_subject(Subject(class_id=class_id, name="Maths")).id
    tests = grades.save_category(Category(maths, "Tests", 100)).id
    t1 = grades.save_assignment(Assignment(maths, tests, "Test 1", 10)).id
    t2 = grades.save_assignment(Assignment(maths, tests, "Test 2", 20)).id
    grades.enter_score(t1, ada, "7.5")
    grades.enter_score(t2, ada, "ex")
    path = tmp_path / "maths.csv"
    write_gradebook_csv(path, grades.sheet(maths))
    assert path.read_text(encoding="utf-8-sig").splitlines() == [
        "Student #,Last name,First name,Test 1 (/10),Test 2 (/20),Tests %,Average %,Grade",
        "S1,Lovelace,Ada,7.5,ex,75.0,75.0,C",
        ",Smith,Bob,,,,,",
    ]


def test_ranking_csv_lists_places_best_first_then_those_unscored(tmp_path):
    from app.models import Student
    from app.services.export import write_ranking_csv
    from app.services.rankings import make_ranking

    ada = Student(1, "Ada", "Lovelace", student_no="S1", id=1)
    bob = Student(1, "Bob", "Smith", id=2)
    cy = Student(1, "Cy", "Young", id=3)
    ranking = make_ranking([ada, bob, cy], {1: 72.25, 2: 91.0})
    path = tmp_path / "ranking.csv"
    write_ranking_csv(path, ranking)
    assert path.read_text(encoding="utf-8-sig").splitlines() == [
        "Place,Student #,Last name,First name,Average %,Grade",
        "1,,Smith,Bob,91.0,A",
        "2,S1,Lovelace,Ada,72.2,C",
        ",,Young,Cy,,",
    ]
    ranking.subjects_counted = {1: 2, 2: 1}
    write_ranking_csv(path, ranking, overall=True)
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].endswith(",Subjects")
    assert lines[1:] == ["1,,Smith,Bob,91.0,A,1", "2,S1,Lovelace,Ada,72.2,C,2", ",,Young,Cy,,,0"]
