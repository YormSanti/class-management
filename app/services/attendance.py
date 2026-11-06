"""Taking attendance: one register per day, either daily (homeroom) or for one subject.

A student with no record for the day is "not marked", which is different from
present: nothing counts until the teacher marks it. Only active students are listed.
"""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from app.models import AttendanceRecord, AttendanceStatus, Student
from app.repositories.attendance_repo import AttendanceRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.dashboard import ABSENCE_LIMIT, ATTENTION_WINDOW_DAYS, LATE_LIMIT, attendance_rate

PRESENT, ABSENT, LATE, EXCUSED = (s.value for s in AttendanceStatus)
UNMARKED = "unmarked"
RECENT_DAYS = ATTENTION_WINDOW_DAYS  # the same window as "Needs attention" on the dashboard


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


@dataclass
class RegisterRow:
    student: Student
    status: AttendanceStatus | None
    note: str = ""
    recent: dict[str, int] = field(default_factory=dict)  # status -> days, in the last RECENT_DAYS

    @property
    def recent_text(self) -> str:
        """e.g. "3 absences · 1 late"; "" when the student was always present."""
        parts = []
        if n := self.recent.get(ABSENT, 0):
            parts.append(_plural(n, "absence"))
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
        if self.recent.get(LATE, 0) >= LATE_LIMIT:
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
        recent = self.attendance.counts_by_student(
            class_id, day - timedelta(days=RECENT_DAYS - 1), day, subject_id
        )
        rows = []
        for student in self.students.list_for_class(class_id):
            record = records.get(student.id)
            rows.append(
                RegisterRow(
                    student=student,
                    status=record.status if record else None,
                    note=record.note if record else "",
                    recent=recent.get(student.id, {}),
                )
            )
        return DayRegister(class_id, day, subject_id, rows)

    # --- marking -------------------------------------------------------------

    def mark(
        self, student_id: int, day: date, status: AttendanceStatus, subject_id: int | None = None
    ) -> None:
        """Set the student's status for the day, keeping any note already written."""
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
        self.attendance.delete(student_id, day, subject_id)

    def set_note(self, student_id: int, day: date, note: str, subject_id: int | None = None) -> None:
        existing = self.attendance.get(student_id, day, subject_id)
        if existing is None:
            raise AttendanceError("Mark the student before adding a note.")
        self.attendance.save(replace(existing, note=note.strip()))

    def mark_unmarked(
        self,
        class_id: int,
        day: date,
        subject_id: int | None = None,
        status: AttendanceStatus = AttendanceStatus.PRESENT,
    ) -> int:
        """Give every student who is not marked yet `status`; returns how many."""
        register = self.day_register(class_id, day, subject_id)
        records = [
            AttendanceRecord(row.student.id, day, AttendanceStatus(status), subject_id=subject_id)
            for row in register.rows
            if row.status is None
        ]
        self.attendance.save_many(records)
        return len(records)

    def clear_day(self, class_id: int, day: date, subject_id: int | None = None) -> int:
        """Remove the whole register for the day, notes included; returns how many."""
        self._check_subject(class_id, subject_id)
        return self.attendance.delete_day(class_id, day, subject_id)

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
