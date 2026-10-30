import sqlite3
from dataclasses import replace

from app.db.connection import transaction
from app.models import Subject


def _from_row(row: sqlite3.Row) -> Subject:
    return Subject(id=row["id"], class_id=row["class_id"], name=row["name"], teacher=row["teacher"])


class SubjectRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, subject: Subject) -> Subject:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO subjects (class_id, name, teacher) VALUES (?, ?, ?)",
                (subject.class_id, subject.name, subject.teacher),
            )
        return replace(subject, id=cur.lastrowid)

    def update(self, subject: Subject) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE subjects SET name = ?, teacher = ? WHERE id = ?",
                (subject.name, subject.teacher, subject.id),
            )

    def delete(self, subject_id: int) -> None:
        """Delete a subject. Raises sqlite3.IntegrityError if grades or attendance reference it."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))

    def get(self, subject_id: int) -> Subject | None:
        row = self.conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        return _from_row(row) if row else None

    def find_by_name(self, class_id: int, name: str) -> Subject | None:
        """Case-insensitive, so "maths" and "Maths" count as the same subject."""
        row = self.conn.execute(
            "SELECT * FROM subjects WHERE class_id = ? AND name = ? COLLATE NOCASE",
            (class_id, name),
        ).fetchone()
        return _from_row(row) if row else None

    def list_for_class(self, class_id: int) -> list[Subject]:
        rows = self.conn.execute(
            "SELECT * FROM subjects WHERE class_id = ? ORDER BY name COLLATE NOCASE, id",
            (class_id,),
        )
        return [_from_row(r) for r in rows]
