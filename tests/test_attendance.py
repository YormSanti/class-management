import sqlite3
from datetime import date

import pytest

from app.models import AttendanceStatus, SchoolClass, Student, Subject
from app.repositories.attendance_repo import AttendanceRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.attendance import (
    UNMARKED,
    AttendanceError,
    AttendanceService,
    RegisterRow,
    day_warning,
    school_day,
)
from app.services.roster import RosterService

P, L, A, E = AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED
DAY = date(2026, 11, 6)  # a Friday


@pytest.fixture
def attendance(conn: sqlite3.Connection) -> AttendanceService:
    return AttendanceService(AttendanceRepository(conn), StudentRepository(conn), SubjectRepository(conn))


@pytest.fixture
def klass(roster: RosterService) -> int:
    return roster.save_class(SchoolClass(name="7B", term="2026-27"), "Maths").id


def _student(roster: RosterService, class_id: int, first: str, last: str) -> int:
    return roster.save_student(Student(class_id=class_id, first_name=first, last_name=last)).id


def test_school_day_skips_weekends():
    assert school_day(DAY, 1) == date(2026, 11, 9)  # Friday -> Monday
    assert school_day(date(2026, 11, 9), -1) == DAY
    assert school_day(DAY, -2) == date(2026, 11, 4)
    assert school_day(date(2026, 11, 7), 1) == date(2026, 11, 9)  # Saturday -> Monday
    assert school_day(DAY, 0) == DAY


def test_new_register_lists_active_students_unmarked(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    grace = _student(roster, klass, "Grace", "Hopper")
    roster.deactivate_student(_student(roster, klass, "Old", "Student"))

    register = attendance.day_register(klass, DAY)

    assert [r.student.id for r in register.rows] == [grace, ada]  # sorted by last name
    assert all(r.status is None for r in register.rows)
    assert register.counts()[UNMARKED] == 2
    assert register.rate is None


def test_mark_change_and_clear(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    attendance.mark(ada, DAY, P)
    attendance.mark(ada, DAY, L)
    assert attendance.day_register(klass, DAY).rows[0].status is L

    attendance.clear(ada, DAY)
    assert attendance.day_register(klass, DAY).rows[0].status is None


def test_changing_status_keeps_note(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    attendance.mark(ada, DAY, A)
    attendance.set_note(ada, DAY, "  Dentist  ")
    attendance.mark(ada, DAY, E)
    row = attendance.day_register(klass, DAY).rows[0]
    assert (row.status, row.note) == (E, "Dentist")


def test_note_needs_a_status(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    with pytest.raises(AttendanceError):
        attendance.set_note(ada, DAY, "Bus late")


def test_daily_and_subject_registers_are_separate(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    maths = roster.list_subjects(klass)[0].id
    attendance.mark(ada, DAY, P)
    attendance.mark(ada, DAY, A, subject_id=maths)

    assert attendance.day_register(klass, DAY).rows[0].status is P
    assert attendance.day_register(klass, DAY, maths).rows[0].status is A
    attendance.clear_day(klass, DAY, maths)
    assert attendance.day_register(klass, DAY).rows[0].status is P
    assert attendance.day_register(klass, DAY, maths).rows[0].status is None


def test_subject_of_another_class_is_refused(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    other = roster.save_class(SchoolClass(name="8A"))
    science = roster.save_subject(Subject(class_id=other.id, name="Science")).id
    with pytest.raises(AttendanceError):
        attendance.mark(ada, DAY, P, subject_id=science)
    with pytest.raises(AttendanceError):
        attendance.day_register(klass, DAY, science)


def test_inactive_student_cannot_be_marked(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    roster.deactivate_student(ada)
    with pytest.raises(AttendanceError, match="inactive"):
        attendance.mark(ada, DAY, P)


def test_mark_unmarked_leaves_marked_students_alone(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    _student(roster, klass, "Grace", "Hopper")
    _student(roster, klass, "Alan", "Turing")
    attendance.mark(ada, DAY, A)

    assert attendance.mark_unmarked(klass, DAY) == 2
    counts = attendance.day_register(klass, DAY).counts()
    assert counts == {"present": 2, "absent": 1, "late": 0, "excused": 0, UNMARKED: 0}
    assert attendance.mark_unmarked(klass, DAY) == 0


def test_clear_day_only_touches_that_day_and_class(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    other = roster.save_class(SchoolClass(name="8A"))
    bob = _student(roster, other.id, "Bob", "Builder")
    attendance.mark(ada, DAY, P)
    attendance.mark(ada, school_day(DAY, -1), P)
    attendance.mark(bob, DAY, P)

    assert attendance.clear_day(klass, DAY) == 1
    assert attendance.day_register(klass, DAY).rows[0].status is None
    assert attendance.day_register(klass, school_day(DAY, -1)).rows[0].status is P
    assert attendance.day_register(other.id, DAY).rows[0].status is P


def test_rate_ignores_excused_and_unmarked(attendance, roster, klass):
    ids = [_student(roster, klass, "S", f"N{i}") for i in range(5)]
    for sid, status in zip(ids, (P, L, A, E)):
        attendance.mark(sid, DAY, status)
    assert attendance.day_register(klass, DAY).rate == pytest.approx(200 / 3)


def test_recent_counts_cover_last_30_days_of_the_same_register(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    maths = roster.list_subjects(klass)[0].id
    for back in (0, 5, 29):
        attendance.mark(ada, date.fromordinal(DAY.toordinal() - back), A)
    attendance.mark(ada, date.fromordinal(DAY.toordinal() - 30), A)  # outside the window
    attendance.mark(ada, date.fromordinal(DAY.toordinal() - 1), A, subject_id=maths)  # other register
    attendance.mark(ada, date.fromordinal(DAY.toordinal() + 1), A)  # after the day shown

    row = attendance.day_register(klass, DAY).rows[0]
    assert row.recent == {"absent": 3}
    assert row.recent_text == "3 absences"
    assert row.recent_tone == "danger"


def test_recent_text_and_tone():
    student = Student(class_id=1, first_name="A", last_name="B")
    assert RegisterRow(student, None).recent_text == ""
    row = RegisterRow(student, None, recent={"absent": 1, "late": 3, "excused": 2})
    assert row.recent_text == "1 absence · 3 late · 2 excused"
    assert row.recent_tone == "warn"
    assert RegisterRow(student, None, recent={"late": 2}).recent_tone == ""


def test_month_register_lists_weekdays_and_marked_weekends(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    grace = _student(roster, klass, "Grace", "Hopper")
    attendance.mark(ada, date(2026, 10, 1), P)
    attendance.mark(ada, date(2026, 10, 2), A)
    attendance.mark(grace, date(2026, 10, 2), L)
    attendance.mark(ada, date(2026, 10, 10), E)  # a Saturday trip
    attendance.mark(ada, date(2026, 11, 2), A)  # next month

    month = attendance.month_register(klass, 2026, 10)

    assert len(month.days) == 23  # 22 weekdays + the Saturday
    assert month.days[0] == date(2026, 10, 1) and month.days[-1] == date(2026, 10, 30)
    assert date(2026, 10, 10) in month.days and date(2026, 10, 11) not in month.days
    assert month.recorded_days == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 10)]
    hopper, lovelace = month.rows
    assert lovelace.counts() == {"present": 1, "absent": 1, "late": 0, "excused": 1}
    assert lovelace.rate == 50
    assert hopper.statuses == {date(2026, 10, 2): L}
    assert month.absent_on(date(2026, 10, 2)) == 1
    assert month.counts() == {"present": 1, "absent": 1, "late": 1, "excused": 1}
    assert month.rate == pytest.approx(200 / 3)


def test_month_register_keeps_registers_apart(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    maths = roster.list_subjects(klass)[0].id
    attendance.mark(ada, date(2026, 10, 1), A, subject_id=maths)
    assert attendance.month_register(klass, 2026, 10).recorded_days == []
    assert attendance.month_register(klass, 2026, 10, maths).rows[0].statuses == {date(2026, 10, 1): A}


def test_day_warning_for_future_and_weekend_days():
    friday = date(2026, 11, 6)
    assert day_warning(friday, friday) is None
    assert day_warning(date(2026, 11, 2), friday) is None  # an earlier weekday
    assert day_warning(date(2026, 11, 7), friday) == "This day is in the future (tomorrow). Check the date before marking."
    assert day_warning(date(2026, 11, 9), friday).startswith("This day is in the future (in 3 days)")
    assert day_warning(date(2026, 10, 31), friday) == "Saturday is a weekend day. Check the date before marking."


def test_snapshot_and_restore_undo_a_day(roster: RosterService, conn: sqlite3.Connection):
    from app.repositories.attendance_repo import AttendanceRepository
    from app.repositories.student_repo import StudentRepository
    from app.repositories.subject_repo import SubjectRepository
    from app.models import AttendanceStatus, SchoolClass, Student

    service = AttendanceService(AttendanceRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    class_id = roster.save_class(SchoolClass(name="7B")).id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace")).id
    alan = roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing")).id
    day = date(2026, 11, 6)
    service.mark(ada, day, AttendanceStatus.LATE)
    service.set_note(ada, day, "Bus")
    before = service.snapshot(class_id, day)

    service.mark_unmarked(class_id, day)
    service.mark(ada, day, AttendanceStatus.ABSENT)
    service.mark(ada, date(2026, 11, 5), AttendanceStatus.ABSENT)  # another day is left alone
    service.restore(class_id, day, None, before)

    rows = {r.student.id: r for r in service.day_register(class_id, day).rows}
    assert (rows[ada].status, rows[ada].note) == (AttendanceStatus.LATE, "Bus")
    assert rows[alan].status is None
    assert service.day_register(class_id, date(2026, 11, 5)).rows[0].status == AttendanceStatus.ABSENT


def test_student_history(roster: RosterService, conn: sqlite3.Connection):
    from app.repositories.attendance_repo import AttendanceRepository
    from app.repositories.student_repo import StudentRepository
    from app.repositories.subject_repo import SubjectRepository
    from app.models import AttendanceStatus, SchoolClass, Student, Subject

    service = AttendanceService(AttendanceRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    class_id = roster.save_class(SchoolClass(name="7B")).id
    maths = roster.save_subject(Subject(class_id=class_id, name="Maths")).id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace")).id
    service.mark(ada, date(2026, 11, 2), AttendanceStatus.PRESENT)
    service.mark(ada, date(2026, 11, 3), AttendanceStatus.ABSENT)
    service.set_note(ada, date(2026, 11, 3), "Flu")
    service.mark(ada, date(2026, 11, 4), AttendanceStatus.LATE)
    service.mark(ada, date(2026, 11, 4), AttendanceStatus.ABSENT, maths)  # another register

    history = service.student_history(ada)
    assert [r.date.day for r in history.records] == [4, 3, 2]
    assert [(r.date.day, r.note) for r in history.not_present] == [(4, ""), (3, "Flu")]
    assert history.counts() == {"present": 1, "absent": 1, "late": 1, "excused": 0}
    assert round(history.rate) == 67
    assert [r.date.day for r in service.student_history(ada, maths).records] == [4]
    with pytest.raises(AttendanceError):
        service.student_history(999)
