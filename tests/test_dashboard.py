import sqlite3
from datetime import date, timedelta

import pytest

from app.models import SchoolClass, Student
from app.repositories.dashboard_repo import DashboardRepository
from app.repositories.student_repo import StudentRepository
from app.services.dashboard import DashboardService, attendance_rate, letter_grade
from app.services.roster import RosterService

# There are no attendance or gradebook repositories yet (Phases 2-3), so these
# tests insert those rows directly.

TODAY = date(2026, 10, 30)  # a Friday


@pytest.fixture
def service(conn: sqlite3.Connection) -> DashboardService:
    return DashboardService(DashboardRepository(conn), StudentRepository(conn))


@pytest.fixture
def class_id(roster: RosterService) -> int:
    return roster.save_class(SchoolClass(name="7B")).id


def _student(roster: RosterService, class_id: int, first: str, last: str = "Test") -> int:
    return roster.save_student(Student(class_id=class_id, first_name=first, last_name=last)).id


def _mark(conn: sqlite3.Connection, student_id: int, day: date, status: str) -> None:
    conn.execute(
        "INSERT INTO attendance (student_id, date, status) VALUES (?, ?, ?)",
        (student_id, day.isoformat(), status),
    )


def _category(conn: sqlite3.Connection, class_id: int, name: str, weight: float) -> int:
    return conn.execute(
        "INSERT INTO categories (class_id, name, weight) VALUES (?, ?, ?)", (class_id, name, weight)
    ).lastrowid


def _assignment(
    conn: sqlite3.Connection, class_id: int, category_id: int, title: str, max_score: float, day: date | None
) -> int:
    return conn.execute(
        "INSERT INTO assignments (class_id, category_id, title, date, max_score) VALUES (?, ?, ?, ?, ?)",
        (class_id, category_id, title, day.isoformat() if day else None, max_score),
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


def test_weighted_average_skips_missing_scores(service, roster, conn, class_id):
    ada = _student(roster, class_id, "Ada")
    homework = _category(conn, class_id, "Homework", 1)
    tests = _category(conn, class_id, "Tests", 3)
    _score(conn, _assignment(conn, class_id, homework, "HW 1", 10, TODAY), ada, 5)
    _score(conn, _assignment(conn, class_id, homework, "HW 2", 10, TODAY), ada, None)
    _score(conn, _assignment(conn, class_id, tests, "Test 1", 50, TODAY), ada, 45)

    s = service.summary(class_id, TODAY)
    assert s.class_average == pytest.approx((50 * 1 + 90 * 3) / 4)
    assert s.grade_distribution["B"] == 1


def test_zero_weights_count_equally(service, roster, conn, class_id):
    ada = _student(roster, class_id, "Ada")
    a = _category(conn, class_id, "A", 0)
    b = _category(conn, class_id, "B", 0)
    _score(conn, _assignment(conn, class_id, a, "One", 10, TODAY), ada, 10)
    _score(conn, _assignment(conn, class_id, b, "Two", 10, TODAY), ada, 5)
    assert service.summary(class_id, TODAY).class_average == 75


@pytest.mark.parametrize("percent, letter", [(95, "A"), (90, "A"), (89.9, "B"), (60, "D"), (12, "F")])
def test_letter_grade(percent, letter):
    assert letter_grade(percent) == letter


def test_missing_work_counts_only_past_dated_assignments(service, roster, conn, class_id):
    ada = _student(roster, class_id, "Ada")
    cat = _category(conn, class_id, "Homework", 1)
    _score(conn, _assignment(conn, class_id, cat, "Scored", 10, TODAY), ada, 0)  # 0 is a score
    _score(conn, _assignment(conn, class_id, cat, "Not submitted", 10, TODAY), ada, None)
    _assignment(conn, class_id, cat, "No row yet", 10, TODAY - timedelta(days=1))
    _assignment(conn, class_id, cat, "Due later", 10, TODAY + timedelta(days=1))
    _assignment(conn, class_id, cat, "Undated", 10, None)
    assert service.summary(class_id, TODAY).missing_total == 2


def test_needs_attention_uses_most_serious_reason(service, roster, conn, class_id):
    maya = _student(roster, class_id, "Maya", "Okafor")
    jonas = _student(roster, class_id, "Jonas", "Berg")
    _student(roster, class_id, "Fine", "Student")
    for i in range(3):
        _mark(conn, maya, TODAY - timedelta(days=i), "absent")
        _mark(conn, jonas, TODAY - timedelta(days=i), "late")
    _mark(conn, maya, TODAY - timedelta(days=40), "absent")  # outside the window
    cat = _category(conn, class_id, "Tests", 1)
    _score(conn, _assignment(conn, class_id, cat, "Test", 100, TODAY), maya, 40)

    items = service.summary(class_id, TODAY).attention
    assert [(i.student.first_name, i.kind) for i in items] == [("Maya", "absent"), ("Jonas", "late")]
    assert items[0].reason == "3 absences in the last 30 days"


def test_inactive_students_are_left_out(service, roster, conn, class_id):
    ada = _student(roster, class_id, "Ada")
    gone = _student(roster, class_id, "Gone")
    _mark(conn, ada, TODAY, "present")
    _mark(conn, gone, TODAY, "absent")
    cat = _category(conn, class_id, "Tests", 1)
    test = _assignment(conn, class_id, cat, "Test", 10, TODAY)
    _score(conn, test, ada, 10)
    _score(conn, test, gone, 0)
    roster.deactivate_student(gone)

    s = service.summary(class_id, TODAY)
    assert s.week_rate == 100
    assert s.class_average == 100
    assert s.recent_assignments[0].submitted == 1
    assert s.recent_assignments[0].average_percent == 100


def test_recent_assignments_newest_first(service, roster, conn, class_id):
    _student(roster, class_id, "Ada")
    cat = _category(conn, class_id, "Homework", 1)
    _assignment(conn, class_id, cat, "Undated", 10, None)
    _assignment(conn, class_id, cat, "Old", 10, TODAY - timedelta(days=9))
    _assignment(conn, class_id, cat, "New", 10, TODAY)
    titles = [a.title for a in service.summary(class_id, TODAY).recent_assignments]
    assert titles == ["New", "Old", "Undated"]
