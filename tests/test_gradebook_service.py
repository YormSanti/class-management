import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from app.models import Assignment, Category, SchoolClass, Student, Subject
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


@pytest.fixture
def tests_id(grades: GradebookService, subject_id: int) -> int:
    return grades.save_category(Category(subject_id, "Tests", 50)).id


def test_assignment_is_saved_trimmed(grades: GradebookService, subject_id: int, tests_id: int):
    saved = grades.save_assignment(Assignment(subject_id, tests_id, " Test   1 ", 20, date(2026, 10, 1)))
    assert saved.title == "Test 1"
    assert grades.list_assignments(subject_id) == [saved]
    assert grades.get_assignment(saved.id) == saved


@pytest.mark.parametrize(
    "title, max_score, day, message",
    [
        ("", 10, None, "Assignment title is required."),
        ("x" * 81, 10, None, "at most 80 characters"),
        ("Test", 0, None, "more than 0"),
        ("Test", 1001, None, "at most 1000"),
        ("Test", 10, date(1926, 10, 1), "1 October 1926 can't be right"),
        ("Test", 10, date(2028, 10, 1), "can't be right"),
    ],
)
def test_invalid_assignment_is_refused(grades: GradebookService, subject_id, tests_id, title, max_score, day, message):
    with pytest.raises(GradebookError, match=message):
        grades.save_assignment(Assignment(subject_id, tests_id, title, max_score, day), today=date(2026, 11, 24))


def test_assignment_needs_a_category_of_its_subject(
    grades: GradebookService, roster: RosterService, class_id: int, subject_id: int
):
    science = roster.save_subject(Subject(class_id=class_id, name="Science")).id
    labs = grades.save_category(Category(science, "Labs", 40)).id
    with pytest.raises(GradebookError, match="Choose one of the subject's categories."):
        grades.save_assignment(Assignment(subject_id, labs, "Lab 1", 10))


def test_assignment_title_can_be_used_once_per_subject(grades: GradebookService, subject_id, tests_id):
    first = grades.save_assignment(Assignment(subject_id, tests_id, "Test 1", 10))
    with pytest.raises(GradebookError, match="already has an assignment called Test 1"):
        grades.save_assignment(Assignment(subject_id, tests_id, "test 1", 20))
    grades.save_assignment(replace(first, max_score=20))  # its own title is fine


def test_deleting_an_assignment_deletes_its_scores(
    grades: GradebookService, roster: RosterService, class_id, subject_id, tests_id
):
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace")).id
    test = grades.save_assignment(Assignment(subject_id, tests_id, "Test 1", 10)).id
    grades.gradebook.save_score(test, ada, 9)
    assert grades.score_count(test) == 1
    grades.delete_assignment(test)
    assert grades.list_assignments(subject_id) == []
