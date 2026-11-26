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


def test_fill_seats_the_rest_in_name_order_front_row_first(
    seating: SeatingService, roster: RosterService, class_id: int
):
    layout, ada, bob, cy = _seated_class(roster, seating, class_id)
    seating.place(layout, bob, 1, 2)
    assert seating.fill(layout) == 2
    assert seating.plan(layout).seats == {(1, 2): bob, (0, 0): ada, (0, 1): cy}


def test_fill_seats_as_many_as_fit(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, bob, cy = _seated_class(roster, seating, class_id)
    seating.save_layout(replace(seating.seating.get_layout(layout), rows=1, cols=2))
    assert seating.fill(layout) == 2
    assert [s.first_name for s in seating.plan(layout).unseated] == ["Cy"]


def test_shuffle_reseats_everyone(seating: SeatingService, roster: RosterService, class_id: int):
    import random

    layout, ada, bob, cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 1, 2)
    assert seating.fill(layout, shuffle=True, rng=random.Random(1)) == 3
    plan = seating.plan(layout)
    assert sorted(plan.seats.values()) == sorted([ada, bob, cy])
    assert set(plan.seats) == {(0, 0), (0, 1), (0, 2)}  # front row first
    orders = set()
    for seed in range(10):
        seating.fill(layout, shuffle=True, rng=random.Random(seed))
        orders.add(tuple(seating.plan(layout).seats[(0, c)] for c in range(3)))
    assert len(orders) > 1


def test_a_plan_is_copied_with_its_seats(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, bob, _cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 0, 0)
    seating.place(layout, bob, 1, 2)
    copy = seating.copy_layout(layout, " Exams ")
    assert (copy.name, copy.rows, copy.cols) == ("Exams", 2, 3)
    assert seating.plan(copy.id).seats == {(0, 0): ada, (1, 2): bob}
    seating.place(copy.id, ada, 0, 1)  # the copy is a plan of its own
    assert seating.plan(layout).seat_of(ada) == (0, 0)
    with pytest.raises(SeatingError, match="already has a seating plan called Exams"):
        seating.copy_layout(layout, "exams")
    assert len(seating.list_layouts(class_id)) == 2


def test_a_spot_without_a_desk_is_skipped(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, bob, cy = _seated_class(roster, seating, class_id)
    seating.set_desk(layout, 0, 1, desk=False)  # an aisle down the middle
    seating.set_desk(layout, 1, 1, desk=False)
    plan = seating.plan(layout)
    assert plan.gaps == {(0, 1), (1, 1)}
    assert plan.free_seats == [(0, 0), (0, 2), (1, 0), (1, 2)]
    with pytest.raises(SeatingError, match="no desk there"):
        seating.place(layout, ada, 0, 1)
    seating.fill(layout)
    assert seating.plan(layout).seats == {(0, 0): ada, (0, 2): bob, (1, 0): cy}
    assert seating.plan(layout).gaps == {(0, 1), (1, 1)}  # filling keeps the aisle
    seating.fill(layout, shuffle=True)
    assert (0, 1) not in seating.plan(layout).seats


def test_an_occupied_desk_stays(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, _bob, _cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 0, 0)
    with pytest.raises(SeatingError, match="Ada Lovelace sits there"):
        seating.set_desk(layout, 0, 0, desk=False)
    seating.set_desk(layout, 0, 1, desk=False)
    seating.set_desk(layout, 0, 1, desk=True)
    assert seating.plan(layout).gaps == set()


def test_putting_a_student_back_where_the_desk_was_taken_away_brings_it_back(
    seating: SeatingService, roster: RosterService, class_id: int
):
    layout, ada, _bob, _cy = _seated_class(roster, seating, class_id)
    seating.set_desk(layout, 0, 0, desk=False)
    seating.set_seats(layout, {(0, 0): ada})  # e.g. undoing to before the desk went
    plan = seating.plan(layout)
    assert plan.seats == {(0, 0): ada} and plan.gaps == set()


def test_gaps_are_copied_and_cut_off_with_the_room(seating: SeatingService, roster: RosterService, class_id: int):
    layout, _ada, _bob, _cy = _seated_class(roster, seating, class_id)
    seating.set_desk(layout, 1, 2, desk=False)
    copy = seating.copy_layout(layout, "Exams")
    assert seating.plan(copy.id).gaps == {(1, 2)}
    seating.save_layout(replace(copy, rows=1))
    assert seating.plan(copy.id).gaps == set()


def test_a_desk_held_by_a_deactivated_student_can_go(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, bob, _cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 0, 0)
    seating.place(layout, bob, 0, 1)
    roster.deactivate_student(ada)
    roster.deactivate_student(bob)
    seating.set_desk(layout, 0, 0, desk=False)
    assert seating.seating.seats(layout) == {(0, 1): bob}  # only the desk taken away is freed
    assert seating.plan(layout).gaps == {(0, 0)}


def test_a_plan_put_back_leaves_out_seats_gone_meanwhile(
    seating: SeatingService, roster: RosterService, class_id: int
):
    layout, ada, bob, cy = _seated_class(roster, seating, class_id)
    old = {(0, 0): ada, (1, 2): bob, (0, 1): cy}
    seating.save_layout(replace(seating.plan(layout).layout, rows=1))  # row 2 is gone
    roster.delete_student(cy)
    seating.set_seats(layout, old)  # e.g. undo from before the changes
    assert seating.plan(layout).seats == {(0, 0): ada}
    assert seating.seating.seats(layout) == {(0, 0): ada}


def test_a_deactivated_student_gets_their_seat_back_unless_it_was_given_away(
    seating: SeatingService, roster: RosterService, class_id: int
):
    layout, ada, bob, cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 0, 0)
    seating.place(layout, cy, 1, 1)
    roster.deactivate_student(ada)
    roster.deactivate_student(cy)
    seating.place(layout, bob, 1, 1)  # Cy's seat is given away; Ada's is untouched
    seating.fill(layout)
    roster.reactivate_student(ada)
    roster.reactivate_student(cy)
    plan = seating.plan(layout)
    assert plan.seats == {(0, 0): ada, (1, 1): bob}
    assert [s.first_name for s in plan.unseated] == ["Cy"]

    roster.deactivate_student(ada)
    seating.clear(layout)  # everyone, so nothing keeps the class from being deleted
    assert seating.seating.seats(layout) == {}


def test_a_plan_is_restored_with_its_desks(seating: SeatingService, roster: RosterService, class_id: int):
    layout, ada, bob, _cy = _seated_class(roster, seating, class_id)
    seating.place(layout, ada, 0, 0)
    seating.set_desk(layout, 1, 1, False)
    seating.place(layout, bob, 0, 1)
    seating.set_desk(layout, 0, 2, False)
    seating.restore(layout, {(0, 0): bob, (0, 1): ada}, {(0, 2), (1, 2), (5, 5)})
    plan = seating.plan(layout)
    assert plan.seats == {(0, 0): bob, (0, 1): ada}
    assert plan.gaps == {(0, 2), (1, 2)}  # (5, 5) is outside the room
