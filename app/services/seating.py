"""Seating plans: a class's named layouts of seats, and who sits where.

A class can keep several plans, e.g. one for tests and one for group work. The
students' active list decides who can be seated; a deactivated student's seat shows
as free and is given away when someone else is put in it.
"""

import random
from dataclasses import dataclass, field, replace

from app.models import SeatLayout, Student
from app.repositories.class_repo import ClassRepository
from app.repositories.seating_repo import SeatingRepository
from app.repositories.student_repo import StudentRepository

NAME_MAX = 40  # characters in a plan's name
ROWS_MAX = 12
COLS_MAX = 12


class SeatingError(ValueError):
    """A user-facing error; the message is safe to show in the UI."""


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


@dataclass
class SeatingPlan:
    """One layout with the class's active students and who of them sits where."""

    layout: SeatLayout
    students: list[Student]
    seats: dict[tuple[int, int], int] = field(default_factory=dict)  # (row, col) -> student id

    def student_at(self, row: int, col: int) -> Student | None:
        student_id = self.seats.get((row, col))
        return next((s for s in self.students if s.id == student_id), None) if student_id else None

    def seat_of(self, student_id: int) -> tuple[int, int] | None:
        return next((seat for seat, s in self.seats.items() if s == student_id), None)

    @property
    def unseated(self) -> list[Student]:
        seated = set(self.seats.values())
        return [s for s in self.students if s.id not in seated]

    @property
    def free_seats(self) -> list[tuple[int, int]]:
        """Empty seats, front row first, left to right."""
        return [
            (r, c) for r in range(self.layout.rows) for c in range(self.layout.cols) if (r, c) not in self.seats
        ]


class SeatingService:
    def __init__(self, seating: SeatingRepository, students: StudentRepository, classes: ClassRepository):
        self.seating = seating
        self.students = students
        self.classes = classes

    # --- layouts -------------------------------------------------------------

    def list_layouts(self, class_id: int) -> list[SeatLayout]:
        return self.seating.layouts(class_id)

    def save_layout(self, layout: SeatLayout) -> SeatLayout:
        """Validate and create (id is None) or rename/resize a layout. Shrinking it
        frees the seats outside the new size (see seated_outside)."""
        layout = replace(layout, name=_clean(layout.name))
        if not layout.name:
            raise SeatingError("Give the seating plan a name, e.g. Tests or Group work.")
        if len(layout.name) > NAME_MAX:
            raise SeatingError(f"A name can be at most {NAME_MAX} characters; this one has {len(layout.name)}.")
        if not 1 <= layout.rows <= ROWS_MAX or not 1 <= layout.cols <= COLS_MAX:
            raise SeatingError(f"A room can have 1 to {ROWS_MAX} rows and 1 to {COLS_MAX} seats in a row.")
        if self.classes.get(layout.class_id) is None:
            raise SeatingError("The selected class no longer exists.")
        existing = self.seating.find_layout(layout.class_id, layout.name)
        if existing and existing.id != layout.id:
            raise SeatingError(f"This class already has a seating plan called {existing.name}.")
        if layout.id is None:
            return self.seating.add_layout(layout)
        self.seating.update_layout(layout)
        return layout

    def seated_outside(self, layout_id: int, rows: int, cols: int) -> list[Student]:
        """The active students who would lose their seat if the layout had `rows` × `cols` seats."""
        plan = self.plan(layout_id)
        if plan is None:
            return []
        return [plan.student_at(r, c) for (r, c) in sorted(plan.seats) if r >= rows or c >= cols]

    def delete_layout(self, layout_id: int) -> None:
        self.seating.delete_layout(layout_id)

    # --- seats ---------------------------------------------------------------

    def plan(self, layout_id: int) -> SeatingPlan | None:
        """The layout with its class's active students; None if it no longer exists."""
        layout = self.seating.get_layout(layout_id)
        if layout is None:
            return None
        students = self.students.list_for_class(layout.class_id)
        active = {s.id for s in students}
        seats = {seat: s for seat, s in self.seating.seats(layout_id).items() if s in active}
        return SeatingPlan(layout, students, seats)

    def _checked(self, layout_id: int, student_id: int) -> SeatingPlan:
        plan = self.plan(layout_id)
        if plan is None:
            raise SeatingError("This seating plan no longer exists.")
        if all(s.id != student_id for s in plan.students):
            raise SeatingError("This student isn't in the class any more.")
        return plan

    def place(self, layout_id: int, student_id: int, row: int, col: int) -> None:
        """Seat a student at (row, col), moving them from their seat if they had one.
        Whoever sat there swaps into that old seat, or stands up if there was none."""
        plan = self._checked(layout_id, student_id)
        if not (0 <= row < plan.layout.rows and 0 <= col < plan.layout.cols):
            raise SeatingError("There is no such seat in this room.")
        seats = dict(plan.seats)
        old = plan.seat_of(student_id)
        occupant = seats.get((row, col))
        if old is not None:
            del seats[old]
            if occupant is not None and occupant != student_id:
                seats[old] = occupant
        seats[(row, col)] = student_id
        self.seating.set_seats(layout_id, seats)

    def unseat(self, layout_id: int, student_id: int) -> None:
        """Take a student out of their seat."""
        plan = self._checked(layout_id, student_id)
        self.seating.set_seats(layout_id, {seat: s for seat, s in plan.seats.items() if s != student_id})

    def set_seats(self, layout_id: int, seats: dict[tuple[int, int], int]) -> None:
        """Replace the whole plan, e.g. to undo a change or after filling it."""
        self.seating.set_seats(layout_id, seats)

    def fill(self, layout_id: int, shuffle: bool = False, rng: random.Random | None = None) -> int:
        """Seat the students without a seat in the free seats, front row first, in name
        order or shuffled; with `shuffle`, everyone is reseated at random. Students who
        don't fit stay unseated. Returns how many students were given a seat."""
        plan = self.plan(layout_id)
        if plan is None:
            raise SeatingError("This seating plan no longer exists.")
        if shuffle:
            students = list(plan.students)
            (rng or random.Random()).shuffle(students)
            seats = {}
            free = [(r, c) for r in range(plan.layout.rows) for c in range(plan.layout.cols)]
        else:
            students = plan.unseated
            seats = dict(plan.seats)
            free = plan.free_seats
        for seat, student in zip(free, students):
            seats[seat] = student.id
        self.seating.set_seats(layout_id, seats)
        return min(len(free), len(students))
