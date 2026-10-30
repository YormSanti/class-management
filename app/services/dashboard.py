"""Overview numbers for one class: attendance, grades and students who need a look.

Inactive students are left out of every figure. Scores that are NULL (not submitted
or exempt) are ignored in averages, unlike a score of 0.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models import AttendanceStatus, Student
from app.repositories.dashboard_repo import AssignmentStats, CategoryPoints, DashboardRepository
from app.repositories.student_repo import StudentRepository

# Lower bound (percent) of each letter grade, best first.
GRADE_SCALE: tuple[tuple[str, float], ...] = (("A", 90), ("B", 80), ("C", 70), ("D", 60), ("F", 0))

CHART_DAYS = 10
RECENT_ASSIGNMENTS = 5
ATTENTION_WINDOW_DAYS = 30
ABSENCE_LIMIT = 3
LATE_LIMIT = 3
MISSING_LIMIT = 2
LOW_AVERAGE = 60.0

PRESENT, ABSENT, LATE, EXCUSED = (s.value for s in AttendanceStatus)


@dataclass
class DayAttendance:
    day: date
    counts: dict[str, int]  # status value -> number of students


@dataclass
class AttentionItem:
    student: Student
    kind: str  # "absent", "grades", "missing" or "late"
    reason: str


@dataclass
class DashboardSummary:
    active_students: int
    inactive_students: int
    week_rate: float | None  # percent; None when nothing was recorded
    previous_week_rate: float | None
    class_average: float | None
    missing_total: int
    attendance_days: list[DayAttendance] = field(default_factory=list)
    attention: list[AttentionItem] = field(default_factory=list)
    recent_assignments: list[AssignmentStats] = field(default_factory=list)
    grade_distribution: dict[str, int] = field(default_factory=dict)


def letter_grade(percent: float) -> str:
    for letter, lower in GRADE_SCALE:
        if percent >= lower:
            return letter
    return GRADE_SCALE[-1][0]


def attendance_rate(counts: dict[str, int]) -> float | None:
    """Present or late, as a percent of marked days. Excused days don't count either way."""
    attended = counts.get(PRESENT, 0) + counts.get(LATE, 0)
    marked = attended + counts.get(ABSENT, 0)
    return attended * 100 / marked if marked else None


def weighted_averages(points: list[CategoryPoints]) -> dict[int, float]:
    """{student_id: percent} weighted by category, over the categories the student has scores in.

    If all of those categories have weight 0, the categories count equally.
    """
    by_student: dict[int, list[CategoryPoints]] = {}
    for p in points:
        if p.possible > 0:
            by_student.setdefault(p.student_id, []).append(p)

    averages = {}
    for student_id, cats in by_student.items():
        total_weight = sum(c.weight for c in cats)
        if total_weight > 0:
            averages[student_id] = sum(c.earned / c.possible * c.weight for c in cats) * 100 / total_weight
        else:
            averages[student_id] = sum(c.earned / c.possible for c in cats) * 100 / len(cats)
    return averages


def _sum_counts(days: list[dict[str, int]]) -> dict[str, int]:
    total: dict[str, int] = {}
    for counts in days:
        for status, n in counts.items():
            total[status] = total.get(status, 0) + n
    return total


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class DashboardService:
    def __init__(self, dashboard: DashboardRepository, students: StudentRepository):
        self.dashboard = dashboard
        self.students = students

    def summary(self, class_id: int, today: date | None = None) -> DashboardSummary:
        today = today or date.today()
        active, inactive = self.dashboard.count_students(class_id)

        week_start = today - timedelta(days=today.weekday())
        by_date = self.dashboard.attendance_by_date(class_id, week_start - timedelta(days=7), today)
        this_week = [c for d, c in by_date.items() if d >= week_start]
        last_week = [c for d, c in by_date.items() if d < week_start]

        chart_dates = self.dashboard.recent_attendance_dates(class_id, today, CHART_DAYS)
        chart_counts = (
            self.dashboard.attendance_by_date(class_id, chart_dates[0], chart_dates[-1])
            if chart_dates
            else {}
        )

        averages = weighted_averages(self.dashboard.category_points(class_id))
        missing = self.dashboard.missing_by_student(class_id, today)

        distribution = {letter: 0 for letter, _ in GRADE_SCALE}
        for percent in averages.values():
            distribution[letter_grade(percent)] += 1

        return DashboardSummary(
            active_students=active,
            inactive_students=inactive,
            week_rate=attendance_rate(_sum_counts(this_week)),
            previous_week_rate=attendance_rate(_sum_counts(last_week)),
            class_average=sum(averages.values()) / len(averages) if averages else None,
            missing_total=sum(missing.values()),
            attendance_days=[DayAttendance(d, chart_counts.get(d, {})) for d in chart_dates],
            attention=self._needs_attention(class_id, today, averages, missing),
            recent_assignments=self.dashboard.recent_assignments(class_id, RECENT_ASSIGNMENTS),
            grade_distribution=distribution,
        )

    def _needs_attention(
        self, class_id: int, today: date, averages: dict[int, float], missing: dict[int, int]
    ) -> list[AttentionItem]:
        """One item per student, using the most serious reason. Most serious first."""
        window_start = today - timedelta(days=ATTENTION_WINDOW_DAYS - 1)
        attendance = self.dashboard.attendance_by_student(class_id, window_start, today)
        window = f"in the last {ATTENTION_WINDOW_DAYS} days"

        items: list[tuple[int, AttentionItem]] = []
        for student in self.students.list_for_class(class_id):
            counts = attendance.get(student.id, {})
            average = averages.get(student.id)
            checks = [
                ("absent", counts.get(ABSENT, 0) >= ABSENCE_LIMIT,
                 f"{_plural(counts.get(ABSENT, 0), 'absence')} {window}"),
                ("grades", average is not None and average < LOW_AVERAGE,
                 f"Average is {average or 0:.0f}%"),
                ("missing", missing.get(student.id, 0) >= MISSING_LIMIT,
                 f"{_plural(missing.get(student.id, 0), 'missing assignment')}"),
                ("late", counts.get(LATE, 0) >= LATE_LIMIT,
                 f"Late {counts.get(LATE, 0)} times {window}"),
            ]  # fmt: skip
            for priority, (kind, hit, reason) in enumerate(checks):
                if hit:
                    items.append((priority, AttentionItem(student, kind, reason)))
                    break
        # list_for_class is already sorted by name, and sort() is stable.
        items.sort(key=lambda item: item[0])
        return [item for _, item in items]
