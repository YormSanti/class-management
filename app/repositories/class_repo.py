import sqlite3
from dataclasses import replace

from app.db.connection import transaction
from app.models import SchoolClass


def _from_row(row: sqlite3.Row) -> SchoolClass:
    return SchoolClass(id=row["id"], name=row["name"], term=row["term"])


class ClassRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, school_class: SchoolClass) -> SchoolClass:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO classes (name, term) VALUES (?, ?)",
                (school_class.name, school_class.term),
            )
        return replace(school_class, id=cur.lastrowid)

    def update(self, school_class: SchoolClass) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE classes SET name = ?, term = ? WHERE id = ?",
                (school_class.name, school_class.term, school_class.id),
            )

    def delete(self, class_id: int) -> None:
        """Delete a class and its subjects.

        Raises sqlite3.IntegrityError (and deletes nothing) if students, seating,
        or any subject's grades or attendance still reference them.
        """
        with transaction(self.conn):
            self.conn.execute("DELETE FROM subjects WHERE class_id = ?", (class_id,))
            self.conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))

    def get(self, class_id: int) -> SchoolClass | None:
        row = self.conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
        return _from_row(row) if row else None

    def list_all(self) -> list[SchoolClass]:
        rows = self.conn.execute("SELECT * FROM classes ORDER BY name COLLATE NOCASE, term, id")
        return [_from_row(r) for r in rows]

    def find_by_name(self, name: str, term: str) -> SchoolClass | None:
        """Case-insensitive, so "7b" and "7B" in the same school year count as the same class."""
        row = self.conn.execute(
            "SELECT * FROM classes WHERE name = ? COLLATE NOCASE AND term = ?", (name, term)
        ).fetchone()
        return _from_row(row) if row else None

    def list_terms(self) -> list[str]:
        """Distinct non-empty school years, newest first ("2026-2027" before "2025-2026")."""
        rows = self.conn.execute("SELECT DISTINCT term FROM classes WHERE term <> '' ORDER BY term DESC")
        return [r["term"] for r in rows]
