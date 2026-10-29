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


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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

    def get(self, student_id: int) -> Student | None:
        row = self.conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return _from_row(row) if row else None

    def find_by_student_no(self, class_id: int, student_no: str) -> Student | None:
        row = self.conn.execute(
            "SELECT * FROM students WHERE class_id = ? AND student_no = ?",
            (class_id, student_no),
        ).fetchone()
        return _from_row(row) if row else None

    def list_for_class(
        self, class_id: int, search: str = "", include_inactive: bool = False
    ) -> list[Student]:
        """Students in a class sorted by name, optionally filtered by a search term.

        The search matches student number, first name, last name, or "first last".
        """
        sql = "SELECT * FROM students WHERE class_id = ?"
        params: list[object] = [class_id]
        if not include_inactive:
            sql += " AND active = 1"
        if search:
            pattern = f"%{_escape_like(search)}%"
            sql += """
                AND (student_no LIKE ? ESCAPE '\\'
                     OR first_name LIKE ? ESCAPE '\\'
                     OR last_name LIKE ? ESCAPE '\\'
                     OR first_name || ' ' || last_name LIKE ? ESCAPE '\\')
            """
            params += [pattern] * 4
        sql += " ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE, id"
        return [_from_row(r) for r in self.conn.execute(sql, params)]
