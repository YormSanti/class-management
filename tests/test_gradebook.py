import sqlite3

import pytest

from app.models import Category, SchoolClass, Subject
from app.repositories.gradebook_repo import GradebookRepository
from app.services.roster import RosterService


@pytest.fixture
def subject_id(roster: RosterService) -> int:
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    return roster.save_subject(Subject(class_id=class_id, name="Maths")).id


@pytest.fixture
def repo(conn: sqlite3.Connection) -> GradebookRepository:
    return GradebookRepository(conn)


def test_categories_are_listed_heaviest_first(repo: GradebookRepository, subject_id: int):
    repo.add_category(Category(subject_id, "Homework", 20))
    tests = repo.add_category(Category(subject_id, "Tests", 50))
    assert [c.name for c in repo.categories(subject_id)] == ["Tests", "Homework"]
    assert repo.get_category(tests.id) == tests


def test_category_can_be_renamed_and_reweighted(repo: GradebookRepository, subject_id: int):
    quizzes = repo.add_category(Category(subject_id, "Quizes", 10))
    repo.update_category(Category(subject_id, "Quizzes", 30, id=quizzes.id))
    assert repo.get_category(quizzes.id).name == "Quizzes"
    assert repo.get_category(quizzes.id).weight == 30


def test_category_is_found_ignoring_case(repo: GradebookRepository, subject_id: int):
    tests = repo.add_category(Category(subject_id, "Tests", 50))
    assert repo.find_category(subject_id, "tests") == tests
    assert repo.find_category(subject_id, "Quizzes") is None


def test_category_name_is_unique_per_subject(repo: GradebookRepository, subject_id: int):
    repo.add_category(Category(subject_id, "Tests", 50))
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_category(Category(subject_id, "Tests", 10))


def test_unused_category_can_be_deleted(repo: GradebookRepository, subject_id: int):
    tests = repo.add_category(Category(subject_id, "Tests", 50))
    repo.delete_category(tests.id)
    assert repo.categories(subject_id) == []
