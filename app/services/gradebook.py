"""Grades: categories, assignments and scores of one subject, and the averages they make.

Each subject has its own gradebook. Assignments belong to a weighted category
(e.g. Tests 50, Homework 20); weights are relative, so they needn't add up to 100.
"""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from app.db.connection import transaction
from app.models import Assignment, Category, Student, Subject
from app.repositories.gradebook_repo import GradebookRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository

CATEGORY_NAME_MAX = 40  # characters: "Oral presentations" fits
WEIGHT_MAX = 100.0
TITLE_MAX = 80  # characters in an assignment title
MAX_SCORE_LIMIT = 1000.0  # points: more is surely a typo
EARLIEST_DAY = date(2000, 1, 1)  # before this, the year was surely mistyped
DAYS_AHEAD = 366
OVER_MAX_LIMIT = 2  # a score up to twice the maximum is bonus points; more is a typo
EXEMPT = "exempt"  # score text for an exempt student, stored as NULL
EXEMPT_WORDS = {"ex", "exempt", "x", "excused"}
PASS_MARK = 60.0  # percent: an average under this is failing, as on the dashboard
SUGGESTED_CATEGORIES = (("Tests", 50.0), ("Quizzes", 20.0), ("Homework", 20.0), ("Participation", 10.0))


class GradebookError(ValueError):
    """A user-facing error; the message is safe to show in the UI."""


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else plural or word + 's'}"


def format_number(value: float) -> str:
    """A score or weight as people write it: 8 not 8.0, 8.5, 8.25."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_score(text: str, max_score: float) -> float | str | None:
    """What the teacher typed in a score cell: a number of points ("8", "8,5"), a
    percentage of the maximum ("85%"), EXEMPT ("ex"), or None for an empty cell.
    Raises GradebookError for anything else."""
    text = text.strip().casefold()
    if not text:
        return None
    if text in EXEMPT_WORDS:
        return EXEMPT
    percent = text.endswith("%")
    number = text.removesuffix("%").strip().replace(",", ".")
    try:
        value = float(number)
    except ValueError:
        raise GradebookError(
            f"{text!r} isn't a score. Type the points, e.g. 8.5, a percentage, e.g. 85%, or ex for exempt."
        ) from None
    if value != value or value in (float("inf"), float("-inf")):  # nan, inf
        raise GradebookError(f"{text!r} isn't a score.")
    if percent:
        value = value * max_score / 100
    if value < 0:
        raise GradebookError("A score can't be negative.")
    if value > max_score * OVER_MAX_LIMIT:
        raise GradebookError(
            f"{format_number(value)} is far more than the maximum of {format_number(max_score)}. Check the score."
        )
    return round(value, 2)


def weight_shares(categories: list[Category]) -> dict[int, float]:
    """{category id: percent of the average it makes up}, once every category has work scored."""
    total = sum(c.weight for c in categories)
    return {c.id: 100 * c.weight / total if total else 0.0 for c in categories}


def category_percents(
    assignments: list[Assignment], scores: dict[int, float | None]
) -> dict[int, float]:
    """{category id: percent} for one student, from `scores` {assignment id: score}:
    the points scored over the points possible in each category. Exempt and not yet
    entered assignments don't count; a category with nothing scored is left out."""
    got: dict[int, float] = {}
    possible: dict[int, float] = {}
    for a in assignments:
        score = scores.get(a.id)
        if score is None:
            continue
        got[a.category_id] = got.get(a.category_id, 0) + score
        possible[a.category_id] = possible.get(a.category_id, 0) + a.max_score
    return {c: 100 * got[c] / possible[c] for c in got}


def weighted_average(
    categories: list[Category], assignments: list[Assignment], scores: dict[int, float | None]
) -> float | None:
    """One student's average percent: each category's percent counted by its weight.
    Categories with nothing scored yet are left out and the others' weights stretched
    to make up for them, so an early average isn't dragged down by work not set yet.
    If every category scored has weight 0, they count equally, as on the dashboard.
    None while nothing is scored."""
    percents = category_percents(assignments, scores)
    weights = {c.id: c.weight for c in categories if c.id in percents}
    if not weights:
        return None
    total = sum(weights.values())
    if not total:
        return sum(percents[c] for c in weights) / len(weights)
    return sum(percents[c] * w for c, w in weights.items()) / total


@dataclass
class GradeSheet:
    """One subject's gradebook for its class's active students."""

    subject: Subject
    categories: list[Category]
    assignments: list[Assignment]
    students: list[Student]
    scores: dict[tuple[int, int], float | None] = field(default_factory=dict)  # (assignment, student)

    def is_entered(self, assignment_id: int, student_id: int) -> bool:
        return (assignment_id, student_id) in self.scores

    def score(self, assignment_id: int, student_id: int) -> float | None:
        """The points, or None when exempt or not entered (see is_entered)."""
        return self.scores.get((assignment_id, student_id))

    def student_scores(self, student_id: int) -> dict[int, float | None]:
        return {a: v for (a, s), v in self.scores.items() if s == student_id}

    def average(self, student_id: int) -> float | None:
        return weighted_average(self.categories, self.assignments, self.student_scores(student_id))

    def category_percents(self, student_id: int) -> dict[int, float]:
        return category_percents(self.assignments, self.student_scores(student_id))

    def entered(self, assignment_id: int) -> int:
        """How many of the students listed have a score (or exemption) for the assignment."""
        return sum(self.is_entered(assignment_id, s.id) for s in self.students)

    def assignment_average(self, assignment_id: int) -> float | None:
        """The listed students' mean percent on the assignment; exempt ones left out."""
        assignment = next(a for a in self.assignments if a.id == assignment_id)
        points = [v for s in self.students if (v := self.score(assignment_id, s.id)) is not None]
        return 100 * sum(points) / len(points) / assignment.max_score if points else None

    def class_average(self) -> float | None:
        """The mean of the students' averages, of those who have one."""
        averages = [v for s in self.students if (v := self.average(s.id)) is not None]
        return sum(averages) / len(averages) if averages else None


class GradebookService:
    def __init__(self, gradebook: GradebookRepository, students: StudentRepository, subjects: SubjectRepository):
        self.gradebook = gradebook
        self.students = students
        self.subjects = subjects

    # --- categories ----------------------------------------------------------

    def list_categories(self, subject_id: int) -> list[Category]:
        return self.gradebook.categories(subject_id)

    def save_category(self, category: Category) -> Category:
        """Validate and create (id is None) or update a category."""
        category = replace(category, name=_clean(category.name))
        if not category.name:
            raise GradebookError("Category name is required.")
        if len(category.name) > CATEGORY_NAME_MAX:
            raise GradebookError(
                f"A category name can be at most {CATEGORY_NAME_MAX} characters; this one has {len(category.name)}."
            )
        if not 0 <= category.weight <= WEIGHT_MAX:
            raise GradebookError(f"The weight has to be between 0 and {format_number(WEIGHT_MAX)}.")
        if self.subjects.get(category.subject_id) is None:
            raise GradebookError("The selected subject no longer exists.")
        existing = self.gradebook.find_category(category.subject_id, category.name)
        if existing and existing.id != category.id:
            raise GradebookError(f"This subject already has a category called {existing.name}.")
        if category.id is None:
            return self.gradebook.add_category(category)
        self.gradebook.update_category(category)
        return category

    def add_categories(self, subject_id: int, categories: tuple[tuple[str, float], ...]) -> list[Category]:
        """Add (name, weight) categories the subject doesn't have yet, all or none.
        Returns those added."""
        added = []
        with transaction(self.gradebook.conn):
            for name, weight in categories:
                if self.gradebook.find_category(subject_id, name) is None:
                    added.append(self.save_category(Category(subject_id, name, weight)))
        return added

    def assignment_counts(self, subject_id: int) -> dict[int, int]:
        """{category id: assignments in it}; categories without any are left out."""
        return self.gradebook.assignment_counts(subject_id)

    def delete_category(self, category_id: int) -> None:
        """Delete a category while no assignment uses it."""
        category = self.gradebook.get_category(category_id)
        if category is None:
            return
        used = self.gradebook.assignment_counts(category.subject_id).get(category_id, 0)
        if used:
            them = "it" if used == 1 else "them"
            raise GradebookError(
                f"{category.name} can't be deleted: it has {_plural(used, 'assignment')}. "
                f"Move {them} to another category or delete {them} first."
            )
        self.gradebook.delete_category(category_id)

    # --- assignments ---------------------------------------------------------

    def list_assignments(self, subject_id: int) -> list[Assignment]:
        """By date, undated ones last."""
        return self.gradebook.assignments(subject_id)

    def get_assignment(self, assignment_id: int) -> Assignment | None:
        return self.gradebook.get_assignment(assignment_id)

    def save_assignment(self, assignment: Assignment, today: date | None = None) -> Assignment:
        """Validate and create (id is None) or update an assignment."""
        assignment = replace(assignment, title=_clean(assignment.title))
        if not assignment.title:
            raise GradebookError("Assignment title is required.")
        if len(assignment.title) > TITLE_MAX:
            raise GradebookError(
                f"A title can be at most {TITLE_MAX} characters; this one has {len(assignment.title)}."
            )
        if not 0 < assignment.max_score <= MAX_SCORE_LIMIT:
            raise GradebookError(f"The maximum score has to be more than 0 and at most {format_number(MAX_SCORE_LIMIT)}.")
        category = self.gradebook.get_category(assignment.category_id)
        if category is None or category.subject_id != assignment.subject_id:
            raise GradebookError("Choose one of the subject's categories.")
        if assignment.date is not None:
            today = today or date.today()
            if not EARLIEST_DAY <= assignment.date <= today + timedelta(days=DAYS_AHEAD):
                d = assignment.date
                raise GradebookError(f"{d.day} {d:%B} {d.year} can't be right. Check the year.")
        for other in self.gradebook.assignments(assignment.subject_id):
            if other.id != assignment.id and other.title.casefold() == assignment.title.casefold():
                raise GradebookError(f"This subject already has an assignment called {other.title}.")
        if assignment.id is None:
            return self.gradebook.add_assignment(assignment)
        self.gradebook.update_assignment(assignment)
        return assignment

    def score_count(self, assignment_id: int) -> int:
        """Scores entered for the assignment, exemptions included."""
        return self.gradebook.score_count(assignment_id)

    def delete_assignment(self, assignment_id: int) -> None:
        """Delete an assignment with all its scores."""
        self.gradebook.delete_assignment(assignment_id)

    # --- scores --------------------------------------------------------------

    def enter_score(self, assignment_id: int, student_id: int, text: str) -> float | str | None:
        """Save what was typed in a score cell (see parse_score); returns what was saved:
        the points, EXEMPT, or None when the cell was emptied."""
        assignment = self.gradebook.get_assignment(assignment_id)
        if assignment is None:
            raise GradebookError("This assignment no longer exists.")
        student = self.students.get(student_id)
        subject = self.subjects.get(assignment.subject_id)
        if student is None or subject is None or student.class_id != subject.class_id:
            raise GradebookError("This student isn't in the class any more.")
        value = parse_score(text, assignment.max_score)
        if value is None:
            self.gradebook.clear_score(assignment_id, student_id)
        else:
            self.gradebook.save_score(assignment_id, student_id, None if value == EXEMPT else value)
        return value

    def sheet(self, subject_id: int) -> GradeSheet | None:
        """Everything the gradebook page shows for a subject; None if it no longer exists."""
        subject = self.subjects.get(subject_id)
        if subject is None:
            return None
        students = self.students.list_for_class(subject.class_id)
        listed = {s.id for s in students}
        scores = {key: v for key, v in self.gradebook.scores(subject_id).items() if key[1] in listed}
        return GradeSheet(
            subject, self.gradebook.categories(subject_id), self.gradebook.assignments(subject_id), students, scores
        )

    def enter_scores(self, entries: list[tuple[int, int, str]]) -> int:
        """enter_score() for many (assignment id, student id, text) cells, all or none:
        a problem in any cell raises GradebookError and nothing is saved. Returns how many
        cells were entered."""
        with transaction(self.gradebook.conn):
            for assignment_id, student_id, text in entries:
                try:
                    self.enter_score(assignment_id, student_id, text)
                except GradebookError as exc:
                    student = self.students.get(student_id)
                    assignment = self.gradebook.get_assignment(assignment_id)
                    where = f"{student.full_name}, {assignment.title}: " if student and assignment else ""
                    raise GradebookError(where + str(exc)) from None
        return len(entries)
