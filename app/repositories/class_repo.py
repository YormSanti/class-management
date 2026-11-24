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
        """Delete a class with its students and subjects.

        Raises sqlite3.IntegrityError (and deletes nothing) if seating, or any
        attendance or grades of its students or subjects, still reference them.
        """
        with transaction(self.conn):
            self.conn.execute("DELETE FROM students WHERE class_id = ?", (class_id,))
            # Grade categories are setup, not records; one with assignments still stops the delete.
            self.conn.execute(
                "DELETE FROM categories WHERE subject_id IN (SELECT id FROM subjects WHERE class_id = ?)", (class_id,)
            )
            self.conn.execute("DELETE FROM subjects WHERE class_id = ?", (class_id,))
            self.conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))

    def recorded(self, class_id: int) -> dict[str, int]:
        """How much is recorded for the class's students and subjects, i.e. what stops
        delete() from removing it: {"attendance", "scores", "assignments", "seating": count}. Seating counts its layouts and others its students sit in."""
        row = self.conn.execute(
            """
            WITH st AS (SELECT id FROM students WHERE class_id = :c),
                 sub AS (SELECT id FROM subjects WHERE class_id = :c)
            SELECT
              (SELECT count(*) FROM attendance WHERE student_id IN st OR subject_id IN sub) AS attendance,
              (SELECT count(*) FROM scores WHERE student_id IN st
                  OR assignment_id IN (SELECT id FROM assignments WHERE subject_id IN sub)) AS scores,
              (SELECT count(*) FROM assignments WHERE subject_id IN sub) AS assignments,
              (SELECT count(*) FROM seat_layouts WHERE class_id = :c
                  OR id IN (SELECT layout_id FROM seats WHERE student_id IN st)) AS seating
            """,
            {"c": class_id},
        ).fetchone()
        return dict(row)

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

    def rename_term(self, old: str, new: str) -> int:
        """Give every class of school year `old` the year `new`; returns how many changed."""
        with transaction(self.conn):
            cur = self.conn.execute("UPDATE classes SET term = ? WHERE term = ?", (new, old))
        return cur.rowcount

    def counts(self) -> dict[int, tuple[int, int]]:
        """{class id: (active students, subjects)} for every class, in one query."""
        rows = self.conn.execute(
            """
            SELECT c.id,
                   (SELECT count(*) FROM students s WHERE s.class_id = c.id AND s.active = 1) AS students,
                   (SELECT count(*) FROM subjects sub WHERE sub.class_id = c.id) AS subjects
            FROM classes c
            """
        )
        return {r["id"]: (r["students"], r["subjects"]) for r in rows}

    def inactive_counts(self) -> dict[int, int]:
        """{class id: inactive students}, for the classes that have any."""
        rows = self.conn.execute("SELECT class_id, count(*) AS n FROM students WHERE active = 0 GROUP BY class_id")
        return {r["class_id"]: r["n"] for r in rows}

    def totals(self) -> dict[str, int]:
        """How much the whole data file holds: {"classes", "students", "attendance": count}."""
        row = self.conn.execute(
            """
            SELECT (SELECT count(*) FROM classes) AS classes,
                   (SELECT count(*) FROM students) AS students,
                   (SELECT count(*) FROM attendance) AS attendance
            """
        ).fetchone()
        return dict(row)
