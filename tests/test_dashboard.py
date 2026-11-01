import sqlite3
from datetime import date, timedelta

import pytest

from app.models import SchoolClass, Student, Subject
from app.repositories.dashboard_repo import DashboardRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.dashboard import DashboardService, attendance_rate, letter_grade
from app.services.roster import RosterService

# There are no attendance or gradebook repositories yet (Phases 2-3), so these
# tests insert those rows directly.

TODAY = date(2026, 10, 30)  # a Friday


@pytest.fixture
def service(conn: sqlite3.Connection) -> DashboardService:
    return DashboardService(DashboardRepository(conn), StudentRepository(conn), SubjectRepository(conn))


@pytest.fixture
def class_id(roster: RosterService) -> int:
    return roster.save_class(SchoolClass(name="7B")).id


@pytest.fixture
def maths(roster: RosterService, class_id: int) -> int:
    return roster.save_subject(Subject(class_id=class_id, name="Maths")).id


def _student(roster: RosterService, class_id: int, first: str, last: str = "Test") -> int:
    return roster.save_student(Student(class_id=class_id, first_name=first, last_name=last)).id


def _mark(
    conn: sqlite3.Connection, student_id: int, day: date, status: str, subject_id: int | None = None
) -> None:
    conn.execute(
        "INSERT INTO attendance (student_id, subject_id, date, status) VALUES (?, ?, ?, ?)",
        (student_id, subject_id, day.isoformat(), status),
    )


def _category(conn: sqlite3.Connection, subject_id: int, name: str, weight: float) -> int:
    return conn.execute(
        "INSERT INTO categories (subject_id, name, weight) VALUES (?, ?, ?)", (subject_id, name, weight)
    ).lastrowid


def _assignment(
    conn: sqlite3.Connection, subject_id: int, category_id: int, title: str, max_score: float, day: date | None
) -> int:
    return conn.execute(
        "INSERT INTO assignments (subject_id, category_id, title, date, max_score) VALUES (?, ?, ?, ?, ?)",
        (subject_id, category_id, title, day.isoformat() if day else None, max_score),
    ).lastrowid


def _score(conn: sqlite3.Connection, assignment_id: int, student_id: int, score: float | None) -> None:
    conn.execute(
        "INSERT INTO scores (assignment_id, student_id, score) VALUES (?, ?, ?)",
        (assignment_id, student_id, score),
    )


def test_empty_class(service: DashboardService, class_id: int):
    s = service.summary(class_id, TODAY)
    assert (s.active_students, s.inactive_students) == (0, 0)
    assert s.week_rate is None and s.class_average is None
    assert s.attendance_days == [] and s.attention == [] and s.recent_assignments == []
    assert sum(s.grade_distribution.values()) == 0


def test_student_counts(service, roster, class_id):
    _student(roster, class_id, "Ada")
    roster.deactivate_student(_student(roster, class_id, "Alan"))
    s = service.summary(class_id, TODAY)
    assert (s.active_students, s.inactive_students) == (1, 1)


def test_attendance_rate_ignores_excused():
    assert attendance_rate({"present": 2, "late": 1, "absent": 1, "excused": 5}) == 75
    assert attendance_rate({"excused": 3}) is None


def test_week_rates_and_chart(service, roster, conn, class_id):
    ada, alan = _student(roster, class_id, "Ada"), _student(roster, class_id, "Alan")
    monday = TODAY - timedelta(days=4)
    _mark(conn, ada, monday, "present")
    _mark(conn, alan, monday, "absent")
    _mark(conn, ada, TODAY, "late")
    _mark(conn, alan, TODAY, "present")
    _mark(conn, ada, monday - timedelta(days=3), "present")  # last Friday
    _mark(conn, alan, monday - timedelta(days=3), "present")

    s = service.summary(class_id, TODAY)
    assert s.week_rate == 75
    assert s.previous_week_rate == 100
    assert [d.day for d in s.attendance_days] == [monday - timedelta(days=3), monday, TODAY]
    assert s.attendance_days[-1].counts == {"late": 1, "present": 1}


def test_chart_keeps_only_the_last_ten_days(service, roster, conn, class_id):
    ada = _student(roster, class_id, "Ada")
    for i in range(15):
        _mark(conn, ada, TODAY - timedelta(days=i), "present")
    _mark(conn, ada, TODAY + timedelta(days=1), "present")  # future dates are ignored
    days = service.summary(class_id, TODAY).attendance_days
    assert len(days) == 10 and days[-1].day == TODAY


def test_weighted_average_skips_missing_scores(service, roster, conn, class_id, maths):
    ada = _student(roster, class_id, "Ada")
    homework = _category(conn, maths, "Homework", 1)
    tests = _category(conn, maths, "Tests", 3)
    _score(conn, _assignment(conn, maths, homework, "HW 1", 10, TODAY), ada, 5)
    _score(conn, _assignment(conn, maths, homework, "HW 2", 10, TODAY), ada, None)
    _score(conn, _assignment(conn, maths, tests, "Test 1", 50, TODAY), ada, 45)

    s = service.summary(class_id, TODAY)
    assert s.class_average == pytest.approx((50 * 1 + 90 * 3) / 4)
    assert s.grade_distribution["B"] == 1


def test_zero_weights_count_equally(service, roster, conn, class_id, maths):
    ada = _student(roster, class_id, "Ada")
    a = _category(conn, maths, "A", 0)
    b = _category(conn, maths, "B", 0)
    _score(conn, _assignment(conn, maths, a, "One", 10, TODAY), ada, 10)
    _score(conn, _assignment(conn, maths, b, "Two", 10, TODAY), ada, 5)
    assert service.summary(class_id, TODAY).class_average == 75


@pytest.mark.parametrize("percent, letter", [(95, "A"), (90, "A"), (89.9, "B"), (60, "D"), (12, "F")])
def test_letter_grade(percent, letter):
    assert letter_grade(percent) == letter


def test_missing_work_counts_only_past_dated_assignments(service, roster, conn, class_id, maths):
    ada = _student(roster, class_id, "Ada")
    cat = _category(conn, maths, "Homework", 1)
    _score(conn, _assignment(conn, maths, cat, "Scored", 10, TODAY), ada, 0)  # 0 is a score
    _score(conn, _assignment(conn, maths, cat, "Not submitted", 10, TODAY), ada, None)
    _assignment(conn, maths, cat, "No row yet", 10, TODAY - timedelta(days=1))
    _assignment(conn, maths, cat, "Due later", 10, TODAY + timedelta(days=1))
    _assignment(conn, maths, cat, "Undated", 10, None)
    assert service.summary(class_id, TODAY).missing_total == 2


def test_needs_attention_uses_most_serious_reason(service, roster, conn, class_id, maths):
    maya = _student(roster, class_id, "Maya", "Okafor")
    jonas = _student(roster, class_id, "Jonas", "Berg")
    _student(roster, class_id, "Fine", "Student")
    for i in range(3):
        _mark(conn, maya, TODAY - timedelta(days=i), "absent")
        _mark(conn, jonas, TODAY - timedelta(days=i), "late")
    _mark(conn, maya, TODAY - timedelta(days=40), "absent")  # outside the window
    cat = _category(conn, maths, "Tests", 1)
    _score(conn, _assignment(conn, maths, cat, "Test", 100, TODAY), maya, 40)

    items = service.summary(class_id, TODAY).attention
    assert [(i.student.first_name, i.kind) for i in items] == [("Maya", "absent"), ("Jonas", "late")]
    assert items[0].reason == "3 absences in 30 days"


def test_inactive_students_are_left_out(service, roster, conn, class_id, maths):
    ada = _student(roster, class_id, "Ada")
    gone = _student(roster, class_id, "Gone")
    _mark(conn, ada, TODAY, "present")
    _mark(conn, gone, TODAY, "absent")
    cat = _category(conn, maths, "Tests", 1)
    test = _assignment(conn, maths, cat, "Test", 10, TODAY)
    _score(conn, test, ada, 10)
    _score(conn, test, gone, 0)
    roster.deactivate_student(gone)

    s = service.summary(class_id, TODAY)
    assert s.week_rate == 100
    assert s.class_average == 100
    assert s.recent_assignments[0].submitted == 1
    assert s.recent_assignments[0].average_percent == 100


def test_recent_assignments_newest_first(service, roster, conn, class_id, maths):
    _student(roster, class_id, "Ada")
    cat = _category(conn, maths, "Homework", 1)
    _assignment(conn, maths, cat, "Undated", 10, None)
    _assignment(conn, maths, cat, "Old", 10, TODAY - timedelta(days=9))
    _assignment(conn, maths, cat, "New", 10, TODAY)
    titles = [a.title for a in service.summary(class_id, TODAY).recent_assignments]
    assert titles == ["New", "Old", "Undated"]


def test_each_subject_counts_equally(service, roster, conn, class_id, maths):
    ada = _student(roster, class_id, "Ada")
    science = roster.save_subject(Subject(class_id=class_id, name="Science")).id
    # Maths has far more points, but the two subject averages still count equally.
    m = _category(conn, maths, "Tests", 1)
    _score(conn, _assignment(conn, maths, m, "Big test", 200, TODAY), ada, 200)
    sc = _category(conn, science, "Tests", 1)
    _score(conn, _assignment(conn, science, sc, "Quiz", 10, TODAY), ada, 5)
    assert service.summary(class_id, TODAY).class_average == 75


def test_dashboard_counts_daily_attendance_only(service, roster, conn, class_id, maths):
    ada = _student(roster, class_id, "Ada")
    _mark(conn, ada, TODAY, "present")
    _mark(conn, ada, TODAY, "absent", subject_id=maths)  # same day, Maths lesson
    s = service.summary(class_id, TODAY)
    assert s.week_rate == 100
    assert s.attendance_days[0].counts == {"present": 1}


def test_recent_assignments_show_subject(service, roster, conn, class_id, maths):
    _assignment(conn, maths, _category(conn, maths, "Homework", 1), "HW 1", 10, TODAY)
    assert service.summary(class_id, TODAY).recent_assignments[0].subject == "Maths"


def test_subject_summaries(service, roster, conn, class_id, maths):
    ada, alan = _student(roster, class_id, "Ada"), _student(roster, class_id, "Alan")
    roster.save_subject(Subject(class_id=class_id, name="Art", teacher="Ms. Chen"))
    cat = _category(conn, maths, "Tests", 1)
    test = _assignment(conn, maths, cat, "Test", 10, TODAY)
    _score(conn, test, ada, 9)
    _score(conn, test, alan, 5)

    by_name = {s.subject.name: s for s in service.summary(class_id, TODAY).subjects}
    assert list(by_name) == ["Art", "Maths"]
    assert (by_name["Maths"].average, by_name["Maths"].scored, by_name["Maths"].below_pass) == (70, 2, 1)
    assert (by_name["Art"].average, by_name["Art"].scored, by_name["Art"].subject.teacher) == (None, 0, "Ms. Chen")


def test_low_grades_name_the_subject(service, roster, conn, class_id, maths):
    ada, alan = _student(roster, class_id, "Ada"), _student(roster, class_id, "Alan")
    science = roster.save_subject(Subject(class_id=class_id, name="Science")).id
    for subject_id, ada_score, alan_score in [(maths, 9, 4), (science, 5, 3)]:
        test = _assignment(conn, subject_id, _category(conn, subject_id, "Tests", 1), "Test", 10, TODAY)
        _score(conn, test, ada, ada_score)
        _score(conn, test, alan, alan_score)

    # Ada's overall average is 70%, but she is failing Science.
    reasons = {i.student.first_name: i.reason for i in service.summary(class_id, TODAY).attention}
    assert reasons == {"Ada": "Science average is 50%", "Alan": "Below 60% in 2 subjects"}
