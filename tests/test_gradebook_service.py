import sqlite3

import pytest

from app.models import Assignment, Category, SchoolClass, Subject
from app.repositories.gradebook_repo import GradebookRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.gradebook import GradebookError, GradebookService, format_number
from app.services.roster import RosterService


@pytest.fixture
def grades(conn: sqlite3.Connection) -> GradebookService:
    return GradebookService(GradebookRepository(conn), StudentRepository(conn), SubjectRepository(conn))


@pytest.fixture
def class_id(roster: RosterService) -> int:
    return roster.save_class(SchoolClass(name="7B", term="2026-2027")).id


@pytest.fixture
def subject_id(roster: RosterService, class_id: int) -> int:
    return roster.save_subject(Subject(class_id=class_id, name="Maths")).id


def test_numbers_are_written_without_needless_decimals():
    assert [format_number(x) for x in (8.0, 8.5, 8.25, 8.126, 0)] == ["8", "8.5", "8.25", "8.13", "0"]


def test_category_is_saved_trimmed(grades: GradebookService, subject_id: int):
    saved = grades.save_category(Category(subject_id, "  Oral   tests ", 30))
    assert saved.name == "Oral tests"
    assert grades.list_categories(subject_id) == [saved]


@pytest.mark.parametrize(
    "name, weight, message",
    [
        (" ", 10, "Category name is required."),
        ("x" * 41, 10, "at most 40 characters"),
        ("Tests", -1, "between 0 and 100"),
        ("Tests", 101, "between 0 and 100"),
    ],
)
def test_invalid_category_is_refused(grades: GradebookService, subject_id: int, name, weight, message):
    with pytest.raises(GradebookError, match=message):
        grades.save_category(Category(subject_id, name, weight))


def test_category_name_can_be_used_once_per_subject(grades: GradebookService, subject_id: int):
    tests = grades.save_category(Category(subject_id, "Tests", 50))
    with pytest.raises(GradebookError, match="already has a category called Tests"):
        grades.save_category(Category(subject_id, "tests", 10))
    grades.save_category(Category(subject_id, "TESTS", 60, id=tests.id))  # its own name is fine


def test_category_with_assignments_cannot_be_deleted(grades: GradebookService, subject_id: int):
    tests = grades.save_category(Category(subject_id, "Tests", 50))
    grades.gradebook.add_assignment(Assignment(subject_id, tests.id, "Test 1", 10))
    with pytest.raises(GradebookError, match="Tests can't be deleted: it has 1 assignment"):
        grades.delete_category(tests.id)
    empty = grades.save_category(Category(subject_id, "Quizzes", 10))
    grades.delete_category(empty.id)
    assert [c.name for c in grades.list_categories(subject_id)] == ["Tests"]
