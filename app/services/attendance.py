"""Taking attendance: one register per day, either daily (homeroom) or for one subject.

A student with no record for the day is "not marked", which is different from
present: nothing counts until the teacher marks it. Only active students are listed.
"""

import calendar
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from app.models import AttendanceRecord, AttendanceStatus, Student
from app.repositories.attendance_repo import AttendanceRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.dashboard import (
    ABSENCE_LIMIT,
    ATTENTION_WINDOW_DAYS,
    LATE_LIMIT,
    STREAK_LIMIT,
    absent_streak,
    attendance_rate,
)

PRESENT, ABSENT, LATE, EXCUSED = (s.value for s in AttendanceStatus)
UNMARKED = "unmarked"
RECENT_DAYS = ATTENTION_WINDOW_DAYS  # the same window as "Needs attention" on the dashboard
NOTE_SUGGESTIONS = 50
COMMON_NOTES = ("Sick", "Doctor's appointment", "Family reason", "School trip", "Bus late")
NOTE_MAX = 200  # characters: a reason, not a report
MAX_DAYS_AT_ONCE = 70  # school days marked in one go: about a term
LOW_RATE = 90.0  # percent: an attendance rate under this is worth a look
STREAK_SHOWN = STREAK_LIMIT  # absent in this many registers in a row is worth pointing out
EARLIEST_DAY = date(2000, 1, 1)  # before this, the year was surely mistyped
DAYS_AHEAD = 366  # marks further ahead than a year are surely a mistyped year


class AttendanceError(ValueError):
    """A user-facing error; the message is safe to show in the UI."""


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else plural or word + 's'}"


def school_day(day: date, step: int) -> date:
    """The weekday `step` days before (negative) or after `day`, skipping weekends."""
    direction = 1 if step >= 0 else -1
    for _ in range(abs(step)):
        day += timedelta(days=direction)
        while day.weekday() >= 5:
            day += timedelta(days=direction)
    return day


def number_key(student: Student) -> tuple:
    """Sorts students by number as people read them ("S2" before "S10"); those
    without a number come last, in the usual name order."""
    if not student.student_no:
        return (1, ())
    parts = re.split(r"(\d+)", student.student_no.casefold())
    return (0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p))


def _checked_note(note: str) -> str:
    note = note.strip()
    if len(note) > NOTE_MAX:
        raise AttendanceError(f"A note can be at most {NOTE_MAX} characters; this one has {len(note)}.")
    return note


def school_days(start: date, end: date) -> list[date]:
    """The weekdays from `start` to `end`, both included."""
    days = (start + timedelta(days=n) for n in range((end - start).days + 1))
    return [day for day in days if day.weekday() < 5]


def check_day(day: date, today: date | None = None) -> None:
    """Refuse a day whose year was surely mistyped: before 2000 or over a year ahead."""
    today = today or date.today()
    if day < EARLIEST_DAY or day > today + timedelta(days=DAYS_AHEAD):
        raise AttendanceError(f"{day.day} {day:%B} {day.year} can't be right. Check the year.")


def day_warning(day: date, today: date) -> str | None:
    """Why marking `day` may be a mistake: it hasn't happened yet, or it's a weekend."""
    if day > today:
        days = (day - today).days
        when = "tomorrow" if days == 1 else f"in {days} days"
        return f"This day is in the future ({when}). Check the date before marking."
    if day.weekday() >= 5:
        return f"{day:%A} is a weekend day. Check the date before marking."
    return None


@dataclass
class RegisterRow:
    student: Student
    status: AttendanceStatus | None
    note: str = ""
    recent: dict[str, int] = field(default_factory=dict)  # status -> days, in the last RECENT_DAYS
    absent_streak: int = 0  # registers taken in a row, up to the day, in which the student was absent
    previous: tuple[date, AttendanceStatus] | None = None  # the latest mark before the day, in RECENT_DAYS

    @property
    def recent_text(self) -> str:
        """e.g. "3 absences (2 in a row) · 1 late"; "" when the student was always present."""
        parts = []
        if n := self.recent.get(ABSENT, 0):
            streak = f" ({self.absent_streak} in a row)" if self.absent_streak >= STREAK_SHOWN else ""
            parts.append(_plural(n, "absence") + streak)
        if n := self.recent.get(LATE, 0):
            parts.append(f"{n} late")
        if n := self.recent.get(EXCUSED, 0):
            parts.append(f"{n} excused")
        return " · ".join(parts)

    @property
    def recent_tone(self) -> str:
        """"danger" or "warn" at the dashboard's limits, otherwise ""."""
        if self.recent.get(ABSENT, 0) >= ABSENCE_LIMIT:
            return "danger"
        if self.recent.get(LATE, 0) >= LATE_LIMIT or self.absent_streak >= STREAK_SHOWN:
            return "warn"
        return ""


@dataclass
class DayRegister:
    class_id: int
    day: date
    subject_id: int | None
    rows: list[RegisterRow]

    def counts(self) -> dict[str, int]:
        """{status or UNMARKED: number of students}, every key present."""
        counts = {s.value: 0 for s in AttendanceStatus} | {UNMARKED: 0}
        for row in self.rows:
            counts[row.status.value if row.status else UNMARKED] += 1
        return counts

    @property
    def rate(self) -> float | None:
        """Present or late, as a percent of students marked present, late or absent."""
        return attendance_rate(self.counts())


@dataclass
class MonthRow:
    student: Student
    statuses: dict[date, AttendanceStatus] = field(default_factory=dict)
    notes: dict[date, str] = field(default_factory=dict)  # only days with a note

    def counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in AttendanceStatus}
        for status in self.statuses.values():
            counts[status.value] += 1
        return counts

    @property
    def rate(self) -> float | None:
        return attendance_rate(self.counts())


@dataclass
class MonthRegister:
    class_id: int
    year: int
    month: int
    subject_id: int | None
    days: list[date]  # every weekday of the month, plus weekend days with marks
    rows: list[MonthRow]

    @property
    def recorded_days(self) -> list[date]:
        """Days on which at least one student is marked."""
        marked = {day for row in self.rows for day in row.statuses}
        return [day for day in self.days if day in marked]

    def not_taken(self, today: date) -> list[date]:
        """School days up to `today` on which no student is marked: forgotten, or holidays."""
        marked = set(self.recorded_days)
        return [day for day in self.days if day <= today and day.weekday() < 5 and day not in marked]

    def unmarked(self, row: MonthRow) -> int:
        """Days the register was taken on which this student has no mark."""
        return sum(1 for day in self.recorded_days if day not in row.statuses)

    def absent_on(self, day: date) -> int:
        return sum(1 for row in self.rows if row.statuses.get(day) is AttendanceStatus.ABSENT)

    def counts(self) -> dict[str, int]:
        totals = {s.value: 0 for s in AttendanceStatus}
        for row in self.rows:
            for status, n in row.counts().items():
                totals[status] += n
        return totals

    @property
    def rate(self) -> float | None:
        return attendance_rate(self.counts())


@dataclass
class StudentHistory:
    """Every mark of one student in one register, newest first."""

    student: Student
    records: list[AttendanceRecord]

    def counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in AttendanceStatus}
        for record in self.records:
            counts[record.status.value] += 1
        return counts

    @property
    def rate(self) -> float | None:
        return attendance_rate(self.counts())

    @property
    def not_present(self) -> list[AttendanceRecord]:
        """The days the student was absent, late or excused."""
        return [r for r in self.records if r.status is not AttendanceStatus.PRESENT]

    def by_month(self) -> list[tuple[date, dict[str, int]]]:
        """(first day of the month, {status: days}) for each month with marks, newest first."""
        months: dict[date, dict[str, int]] = {}
        for record in self.records:
            counts = months.setdefault(record.date.replace(day=1), {s.value: 0 for s in AttendanceStatus})
            counts[record.status.value] += 1
        return sorted(months.items(), reverse=True)

    def absence_runs(self) -> tuple[int, int]:
        """(current, longest): marks in a row that are absences, the current run ending
        with the newest mark."""
        current = longest = run = 0
        for n, record in enumerate(self.records):  # newest first
            run = run + 1 if record.status is AttendanceStatus.ABSENT else 0
            longest = max(longest, run)
            if run == n + 1:
                current = run
        return current, longest


@dataclass
class PeriodRow:
    student: Student
    counts: dict[str, int]  # status -> days, every status present
    unmarked: int  # recorded days on which this student has no mark

    @property
    def rate(self) -> float | None:
        return attendance_rate(self.counts)


@dataclass
class PeriodSummary:
    """Each active student's totals between two dates, e.g. for a term report."""

    class_id: int
    start: date
    end: date
    subject_id: int | None
    recorded_days: int  # days on which at least one student is marked
    rows: list[PeriodRow]


class AttendanceService:
    def __init__(
        self, attendance: AttendanceRepository, students: StudentRepository, subjects: SubjectRepository
    ):
        self.attendance = attendance
        self.students = students
        self.subjects = subjects

    # --- reading -------------------------------------------------------------

    def day_register(self, class_id: int, day: date, subject_id: int | None = None) -> DayRegister:
        """Every active student with their status on `day`, sorted by name."""
        self._check_subject(class_id, subject_id)
        records = {r.student_id: r for r in self.attendance.for_period(class_id, day, day, subject_id)}
        window = self.attendance.for_period(class_id, day - timedelta(days=RECENT_DAYS - 1), day, subject_id)
        recent: dict[int, dict[str, int]] = {}
        marks: dict[int, dict[date, AttendanceStatus]] = {}
        for r in window:
            counts = recent.setdefault(r.student_id, {})
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
            marks.setdefault(r.student_id, {})[r.date] = r.status
        taken = sorted({r.date for r in window}, reverse=True)
        rows = []
        for student in self.students.list_for_class(class_id):
            record = records.get(student.id)
            rows.append(
                RegisterRow(
                    student=student,
                    status=record.status if record else None,
                    note=record.note if record else "",
                    recent=recent.get(student.id, {}),
                    absent_streak=absent_streak(marks.get(student.id, {}), taken),
                    previous=max(((d, st) for d, st in marks.get(student.id, {}).items() if d < day), default=None),
                )
            )
        return DayRegister(class_id, day, subject_id, rows)

    def month_register(
        self, class_id: int, year: int, month: int, subject_id: int | None = None
    ) -> MonthRegister:
        """Every active student's marks for one month, sorted by name."""
        self._check_subject(class_id, subject_id)
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        records = self.attendance.for_period(class_id, first, last, subject_id)
        by_student: dict[int, dict[date, AttendanceStatus]] = {}
        notes: dict[int, dict[date, str]] = {}
        for r in records:
            by_student.setdefault(r.student_id, {})[r.date] = r.status
            if r.note:
                notes.setdefault(r.student_id, {})[r.date] = r.note
        marked_days = {r.date for r in records}
        month_days = [first + timedelta(days=n) for n in range(last.day)]
        days = [day for day in month_days if day.weekday() < 5 or day in marked_days]
        rows = [
            MonthRow(s, by_student.get(s.id, {}), notes.get(s.id, {}))
            for s in self.students.list_for_class(class_id)
        ]
        return MonthRegister(class_id, year, month, subject_id, days, rows)

    def period_summary(
        self, class_id: int, start: date, end: date, subject_id: int | None = None
    ) -> PeriodSummary:
        """Totals per active student for the days from `start` to `end`, both included."""
        if end < start:
            raise AttendanceError("The end date is before the start date.")
        self._check_subject(class_id, subject_id)
        records = self.attendance.for_period(class_id, start, end, subject_id)
        recorded = len({r.date for r in records})
        by_student: dict[int, dict[str, int]] = {}
        for r in records:
            counts = by_student.setdefault(r.student_id, {s.value: 0 for s in AttendanceStatus})
            counts[r.status.value] += 1
        rows = []
        for student in self.students.list_for_class(class_id):
            counts = by_student.get(student.id, {s.value: 0 for s in AttendanceStatus})
            rows.append(PeriodRow(student, counts, recorded - sum(counts.values())))
        return PeriodSummary(class_id, start, end, subject_id, recorded, rows)

    def student_history(self, student_id: int, subject_id: int | None = None) -> StudentHistory:
        student = self.students.get(student_id)
        if student is None:
            raise AttendanceError("That student no longer exists.")
        self._check_subject(student.class_id, subject_id)
        return StudentHistory(student, self.attendance.for_student(student_id, subject_id))

    def note_suggestions(self, class_id: int) -> list[str]:
        """Notes already written in this class, newest first, to offer while typing one,
        then the common reasons not written yet, so a new class has some to start with."""
        written = self.attendance.recent_notes(class_id, NOTE_SUGGESTIONS)
        known = {note.casefold() for note in written}
        return written + [note for note in COMMON_NOTES if note.casefold() not in known]

    # --- marking -------------------------------------------------------------

    def mark(
        self, student_id: int, day: date, status: AttendanceStatus, subject_id: int | None = None
    ) -> None:
        """Set the student's status for the day, keeping any note already written."""
        check_day(day)
        self._check_student(student_id, subject_id)
        existing = self.attendance.get(student_id, day, subject_id)
        record = (
            replace(existing, status=AttendanceStatus(status))
            if existing
            else AttendanceRecord(student_id, day, AttendanceStatus(status), subject_id=subject_id)
        )
        self.attendance.save(record)

    def clear(self, student_id: int, day: date, subject_id: int | None = None) -> None:
        """Make the student "not marked" again; the day's note goes with the record."""
        student = self.students.get(student_id)
        if student is None:
            raise AttendanceError("That student no longer exists.")
        self._check_subject(student.class_id, subject_id)
        self.attendance.delete(student_id, day, subject_id)

    def set_note(self, student_id: int, day: date, note: str, subject_id: int | None = None) -> None:
        """Write the note of the student's mark for the day; the same checks as mark()."""
        self._check_student(student_id, subject_id)
        existing = self.attendance.get(student_id, day, subject_id)
        if existing is None:
            raise AttendanceError("Mark the student before adding a note.")
        self.attendance.save(replace(existing, note=_checked_note(note)))

    def mark_days(
        self,
        student_id: int,
        start: date,
        end: date,
        status: AttendanceStatus,
        note: str = "",
        subject_id: int | None = None,
        replace_marks: bool = False,
    ) -> list[date]:
        """Mark the student on every school day from `start` to `end`, e.g. for a sick note.

        Days the student is already marked are left alone unless `replace_marks`; a
        replaced mark keeps its note when no new one is given. Returns the days changed.
        """
        if end < start:
            raise AttendanceError("The last day is before the first.")
        check_day(start)
        check_day(end)
        days = school_days(start, end)
        if not days:
            raise AttendanceError("There are no school days between these dates, only a weekend.")
        if len(days) > MAX_DAYS_AT_ONCE:
            raise AttendanceError(
                f"That is {len(days)} school days. Mark at most {MAX_DAYS_AT_ONCE} at once, about a term."
            )
        self._check_student(student_id, subject_id)
        status, note = AttendanceStatus(status), _checked_note(note)
        records = []
        for day in days:
            existing = self.attendance.get(student_id, day, subject_id)
            if existing is None:
                records.append(AttendanceRecord(student_id, day, status, note, subject_id))
            elif replace_marks and (existing.status, existing.note) != (status, note or existing.note):
                records.append(replace(existing, status=status, note=note or existing.note))
        self.attendance.save_many(records)
        return [r.date for r in records]

    def mark_unmarked(
        self,
        class_id: int,
        day: date,
        subject_id: int | None = None,
        status: AttendanceStatus = AttendanceStatus.PRESENT,
    ) -> int:
        """Give every student who is not marked yet `status`; returns how many."""
        check_day(day)
        register = self.day_register(class_id, day, subject_id)
        records = [
            AttendanceRecord(row.student.id, day, AttendanceStatus(status), subject_id=subject_id)
            for row in register.rows
            if row.status is None
        ]
        self.attendance.save_many(records)
        return len(records)

    def copy_from_daily(self, class_id: int, day: date, subject_id: int) -> int:
        """Mark students who are away all day in this subject's register too; returns how many.

        Students absent or excused in the daily register get the same status and note,
        when they aren't marked in the subject yet. Late isn't copied: being late for
        registration says nothing about a lesson later in the day.
        """
        check_day(day)
        records = self.daily_to_copy(class_id, day, subject_id)
        self.attendance.save_many(records)
        return len(records)

    def daily_to_copy(self, class_id: int, day: date, subject_id: int) -> list[AttendanceRecord]:
        """The marks copy_from_daily() would add, without adding them."""
        if subject_id is None:
            raise AttendanceError("Pick a subject register to copy the daily register into.")
        daily = {row.student.id: row for row in self.day_register(class_id, day).rows}
        records = []
        for row in self.day_register(class_id, day, subject_id).rows:
            source = daily.get(row.student.id)
            if row.status is None and source and source.status in (AttendanceStatus.ABSENT, AttendanceStatus.EXCUSED):
                records.append(AttendanceRecord(row.student.id, day, source.status, source.note, subject_id))
        return records

    def clear_day(self, class_id: int, day: date, subject_id: int | None = None) -> int:
        """Remove the whole register for the day, notes included; returns how many."""
        self._check_subject(class_id, subject_id)
        return self.attendance.delete_day(class_id, day, subject_id)

    # --- undo ----------------------------------------------------------------

    def snapshot(self, class_id: int, day: date, subject_id: int | None = None) -> list[AttendanceRecord]:
        """The day's register as it is now, to hand back to restore() for undo."""
        self._check_subject(class_id, subject_id)
        return self.attendance.for_period(class_id, day, day, subject_id)

    def restore(
        self, class_id: int, day: date, subject_id: int | None, records: list[AttendanceRecord]
    ) -> None:
        """Put the day's register back to a snapshot: marks and notes made since are undone."""
        self._check_subject(class_id, subject_id)
        self.attendance.replace_day(class_id, day, subject_id, records)

    # --- checks --------------------------------------------------------------

    def _check_subject(self, class_id: int, subject_id: int | None) -> None:
        if subject_id is None:
            return
        subject = self.subjects.get(subject_id)
        if subject is None or subject.class_id != class_id:
            raise AttendanceError("That subject doesn't belong to this class.")

    def _check_student(self, student_id: int, subject_id: int | None) -> None:
        student = self.students.get(student_id)
        if student is None:
            raise AttendanceError("That student no longer exists.")
        if not student.active:
            raise AttendanceError(f"{student.full_name} is inactive. Reactivate them to take attendance.")
        self._check_subject(student.class_id, subject_id)
