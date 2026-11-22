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
    check_day,
    day_warning,
    school_day,
    school_days,
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


def test_note_is_checked_like_a_mark(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    attendance.mark(ada, DAY, A)
    other_class = roster.save_class(SchoolClass(name="8C"), "Science").id
    science = roster.list_subjects(other_class)[0].id
    with pytest.raises(AttendanceError, match="doesn't belong"):
        attendance.set_note(ada, DAY, "Bus late", subject_id=science)

    roster.deactivate_student(ada)
    with pytest.raises(AttendanceError, match="inactive"):
        attendance.set_note(ada, DAY, "Bus late")
    roster.reactivate_student(ada)
    assert attendance.day_register(klass, DAY).rows[0].note == ""


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


def test_clearing_checks_the_register_belongs_to_the_class(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    other = roster.save_class(SchoolClass(name="8A"), "Science").id
    science = roster.list_subjects(other)[0].id
    attendance.mark(ada, DAY, A)
    with pytest.raises(AttendanceError, match="doesn't belong"):
        attendance.clear(ada, DAY, science)
    with pytest.raises(AttendanceError, match="no longer exists"):
        attendance.clear(ada + 100, DAY)
    assert attendance.day_register(klass, DAY).rows[0].status is A


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
    attendance.mark(ada, date.fromordinal(DAY.toordinal() - 2), P)

    row = attendance.day_register(klass, DAY).rows[0]
    assert row.recent == {"absent": 3, "present": 1}
    assert row.absent_streak == 1
    assert row.recent_text == "3 absences"
    assert row.recent_tone == "danger"


def test_recent_text_and_tone():
    student = Student(class_id=1, first_name="A", last_name="B")
    assert RegisterRow(student, None).recent_text == ""
    row = RegisterRow(student, None, recent={"absent": 1, "late": 3, "excused": 2})
    assert row.recent_text == "1 absence · 3 late · 2 excused"
    assert row.recent_tone == "warn"
    assert RegisterRow(student, None, recent={"late": 2}).recent_tone == ""
    row = RegisterRow(student, None, recent={"absent": 2}, absent_streak=2)
    assert row.recent_text == "2 absences (2 in a row)"
    assert row.recent_tone == "warn"
    assert RegisterRow(student, None, recent={"absent": 2}, absent_streak=1).recent_text == "2 absences"


def test_absent_streak_counts_registers_missed_in_a_row(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    grace = _student(roster, klass, "Grace", "Hopper")
    days = [school_day(DAY, -n) for n in range(5, -1, -1)]  # Fri 30 Oct .. Fri 6 Nov
    for day in days[:2]:
        attendance.mark(ada, day, A)
    attendance.mark(ada, days[2], P)
    for day in days[3:5]:
        attendance.mark(ada, day, A)
    for day in days:
        attendance.mark(grace, day, P)  # the register was taken every day

    def streak(student_id, day=DAY):
        return next(r for r in attendance.day_register(klass, day).rows if r.student.id == student_id).absent_streak

    assert streak(ada) == 2  # not marked yet today: the run so far still shows
    attendance.mark(ada, DAY, A)
    assert streak(ada) == 3
    assert streak(ada, days[2]) == 0
    assert streak(grace) == 0


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


def test_month_register_keeps_the_notes(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    attendance.mark(ada, date(2026, 10, 1), P)
    attendance.mark(ada, date(2026, 10, 2), E)
    attendance.set_note(ada, date(2026, 10, 2), "Dentist")
    (row,) = attendance.month_register(klass, 2026, 10).rows
    assert row.notes == {date(2026, 10, 2): "Dentist"}


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


def test_period_summary(roster: RosterService, conn: sqlite3.Connection):
    from app.repositories.attendance_repo import AttendanceRepository
    from app.repositories.student_repo import StudentRepository
    from app.repositories.subject_repo import SubjectRepository
    from app.models import AttendanceStatus, SchoolClass, Student

    service = AttendanceService(AttendanceRepository(conn), StudentRepository(conn), SubjectRepository(conn))
    class_id = roster.save_class(SchoolClass(name="7B")).id
    ada = roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace")).id
    alan = roster.save_student(Student(class_id=class_id, first_name="Alan", last_name="Turing")).id
    service.mark(ada, date(2026, 9, 30), AttendanceStatus.ABSENT)  # before the period
    service.mark(ada, date(2026, 10, 1), AttendanceStatus.PRESENT)
    service.mark(ada, date(2026, 10, 2), AttendanceStatus.LATE)
    service.mark(alan, date(2026, 10, 2), AttendanceStatus.ABSENT)

    summary = service.period_summary(class_id, date(2026, 10, 1), date(2026, 10, 31))
    assert summary.recorded_days == 2
    ada_row, alan_row = summary.rows
    assert ada_row.counts == {"present": 1, "absent": 0, "late": 1, "excused": 0}
    assert (ada_row.unmarked, ada_row.rate) == (0, 100)
    assert (alan_row.unmarked, alan_row.rate) == (1, 0)
    with pytest.raises(AttendanceError):
        service.period_summary(class_id, date(2026, 10, 31), date(2026, 10, 1))


def test_note_suggestions_are_the_class_notes_newest_first(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    grace = _student(roster, klass, "Grace", "Hopper")
    other = _student(roster, roster.save_class(SchoolClass(name="8A")).id, "Alan", "Turing")
    for student, day, note in (
        (ada, date(2026, 10, 1), "Dentist"),
        (grace, date(2026, 10, 2), "Bus late"),
        (ada, date(2026, 10, 5), "Bus late"),
        (grace, date(2026, 10, 3), "Dentist"),
        (other, date(2026, 10, 9), "Sports day"),
    ):
        attendance.mark(student, day, L)
        attendance.set_note(student, day, note)
    attendance.mark(ada, date(2026, 10, 6), P)  # no note
    assert attendance.note_suggestions(klass) == [
        "Bus late", "Dentist", "Sick", "Doctor's appointment", "Family reason", "School trip"
    ]  # then the common reasons not written yet ("bus late" is)


def test_copy_from_daily_marks_students_away_all_day(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    grace = _student(roster, klass, "Grace", "Hopper")
    alan = _student(roster, klass, "Alan", "Turing")
    kay = _student(roster, klass, "Kay", "Mauchly")
    maths = roster.list_subjects(klass)[0].id
    attendance.mark(ada, DAY, A)
    attendance.set_note(ada, DAY, "Flu")
    attendance.mark(grace, DAY, E)
    attendance.mark(alan, DAY, L)
    attendance.mark(kay, DAY, A)
    attendance.mark(kay, DAY, P, subject_id=maths)  # already marked in the lesson: kept

    assert attendance.copy_from_daily(klass, DAY, maths) == 2
    rows = {r.student.id: r for r in attendance.day_register(klass, DAY, maths).rows}
    assert (rows[ada].status, rows[ada].note) == (A, "Flu")
    assert rows[grace].status is E
    assert rows[alan].status is None  # late for registration says nothing about the lesson
    assert rows[kay].status is P
    assert attendance.copy_from_daily(klass, DAY, maths) == 0

    with pytest.raises(AttendanceError):
        attendance.copy_from_daily(klass, DAY, None)


def test_school_days_leave_out_weekends():
    assert school_days(DAY, date(2026, 11, 10)) == [DAY, date(2026, 11, 9), date(2026, 11, 10)]
    assert school_days(date(2026, 11, 7), date(2026, 11, 8)) == []
    assert school_days(DAY, date(2026, 11, 5)) == []


def test_mark_days_marks_each_school_day(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    maths = roster.list_subjects(klass)[0].id
    tuesday = date(2026, 11, 10)
    attendance.mark(ada, date(2026, 11, 9), P)
    attendance.set_note(ada, date(2026, 11, 9), "Came in late morning")

    changed = attendance.mark_days(ada, DAY, tuesday, E, " Sick note ")
    assert changed == [DAY, tuesday]  # Monday was marked already: left alone
    history = {r.date: r for r in attendance.student_history(ada).records}
    assert set(history) == {DAY, date(2026, 11, 9), tuesday}  # not the weekend
    assert (history[DAY].status, history[DAY].note) == (E, "Sick note")
    assert history[date(2026, 11, 9)].status is P
    assert attendance.student_history(ada, maths).records == []  # one register at a time

    changed = attendance.mark_days(ada, DAY, tuesday, E, replace_marks=True)
    assert changed == [date(2026, 11, 9)]
    monday = attendance.student_history(ada).records[1]
    assert (monday.status, monday.note) == (E, "Came in late morning")  # no new note: kept


def test_mark_days_refuses_bad_periods(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    with pytest.raises(AttendanceError, match="before the first"):
        attendance.mark_days(ada, DAY, date(2026, 11, 5), A)
    with pytest.raises(AttendanceError, match="weekend"):
        attendance.mark_days(ada, date(2026, 11, 7), date(2026, 11, 8), A)
    with pytest.raises(AttendanceError, match="at most"):
        attendance.mark_days(ada, date(2026, 9, 1), date(2026, 12, 31), A)
    roster.deactivate_student(ada)
    with pytest.raises(AttendanceError, match="inactive"):
        attendance.mark_days(ada, DAY, DAY, A)


def test_days_with_a_mistyped_year_are_refused(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    today = date(2026, 11, 6)
    check_day(date(2027, 11, 6), today)  # a year ahead is still fine
    with pytest.raises(AttendanceError, match="Check the year"):
        check_day(date(2027, 11, 8), today)
    with pytest.raises(AttendanceError, match="Check the year"):
        check_day(date(1926, 11, 6), today)
    with pytest.raises(AttendanceError):
        attendance.mark(ada, date(1926, 11, 6), P)
    with pytest.raises(AttendanceError):
        attendance.mark_unmarked(klass, date(2126, 11, 6))
    with pytest.raises(AttendanceError):
        attendance.mark_days(ada, date(1999, 12, 31), DAY, P)
    assert attendance.student_history(ada).records == []


def test_notes_are_kept_short(attendance, roster, klass):
    from app.services.attendance import NOTE_MAX

    ada = _student(roster, klass, "Ada", "Lovelace")
    attendance.mark(ada, DAY, A)
    attendance.set_note(ada, DAY, "x" * NOTE_MAX + "   ")  # spaces around don't count
    with pytest.raises(AttendanceError, match="at most"):
        attendance.set_note(ada, DAY, "x" * (NOTE_MAX + 1))
    with pytest.raises(AttendanceError, match="at most"):
        attendance.mark_days(ada, DAY, DAY, E, "x" * (NOTE_MAX + 1), replace_marks=True)
    assert attendance.student_history(ada).records[0].note == "x" * NOTE_MAX


def test_number_key_sorts_numbers_as_people_read_them():
    from app.services.attendance import number_key

    students = [Student(class_id=1, first_name=n, last_name="X", student_no=no)
                for n, no in (("a", "S10"), ("b", None), ("c", "s2"), ("d", "S1"), ("e", ""))]  # fmt: skip
    assert [s.first_name for s in sorted(students, key=number_key)] == ["d", "c", "a", "b", "e"]


def test_month_register_counts_days_not_marked(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    grace = _student(roster, klass, "Grace", "Hopper")
    attendance.mark(ada, DAY, P)
    attendance.mark(ada, date(2026, 11, 5), P)
    attendance.mark(grace, DAY, A)
    month = attendance.month_register(klass, 2026, 11)
    rows = {r.student.id: r for r in month.rows}
    assert month.unmarked(rows[ada]) == 0
    assert month.unmarked(rows[grace]) == 1  # the 5th


def test_history_finds_the_current_and_longest_absence_runs(attendance, roster, klass):
    ada = _student(roster, klass, "Ada", "Lovelace")
    marks = [A, A, A, P, A, A, L, A]  # oldest first, on consecutive school days
    for n, status in enumerate(marks):
        attendance.mark(ada, school_day(date(2026, 10, 1), n), status)
    assert attendance.student_history(ada).absence_runs() == (1, 3)
    attendance.mark(ada, school_day(date(2026, 10, 1), len(marks)), A)
    attendance.mark(ada, school_day(date(2026, 10, 1), len(marks) + 1), A)
    assert attendance.student_history(ada).absence_runs() == (3, 3)
    attendance.mark(ada, school_day(date(2026, 10, 1), len(marks) + 2), P)
    assert attendance.student_history(ada).absence_runs() == (0, 3)
