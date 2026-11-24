import sqlite3

import pytest

from app.models import SchoolClass, SeatLayout, Student
from app.repositories.seating_repo import SeatingRepository
from app.services.roster import RosterService


@pytest.fixture
def repo(conn: sqlite3.Connection) -> SeatingRepository:
    return SeatingRepository(conn)


@pytest.fixture
def class_id(roster: RosterService) -> int:
    return roster.save_class(SchoolClass(name="7B", term="2026-2027")).id


def test_layouts_are_listed_by_name(repo: SeatingRepository, class_id: int):
    repo.add_layout(SeatLayout(class_id, "Tests", 5, 6))
    groups = repo.add_layout(SeatLayout(class_id, "group work", 3, 4))
    assert [x.name for x in repo.layouts(class_id)] == ["group work", "Tests"]
    assert repo.get_layout(groups.id) == groups
    assert repo.find_layout(class_id, "TESTS").name == "Tests"
    assert repo.find_layout(class_id, "Exams") is None


def test_layout_name_is_unique_per_class(repo: SeatingRepository, class_id: int):
    repo.add_layout(SeatLayout(class_id, "Tests", 5, 6))
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_layout(SeatLayout(class_id, "Tests", 2, 2))


def test_seats_are_saved_and_replaced(repo: SeatingRepository, roster: RosterService, class_id: int):
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace")).id
    bob = roster.save_student(Student(class_id, "Bob", "Smith")).id
    layout = repo.add_layout(SeatLayout(class_id, "Tests", 2, 3)).id
    repo.set_seats(layout, {(0, 0): ada, (1, 2): bob})
    assert repo.seats(layout) == {(0, 0): ada, (1, 2): bob}
    repo.set_seats(layout, {(0, 1): bob})
    assert repo.seats(layout) == {(0, 1): bob}


def test_a_student_has_one_seat_per_layout(repo: SeatingRepository, roster: RosterService, class_id: int):
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace")).id
    layout = repo.add_layout(SeatLayout(class_id, "Tests", 2, 3)).id
    with pytest.raises(sqlite3.IntegrityError):
        repo.set_seats(layout, {(0, 0): ada, (0, 1): ada})
    assert repo.seats(layout) == {}  # all or nothing


def test_shrinking_a_layout_frees_the_seats_outside_it(repo: SeatingRepository, roster: RosterService, class_id: int):
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace")).id
    bob = roster.save_student(Student(class_id, "Bob", "Smith")).id
    layout = repo.add_layout(SeatLayout(class_id, "Tests", 3, 3))
    repo.set_seats(layout.id, {(0, 0): ada, (2, 1): bob})
    repo.update_layout(SeatLayout(class_id, "Exams", 2, 3, id=layout.id))
    assert repo.get_layout(layout.id).name == "Exams"
    assert repo.seats(layout.id) == {(0, 0): ada}


def test_deleting_a_layout_frees_its_students(repo: SeatingRepository, roster: RosterService, class_id: int):
    ada = roster.save_student(Student(class_id, "Ada", "Lovelace")).id
    layout = repo.add_layout(SeatLayout(class_id, "Tests", 2, 2)).id
    repo.set_seats(layout, {(0, 0): ada})
    repo.delete_layout(layout)
    assert repo.layouts(class_id) == []
    assert roster.can_delete_student(ada)
