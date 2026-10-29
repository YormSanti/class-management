import sqlite3
from dataclasses import replace

from app.db.connection import transaction
from app.models import SchoolClass


def _from_row(row: sqlite3.Row) -> SchoolClass:
    return SchoolClass(id=row["id"], name=row["name"], subject=row["subject"], term=row["term"])


class ClassRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, school_class: SchoolClass) -> SchoolClass:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO classes (name, subject, term) VALUES (?, ?, ?)",
                (school_class.name, school_class.subject, school_class.term),
            )
        return replace(school_class, id=cur.lastrowid)

    def update(self, school_class: SchoolClass) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE classes SET name = ?, subject = ?, term = ? WHERE id = ?",
                (school_class.name, school_class.subject, school_class.term, school_class.id),
            )

    def delete(self, class_id: int) -> None:
        """Delete a class. Raises sqlite3.IntegrityError if anything references it."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))

    def get(self, class_id: int) -> SchoolClass | None:
        row = self.conn.execute("SELECT * FROM classes WHERE id = ?", (class_id,)).fetchone()
        return _from_row(row) if row else None

    def list_all(self) -> list[SchoolClass]:
        rows = self.conn.execute("SELECT * FROM classes ORDER BY name COLLATE NOCASE, term, id")
        return [_from_row(r) for r in rows]
