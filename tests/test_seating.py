import sqlite3
from dataclasses import replace

import pytest

from app.models import SchoolClass, SeatLayout, Student
from app.repositories.class_repo import ClassRepository
from app.repositories.seating_repo import SeatingRepository
from app.repositories.student_repo import StudentRepository
from app.services.seating import SeatingError, SeatingService
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


@pytest.fixture
def seating(conn: sqlite3.Connection) -> SeatingService:
    return SeatingService(SeatingRepository(conn), StudentRepository(conn), ClassRepository(conn))


def test_layout_is_validated(seating: SeatingService, class_id: int):
    with pytest.raises(SeatingError, match="name"):
        seating.save_layout(SeatLayout(class_id, "  ", 5, 6))
    with pytest.raises(SeatingError, match="1 to 12 rows"):
        seating.save_layout(SeatLayout(class_id, "Tests", 0, 6))
    with pytest.raises(SeatingError, match="1 to 12 rows"):
        seating.save_layout(SeatLayout(class_id, "Tests", 5, 13))
    with pytest.raises(SeatingError, match="no longer exists"):
        seating.save_layout(SeatLayout(999, "Tests", 5, 6))
    tests = seating.save_layout(SeatLayout(class_id, "  Tests ", 5, 6))
    assert tests.name == "Tests"
    with pytest.raises(SeatingError, match="already has a seating plan called Tests"):
        seating.save_layout(SeatLayout(class_id, "tests", 2, 2))
    seating.save_layout(replace(tests, rows=4))  # its own name is fine


def _seated_class(roster: RosterService, seating: SeatingService, class_id: int) -> tuple[int, int, int, int]:
    """Ada, Bob and Cy in a 2 × 3 room. Returns (layout, ada, bob, cy)."""
    ids = [roster.save_student(Student(class_id, f, l)).id for f, l in (("Ada", "Lovelace"), ("Bob", "Smith"), ("Cy", "Young"))]
    return (seating.save_layout(SeatLayout(class_id, "Tests", 2, 3)).id, *ids)


def test_placing_moves_and_swaps_students(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, bob, cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 0, 0)
    seating.place(layout, bob, 0, 1)
    plan = seating.plan(layout)
    assert plan.student_at(0, 0).first_name == "Ada" and plan.seat_of(bob) == (0, 1)
    assert [s.first_name for s in plan.unseated] == ["Cy"]
    seating.place(layout, ada, 0, 1)  # onto Bob: they swap
    assert seating.plan(layout).seats == {(0, 1): ada, (0, 0): bob}
    seating.place(layout, cy, 0, 1)  # onto Ada from no seat: Ada stands up
    plan = seating.plan(layout)
    assert plan.seats == {(0, 1): cy, (0, 0): bob}
    assert [s.first_name for s in plan.unseated] == ["Ada"]
    assert len(plan.free_seats) == 4 and plan.free_seats[0] == (0, 2)
    seating.unseat(layout, bob)
    assert seating.plan(layout).seats == {(0, 1): cy}


def test_seats_outside_the_room_are_refused(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, _bob, _cy = _seated_class(roster, seating, class_id)
    with pytest.raises(SeatingError, match="no such seat"):
        seating.place(layout, ada, 2, 0)
    with pytest.raises(SeatingError, match="isn't in the class"):
        seating.place(layout, 999, 0, 0)


def test_shrinking_names_who_would_lose_their_seat(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, bob, cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 0, 0)
    seating.place(layout, bob, 1, 0)
    seating.place(layout, cy, 0, 2)
    assert [s.first_name for s in seating.seated_outside(layout, 1, 2)] == ["Cy", "Bob"]
    assert seating.seated_outside(layout, 2, 3) == []


def test_a_deactivated_students_seat_shows_free_and_can_be_given_away(
    seating: SeatingService, roster: RosterService, class_id: int
):
    layout, ada, bob, _cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 0, 0)
    roster.deactivate_student(ada)
    plan = seating.plan(layout)
    assert plan.seats == {} and (0, 0) in plan.free_seats
    seating.place(layout, bob, 0, 0)
    assert seating.seating.seats(layout) == {(0, 0): bob}
