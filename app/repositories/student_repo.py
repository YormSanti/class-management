import sqlite3
from dataclasses import replace

from app.db.connection import transaction
from app.models import Student


def _from_row(row: sqlite3.Row) -> Student:
    return Student(
        id=row["id"],
        class_id=row["class_id"],
        student_no=row["student_no"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        active=bool(row["active"]),
        notes=row["notes"],
    )


class StudentRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, student: Student) -> Student:
        with transaction(self.conn):
            cur = self.conn.execute(
                """
                INSERT INTO students (class_id, student_no, first_name, last_name, active, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    student.class_id,
                    student.student_no,
                    student.first_name,
                    student.last_name,
                    int(student.active),
                    student.notes,
                ),
            )
        return replace(student, id=cur.lastrowid)

    def update(self, student: Student) -> None:
        with transaction(self.conn):
            self.conn.execute(
                """
                UPDATE students
                SET student_no = ?, first_name = ?, last_name = ?, active = ?, notes = ?
                WHERE id = ?
                """,
                (
                    student.student_no,
                    student.first_name,
                    student.last_name,
                    int(student.active),
                    student.notes,
                    student.id,
                ),
            )

    def set_active(self, student_id: int, active: bool) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE students SET active = ? WHERE id = ?", (int(active), student_id)
            )

    def set_class(self, student_id: int, class_id: int, student_no: str | None) -> None:
        """Move the student to `class_id` with `student_no`, in one step: their number may
        be taken in either class on its own."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE students SET class_id = ?, student_no = ? WHERE id = ?", (class_id, student_no, student_id)
            )

    def delete(self, student_id: int) -> None:
        """Delete a student. Raises sqlite3.IntegrityError if anything refers to them."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM students WHERE id = ?", (student_id,))

    def has_records(self, student_id: int) -> bool:
        """True if any attendance, score or seat refers to the student."""
        row = self.conn.execute(
            """
            SELECT EXISTS (SELECT 1 FROM attendance WHERE student_id = :id)
                OR EXISTS (SELECT 1 FROM scores WHERE student_id = :id)
                OR EXISTS (SELECT 1 FROM seats WHERE student_id = :id)
            """,
            {"id": student_id},
        ).fetchone()
        return bool(row[0])

    def recorded(self, student_id: int) -> dict[str, int]:
        """What has_records() looks at, counted: {"attendance", "scores", "seating": count};
        seating counts the plans the student has a seat in."""
        row = self.conn.execute(
            """
            SELECT (SELECT count(*) FROM attendance WHERE student_id = :id) AS attendance,
                   (SELECT count(*) FROM scores WHERE student_id = :id) AS scores,
                   (SELECT count(*) FROM seats WHERE student_id = :id) AS seating
            """,
            {"id": student_id},
        ).fetchone()
        return dict(row)

    def get(self, student_id: int) -> Student | None:
        row = self.conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return _from_row(row) if row else None

    def find_by_student_no(self, class_id: int, student_no: str) -> Student | None:
        """Ignoring case, so "s007" and "S007" count as the same number."""
        row = self.conn.execute(
            "SELECT * FROM students WHERE class_id = ? AND student_no = ? COLLATE NOCASE",
            (class_id, student_no),
        ).fetchone()
        return _from_row(row) if row else None

    def find_by_name(self, class_id: int, first_name: str, last_name: str) -> list[Student]:
        """Students in the class with this name, ignoring case, also of letters such as
        "É" that SQLite's NOCASE leaves alone; inactive ones included."""
        wanted = (first_name.casefold(), last_name.casefold())
        rows = self.conn.execute("SELECT * FROM students WHERE class_id = ? ORDER BY id", (class_id,))
        return [_from_row(r) for r in rows if (r["first_name"].casefold(), r["last_name"].casefold()) == wanted]

    def list_for_class(self, class_id: int, include_inactive: bool = False) -> list[Student]:
        """Students in a class sorted by name (the roster service does the searching)."""
        sql = "SELECT * FROM students WHERE class_id = ?"
        if not include_inactive:
            sql += " AND active = 1"
        sql += " ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE, id"
        return [_from_row(r) for r in self.conn.execute(sql, (class_id,))]
