import sqlite3

import pytest

from app.models import Assignment, Category, SchoolClass, Student, Subject
from app.repositories.gradebook_repo import GradebookRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.gradebook import GradebookService
from app.services.rankings import RankingService, make_ranking, rank_places
from app.services.roster import RosterService


def test_competition_places_skip_after_a_tie():
    assert rank_places([90, 80, 80, 70]) == [1, 2, 2, 4]


def test_dense_places_do_not_skip():
    assert rank_places([90, 80, 80, 70], "dense") == [1, 2, 2, 3]


def test_places_follow_the_order_given():
    assert rank_places([70, 90, 80]) == [3, 1, 2]


def test_averages_equal_as_shown_share_a_place():
    assert rank_places([83.33333, 83.32999, 83.2]) == [1, 1, 3]


def test_students_sharing_a_place_are_listed_by_name():
    ada, bob, cy = (Student(1, first, "Pupil", id=i) for i, first in enumerate(("Ada", "Bob", "Cy"), 1))
    # Bob is 0.08 ahead, but both show as 85.0%, so the two share 1st place in name order.
    ranking = make_ranking([ada, bob, cy], {ada.id: 84.96, bob.id: 85.04, cy.id: 70})
    assert [(r.place, r.student.first_name, r.shared) for r in ranking.ranked] == [
        (1, "Ada", True),
        (1, "Bob", True),
        (3, "Cy", False),
    ]


def test_everyone_tied_is_first():
    assert rank_places([50, 50, 50], "dense") == [1, 1, 1]
    assert rank_places([50, 50, 50]) == [1, 1, 1]


def test_nothing_to_rank():
    assert rank_places([]) == []


def test_unknown_method_is_refused():
    with pytest.raises(ValueError):
        rank_places([1], "olympic")


@pytest.fixture
def grades(conn: sqlite3.Connection) -> GradebookService:
    return GradebookService(GradebookRepository(conn), StudentRepository(conn), SubjectRepository(conn))


@pytest.fixture
def rankings(grades: GradebookService) -> RankingService:
    return RankingService(grades)


def _class(roster: RosterService, *names: str) -> tuple[int, list[Student]]:
    class_id = roster.save_class(SchoolClass(name="7B", term="2026-2027")).id
    return class_id, [roster.save_student(Student(class_id, first, "Pupil")) for first in names]


def _subject(roster: RosterService, grades: GradebookService, class_id: int, name: str) -> tuple[int, int]:
    """A subject with one Tests category and a test out of 10; returns (subject id, test id)."""
    subject_id = roster.save_subject(Subject(class_id=class_id, name=name)).id
    tests = grades.save_category(Category(subject_id, "Tests", 50))
    test = grades.save_assignment(Assignment(subject_id, tests.id, "Test 1", 10))
    return subject_id, test.id


def test_subject_ranking_lists_best_average_first(
    roster: RosterService, grades: GradebookService, rankings: RankingService
):
    class_id, (ada, ben, cy, dee) = _class(roster, "Ada", "Ben", "Cy", "Dee")
    maths, test = _subject(roster, grades, class_id, "Maths")
    grades.enter_scores([(test, ada.id, "7"), (test, ben.id, "9"), (test, cy.id, "7"), (test, dee.id, "ex")])
    ranking = rankings.subject_ranking(maths)
    assert [(r.place, r.student.first_name, r.average, r.shared) for r in ranking.ranked] == [
        (1, "Ben", 90, False),
        (2, "Ada", 70, True),
        (2, "Cy", 70, True),
    ]
    assert [s.first_name for s in ranking.unranked] == ["Dee"]


def test_subject_ranking_numbers_places_as_set(roster: RosterService, grades: GradebookService, rankings: RankingService):
    class_id, (ada, ben, cy) = _class(roster, "Ada", "Ben", "Cy")
    maths, test = _subject(roster, grades, class_id, "Maths")
    grades.enter_scores([(test, ada.id, "9"), (test, ben.id, "9"), (test, cy.id, "5")])
    assert [r.place for r in rankings.subject_ranking(maths).ranked] == [1, 1, 3]
    rankings.method = "dense"
    assert [r.place for r in rankings.subject_ranking(maths).ranked] == [1, 1, 2]


def test_ranking_of_a_deleted_subject_is_none(rankings: RankingService):
    assert rankings.subject_ranking(999) is None


def test_overall_ranking_is_the_mean_of_subject_averages(
    roster: RosterService, grades: GradebookService, rankings: RankingService
):
    class_id, (ada, ben, cy) = _class(roster, "Ada", "Ben", "Cy")
    maths, maths_test = _subject(roster, grades, class_id, "Maths")
    art, art_test = _subject(roster, grades, class_id, "Art")
    _subject(roster, grades, class_id, "Music")  # nothing scored: not counted
    grades.enter_scores([(maths_test, ada.id, "6"), (art_test, ada.id, "10"), (maths_test, ben.id, "9")])
    ranking = rankings.overall_ranking(class_id)
    assert [(r.place, r.student.first_name, r.average) for r in ranking.ranked] == [(1, "Ben", 90), (2, "Ada", 80)]
    assert [s.first_name for s in ranking.unranked] == ["Cy"]
    assert ranking.subjects_counted == {ada.id: 2, ben.id: 1}
    assert ranking.subjects == 2
    assert ranking.subject_averages == {ada.id: [("Art", 100), ("Maths", 60)], ben.id: [("Maths", 90)]}


def test_overall_ranking_leaves_out_inactive_students(
    roster: RosterService, grades: GradebookService, rankings: RankingService
):
    class_id, (ada, ben) = _class(roster, "Ada", "Ben")
    maths, test = _subject(roster, grades, class_id, "Maths")
    grades.enter_scores([(test, ada.id, "6"), (test, ben.id, "9")])
    roster.deactivate_student(ben.id)
    assert [r.student.first_name for r in rankings.overall_ranking(class_id).ranked] == ["Ada"]


def test_overall_ranking_of_a_class_without_subjects_is_empty(roster: RosterService, rankings: RankingService):
    class_id, _students = _class(roster, "Ada")
    ranking = rankings.overall_ranking(class_id)
    assert ranking.ranked == [] and len(ranking.unranked) == 1 and ranking.subjects == 0
