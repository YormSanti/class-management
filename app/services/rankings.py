"""Rankings: the students of a class in order of their averages, with their places.

How shared places are numbered is a setting (see config.RANKING_METHODS):
"competition" skips places after a tie (1, 2, 2, 4), "dense" doesn't (1, 2, 2, 3).
"""

from dataclasses import dataclass, field

from app.config import RANKING_METHODS
from app.models import Student
from app.services.gradebook import GradebookService

TIE_DECIMALS = 1  # averages equal to this many decimals, as shown, share a place


def rank_places(values: list[float], method: str = "competition") -> list[int]:
    """The place of each of `values` (higher is better), in the same order.
    Values equal when rounded to TIE_DECIMALS share a place."""
    if method not in RANKING_METHODS:
        raise ValueError(f"Unknown ranking method {method!r}")
    keys = [round(v, TIE_DECIMALS) for v in values]
    distinct = sorted(set(keys), reverse=True)
    if method == "dense":
        place_of = {k: i + 1 for i, k in enumerate(distinct)}
    else:
        place_of = {k: 1 + sum(other > k for other in keys) for k in distinct}
    return [place_of[k] for k in keys]


@dataclass
class RankedStudent:
    place: int
    student: Student
    average: float  # percent
    shared: bool = False  # another student has the same place


@dataclass
class Ranking:
    """Students with an average, best first, then those without one yet."""

    ranked: list[RankedStudent] = field(default_factory=list)
    unranked: list[Student] = field(default_factory=list)  # nothing scored yet
    # Overall rankings only: {student id: subjects their average is made of}, and the
    # subjects anyone has an average in.
    subjects_counted: dict[int, int] = field(default_factory=dict)
    subjects: int = 0


def make_ranking(students: list[Student], averages: dict[int, float], method: str = "competition") -> Ranking:
    """Rank `students` by `averages` {student id: percent}; those without one are left
    unranked. Shared places list in name order, as `students` are given."""
    # Sorted as shown, so students sharing a place stay in name order even if their
    # averages differ in a decimal that isn't shown.
    scored = sorted(
        (s for s in students if s.id in averages), key=lambda s: -round(averages[s.id], TIE_DECIMALS)
    )
    places = rank_places([averages[s.id] for s in scored], method)
    ranked = [
        RankedStudent(place, s, averages[s.id], places.count(place) > 1) for place, s in zip(places, scored)
    ]
    return Ranking(ranked, [s for s in students if s.id not in averages])


class RankingService:
    def __init__(self, grades: GradebookService):
        self.grades = grades
        self.method = "competition"  # how shared places are numbered, from Settings

    def subject_ranking(self, subject_id: int) -> Ranking | None:
        """The class's active students by their average in the subject; None if the
        subject no longer exists."""
        sheet = self.grades.sheet(subject_id)
        if sheet is None:
            return None
        averages = {s.id: v for s in sheet.students if (v := sheet.average(s.id)) is not None}
        return make_ranking(sheet.students, averages, self.method)

    def overall_ranking(self, class_id: int) -> Ranking:
        """The class's active students by the mean of their subject averages, as on the
        dashboard. A subject a student has nothing scored in is left out of their mean."""
        per_student: dict[int, list[float]] = {}
        subjects = 0
        for subject in self.grades.subjects.list_for_class(class_id):
            sheet = self.grades.sheet(subject.id)
            averages = {s.id: v for s in sheet.students if (v := sheet.average(s.id)) is not None}
            subjects += bool(averages)
            for student_id, average in averages.items():
                per_student.setdefault(student_id, []).append(average)
        means = {sid: sum(values) / len(values) for sid, values in per_student.items()}
        ranking = make_ranking(self.grades.students.list_for_class(class_id), means, self.method)
        ranking.subjects_counted = {sid: len(values) for sid, values in per_student.items()}
        ranking.subjects = subjects
        return ranking
