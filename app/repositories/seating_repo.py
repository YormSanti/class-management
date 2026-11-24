"""Seating plans of a class: named layouts of rows × columns of seats, and who sits where.

A seat row only exists while a student sits in it; an empty seat is just a missing row.
A row without a student marks a spot with no desk, e.g. an aisle.
"""

import sqlite3
from dataclasses import replace

from app.db.connection import transaction
from app.models import SeatLayout


def _layout(row: sqlite3.Row) -> SeatLayout:
    return SeatLayout(id=row["id"], class_id=row["class_id"], name=row["name"], rows=row["rows"], cols=row["cols"])


class SeatingRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- layouts -------------------------------------------------------------

    def add_layout(self, layout: SeatLayout) -> SeatLayout:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO seat_layouts (class_id, name, rows, cols) VALUES (?, ?, ?, ?)",
                (layout.class_id, layout.name, layout.rows, layout.cols),
            )
        return replace(layout, id=cur.lastrowid)

    def update_layout(self, layout: SeatLayout) -> None:
        """Rename or resize; students in seats outside the new size lose them."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE seat_layouts SET name = ?, rows = ?, cols = ? WHERE id = ?",
                (layout.name, layout.rows, layout.cols, layout.id),
            )
            self.conn.execute(
                "DELETE FROM seats WHERE layout_id = ? AND (row >= ? OR col >= ?)",
                (layout.id, layout.rows, layout.cols),
            )

    def delete_layout(self, layout_id: int) -> None:
        """Delete a layout with its seats."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM seat_layouts WHERE id = ?", (layout_id,))

    def get_layout(self, layout_id: int) -> SeatLayout | None:
        row = self.conn.execute("SELECT * FROM seat_layouts WHERE id = ?", (layout_id,)).fetchone()
        return _layout(row) if row else None

    def find_layout(self, class_id: int, name: str) -> SeatLayout | None:
        """Case-insensitive, so "Exams" and "exams" count as the same layout."""
        row = self.conn.execute(
            "SELECT * FROM seat_layouts WHERE class_id = ? AND name = ? COLLATE NOCASE", (class_id, name)
        ).fetchone()
        return _layout(row) if row else None

    def layouts(self, class_id: int) -> list[SeatLayout]:
        """The class's layouts by name."""
        rows = self.conn.execute(
            "SELECT * FROM seat_layouts WHERE class_id = ? ORDER BY name COLLATE NOCASE, id", (class_id,)
        )
        return [_layout(r) for r in rows]

    # --- seats ---------------------------------------------------------------

    def seats(self, layout_id: int) -> dict[tuple[int, int], int]:
        """{(row, col): student id} of the seats taken."""
        rows = self.conn.execute(
            "SELECT row, col, student_id FROM seats WHERE layout_id = ? AND student_id IS NOT NULL", (layout_id,)
        )
        return {(r["row"], r["col"]): r["student_id"] for r in rows}

    def set_seats(self, layout_id: int, seats: dict[tuple[int, int], int]) -> None:
        """Replace who sits where in the layout with `seats` {(row, col): student id}.
        A student put where there was no desk gets the desk back."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM seats WHERE layout_id = ? AND student_id IS NOT NULL", (layout_id,))
            self.conn.executemany(
                "DELETE FROM seats WHERE layout_id = ? AND row = ? AND col = ?",
                [(layout_id, row, col) for row, col in seats],
            )
            self.conn.executemany(
                "INSERT INTO seats (layout_id, row, col, student_id) VALUES (?, ?, ?, ?)",
                [(layout_id, row, col, student) for (row, col), student in seats.items()],
            )

    def gaps(self, layout_id: int) -> set[tuple[int, int]]:
        """The (row, col) spots with no desk."""
        rows = self.conn.execute(
            "SELECT row, col FROM seats WHERE layout_id = ? AND student_id IS NULL", (layout_id,)
        )
        return {(r["row"], r["col"]) for r in rows}

    def set_gap(self, layout_id: int, row: int, col: int, gap: bool) -> None:
        """Mark the spot (row, col) as having no desk, freeing it of whoever sat there,
        or put a desk back."""
        with transaction(self.conn):
            self.conn.execute(
                "DELETE FROM seats WHERE layout_id = ? AND row = ? AND col = ?"
                + ("" if gap else " AND student_id IS NULL"),
                (layout_id, row, col),
            )
            if gap:
                self.conn.execute(
                    "INSERT INTO seats (layout_id, row, col, student_id) VALUES (?, ?, ?, NULL)", (layout_id, row, col)
                )
