"""Grades: categories, assignments and scores of one subject, and the averages they make.

Each subject has its own gradebook. Assignments belong to a weighted category
(e.g. Tests 50, Homework 20); weights are relative, so they needn't add up to 100.
"""

from dataclasses import replace

from app.models import Category
from app.repositories.gradebook_repo import GradebookRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository

CATEGORY_NAME_MAX = 40  # characters: "Oral presentations" fits
WEIGHT_MAX = 100.0


class GradebookError(ValueError):
    """A user-facing error; the message is safe to show in the UI."""


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else plural or word + 's'}"


def format_number(value: float) -> str:
    """A score or weight as people write it: 8 not 8.0, 8.5, 8.25."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


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
