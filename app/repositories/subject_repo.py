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
        """Delete a subject with its grade categories. Raises sqlite3.IntegrityError if
        assignments or attendance reference it."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM categories WHERE subject_id = ?", (subject_id,))
            self.conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))

    def copy_categories(self, from_subject_id: int, to_subject_id: int) -> None:
        """Give `to_subject_id` the grade categories of `from_subject_id` it doesn't have yet."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO categories (subject_id, name, weight)
                SELECT ?, name, weight FROM categories c WHERE subject_id = ?
                  AND NOT EXISTS (SELECT 1 FROM categories WHERE subject_id = ? AND name = c.name COLLATE NOCASE)
                ORDER BY id
                """,
                (to_subject_id, from_subject_id, to_subject_id),
            )

    def recorded(self, subject_id: int) -> dict[str, int]:
        """What stops delete() from removing the subject: {"attendance", "scores",
        "assignments": count}."""
        row = self.conn.execute(
            """
            SELECT
              (SELECT count(*) FROM attendance WHERE subject_id = :s) AS attendance,
              (SELECT count(*) FROM scores
                  WHERE assignment_id IN (SELECT id FROM assignments WHERE subject_id = :s)) AS scores,
              (SELECT count(*) FROM assignments WHERE subject_id = :s) AS assignments
            """,
            {"s": subject_id},
        ).fetchone()
        return dict(row)

    def get(self, subject_id: int) -> Subject | None:
        row = self.conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        return _from_row(row) if row else None

    def find_by_name(self, class_id: int, name: str) -> Subject | None:
        """Case-insensitive, so "maths" and "Maths", or "économie" and "Économie", count
        as the same subject (SQLite's NOCASE only folds A to Z)."""
        rows = self.conn.execute("SELECT * FROM subjects WHERE class_id = ? ORDER BY id", (class_id,))
        return next((_from_row(r) for r in rows if r["name"].casefold() == name.casefold()), None)

    def list_for_class(self, class_id: int) -> list[Subject]:
        rows = self.conn.execute(
            "SELECT * FROM subjects WHERE class_id = ? ORDER BY name COLLATE NOCASE, id",
            (class_id,),
        )
        return [_from_row(r) for r in rows]

    def distinct_values(self, column: str) -> list[str]:
        """Every different subject name or teacher in use, in any class, sorted."""
        if column not in ("name", "teacher"):
            raise ValueError(column)
        rows = self.conn.execute(
            f"SELECT DISTINCT {column} AS value FROM subjects WHERE {column} <> '' ORDER BY {column} COLLATE NOCASE"
        )
        return [r["value"] for r in rows]
