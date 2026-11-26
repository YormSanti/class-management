"""Seating plans: a class's named layouts of seats, and who sits where.

A class can keep several plans, e.g. one for tests and one for group work. The
students' active list decides who can be seated; a deactivated student's seat shows
as free and is given away when someone else is put in it; until then it is theirs
again if they are reactivated.
"""

import random
from dataclasses import dataclass, field, replace

from app.db.connection import transaction
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
    gaps: set[tuple[int, int]] = field(default_factory=set)  # spots with no desk, e.g. an aisle

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
    def desks(self) -> list[tuple[int, int]]:
        """Every seat, front row first, left to right; spots with no desk left out."""
        return [
            (r, c) for r in range(self.layout.rows) for c in range(self.layout.cols) if (r, c) not in self.gaps
        ]

    @property
    def free_seats(self) -> list[tuple[int, int]]:
        """Empty seats, front row first, left to right."""
        return [seat for seat in self.desks if seat not in self.seats]


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

    def copy_layout(self, layout_id: int, name: str) -> SeatLayout:
        """A new plan called `name` with the same room and everyone in the same seat."""
        layout = self.seating.get_layout(layout_id)
        if layout is None:
            raise SeatingError("This seating plan no longer exists.")
        with transaction(self.seating.conn):
            copy = self.save_layout(replace(layout, name=name, id=None))
            for row, col in self.seating.gaps(layout_id):
                self.seating.set_gap(copy.id, row, col, True)
            self.seating.set_seats(copy.id, self.seating.seats(layout_id))
        return copy

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
        return SeatingPlan(layout, students, seats, self.seating.gaps(layout_id))

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
        if (row, col) in plan.gaps:
            raise SeatingError("There's no desk there. Put one there first.")
        seats = dict(plan.seats)
        old = plan.seat_of(student_id)
        occupant = seats.get((row, col))
        if old is not None:
            del seats[old]
            if occupant is not None and occupant != student_id:
                seats[old] = occupant
        seats[(row, col)] = student_id
        self._write(plan, seats)

    def set_desk(self, layout_id: int, row: int, col: int, desk: bool) -> None:
        """Put a desk at (row, col), or mark it as a spot with no desk, e.g. an aisle.
        The desk has to be free to be taken away; a deactivated student's seat counts as free."""
        plan = self.plan(layout_id)
        if plan is None:
            raise SeatingError("This seating plan no longer exists.")
        if not desk and (occupant := plan.student_at(row, col)) is not None:
            raise SeatingError(f"{occupant.full_name} sits there. Take them out of the seat first.")
        self.seating.set_gap(layout_id, row, col, not desk)

    def unseat(self, layout_id: int, student_id: int) -> None:
        """Take a student out of their seat."""
        plan = self._checked(layout_id, student_id)
        self._write(plan, {seat: s for seat, s in plan.seats.items() if s != student_id})

    def set_seats(self, layout_id: int, seats: dict[tuple[int, int], int]) -> None:
        """Replace the whole plan, e.g. to undo a change or after filling it. Seats
        outside the room, and students no longer in the class or deactivated meanwhile,
        are left out: the room may have been made smaller or a student deleted since."""
        plan = self.plan(layout_id)
        if plan is None:
            raise SeatingError("This seating plan no longer exists.")
        students = {s.id for s in plan.students}
        rows, cols = plan.layout.rows, plan.layout.cols
        self._write(
            plan, {(r, c): s for (r, c), s in seats.items() if s in students and 0 <= r < rows and 0 <= c < cols}
        )

    def restore(
        self,
        layout_id: int,
        seats: dict[tuple[int, int], int],
        gaps: set[tuple[int, int]],
        size: tuple[int, int] | None = None,
    ) -> None:
        """Put back who sat where, the spots with no desk and the room's (rows, cols)
        `size`, e.g. to undo a change; what no longer fits is left out as in set_seats."""
        layout = self.seating.get_layout(layout_id)
        if layout is None:
            raise SeatingError("This seating plan no longer exists.")
        with transaction(self.seating.conn):
            if size and size != (layout.rows, layout.cols):
                layout = replace(layout, rows=size[0], cols=size[1])
                self.seating.update_layout(layout)
            gaps = {(r, c) for r, c in gaps if r < layout.rows and c < layout.cols}
            current = self.seating.gaps(layout_id)
            for row, col in current - gaps:
                self.seating.set_gap(layout_id, row, col, False)
            for row, col in gaps - current:
                self.seating.set_gap(layout_id, row, col, True)
            self.set_seats(layout_id, seats)

    def clear(self, layout_id: int) -> None:
        """Take everyone out of their seat, deactivated students too."""
        self.seating.set_seats(layout_id, {})

    def _write(self, plan: SeatingPlan, seats: dict[tuple[int, int], int]) -> None:
        """Save `seats` {(row, col): active student id} as who sits where in `plan`. A
        deactivated student keeps their seat unless someone else sits there now, so it is
        theirs again if they come back."""
        active = {s.id for s in plan.students}
        held = {
            seat: s for seat, s in self.seating.seats(plan.layout.id).items() if s not in active and seat not in seats
        }
        self.seating.set_seats(plan.layout.id, seats | held)

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
            free = plan.desks
        else:
            students = plan.unseated
            seats = dict(plan.seats)
            free = plan.free_seats
        for seat, student in zip(free, students):
            seats[seat] = student.id
        self._write(plan, seats)
        return min(len(free), len(students))
