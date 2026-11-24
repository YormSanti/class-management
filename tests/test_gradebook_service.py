import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from app.models import Assignment, Category, SchoolClass, Student, Subject
from app.repositories.gradebook_repo import GradebookRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.gradebook import EXEMPT, SUGGESTED_CATEGORIES, GradebookError, GradebookService, format_number, parse_score, weight_shares, weighted_average
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


@pytest.mark.parametrize(
    "text, expected",
    [("", None), ("  ", None), ("8", 8), ("8,5", 8.5), (" 7.25 ", 7.25), ("85%", 17), ("ex", EXEMPT),
     ("X", EXEMPT), ("Excused", EXEMPT), ("0", 0), ("25", 25), ("40", 40)],
)
def test_typed_scores_are_read(text, expected):
    assert parse_score(text, 20) == expected


@pytest.mark.parametrize("text, message", [("abc", "isn't a score"), ("nan", "isn't a score"),
                                           ("-1", "can't be negative"), ("41", "far more than the maximum of 20")])
def test_impossible_scores_are_refused(text, message):
    with pytest.raises(GradebookError, match=message):
        parse_score(text, 20)


def test_score_is_entered_exempted_and_cleared(
    grades: GradebookService, roster: RosterService, class_id, subject_id, tests_id
):
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace")).id
    test = grades.save_assignment(Assignment(subject_id, tests_id, "Test 1", 10)).id
    assert grades.enter_score(test, ada, "8,5") == 8.5
    assert grades.gradebook.scores(subject_id) == {(test, ada): 8.5}
    assert grades.enter_score(test, ada, "ex") == EXEMPT
    assert grades.gradebook.scores(subject_id) == {(test, ada): None}
    assert grades.enter_score(test, ada, "") is None
    assert grades.gradebook.scores(subject_id) == {}


def test_score_of_a_student_of_another_class_is_refused(
    grades: GradebookService, roster: RosterService, subject_id, tests_id
):
    other = roster.save_class(SchoolClass(name="7C", term="2026-2027")).id
    bob = roster.save_student(Student(other, "Bob", "Smith")).id
    test = grades.save_assignment(Assignment(subject_id, tests_id, "Test 1", 10)).id
    with pytest.raises(GradebookError, match="isn't in the class"):
        grades.enter_score(test, bob, "5")


def _book():
    tests, homework, extra = Category(1, "Tests", 60, id=1), Category(1, "Homework", 40, id=2), Category(1, "Extra", 0, id=3)
    assignments = [Assignment(1, 1, "T1", 20, id=10), Assignment(1, 1, "T2", 30, id=11),
                   Assignment(1, 2, "H1", 10, id=20), Assignment(1, 3, "Bonus", 10, id=30)]  # fmt: skip
    return [tests, homework, extra], assignments


def test_average_weighs_each_category_by_its_points():
    categories, assignments = _book()
    # Tests: (10 + 30) / 50 = 80 %, Homework 5 / 10 = 50 %; 0.6 * 80 + 0.4 * 50 = 68
    assert weighted_average(categories, assignments, {10: 10, 11: 30, 20: 5, 30: 0}) == pytest.approx(68)


def test_average_leaves_out_exempt_unentered_and_unweighted_work():
    categories, assignments = _book()
    assert weighted_average(categories, assignments, {10: 15, 11: None}) == pytest.approx(75)  # Tests only
    assert weighted_average(categories, assignments, {30: 10}) is None  # weight 0 doesn't count
    assert weighted_average(categories, assignments, {}) is None


def test_sheet_lists_active_students_with_their_averages(
    grades: GradebookService, roster: RosterService, class_id, subject_id, tests_id
):
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace")).id
    bob = roster.save_student(Student(class_id, "Bob", "Smith")).id
    gone = roster.save_student(Student(class_id, "Cy", "Old")).id
    t1 = grades.save_assignment(Assignment(subject_id, tests_id, "Test 1", 10)).id
    t2 = grades.save_assignment(Assignment(subject_id, tests_id, "Test 2", 10)).id
    grades.enter_score(t1, ada, "8")
    grades.enter_score(t2, ada, "ex")
    grades.enter_score(t1, bob, "6")
    grades.enter_score(t1, gone, "1")
    roster.deactivate_student(gone)

    sheet = grades.sheet(subject_id)
    assert [s.first_name for s in sheet.students] == ["Ada", "Bob"]
    assert [a.title for a in sheet.assignments] == ["Test 1", "Test 2"]
    assert sheet.is_entered(t2, ada) and sheet.score(t2, ada) is None
    assert not sheet.is_entered(t2, bob)
    assert sheet.average(ada) == pytest.approx(80)
    assert sheet.category_percents(bob) == {tests_id: pytest.approx(60)}
    assert sheet.entered(t1) == 2 and sheet.entered(t2) == 1
    assert sheet.assignment_average(t1) == pytest.approx(70)  # the inactive student is left out
    assert sheet.assignment_average(t2) is None
    assert sheet.class_average() == pytest.approx(70)


def test_sheet_of_a_deleted_subject_is_none(grades: GradebookService):
    assert grades.sheet(999) is None


def test_weights_are_shown_as_shares_of_the_average():
    categories, _ = _book()
    assert weight_shares(categories) == {1: 60, 2: 40, 3: 0}
    assert weight_shares([Category(1, "A", 0, id=1)]) == {1: 0}


def test_suggested_categories_are_added_once(grades: GradebookService, subject_id: int):
    grades.save_category(Category(subject_id, "tests", 70))
    added = grades.add_categories(subject_id, SUGGESTED_CATEGORIES)
    assert [c.name for c in added] == ["Quizzes", "Homework", "Participation"]
    assert grades.add_categories(subject_id, SUGGESTED_CATEGORIES) == []
    assert len(grades.list_categories(subject_id)) == 4
