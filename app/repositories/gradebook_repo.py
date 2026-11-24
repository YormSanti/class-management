"""Grade categories, assignments and scores of one subject's gradebook.

A category (e.g. Tests, weight 50) groups assignments; every assignment has a
maximum score; a score is what one student got on one assignment. A score row
with score NULL means "exempt", which is ignored in averages and differs both
from 0 and from no row at all (nothing entered yet).
"""

import sqlite3
from dataclasses import replace
from datetime import date

from app.db.connection import transaction
from app.models import Assignment, Category


def _category(row: sqlite3.Row) -> Category:
    return Category(id=row["id"], subject_id=row["subject_id"], name=row["name"], weight=row["weight"])


def _assignment(row: sqlite3.Row) -> Assignment:
    return Assignment(
        id=row["id"],
        subject_id=row["subject_id"],
        category_id=row["category_id"],
        title=row["title"],
        max_score=row["max_score"],
        date=date.fromisoformat(row["date"]) if row["date"] else None,
    )


class GradebookRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- categories ----------------------------------------------------------

    def add_category(self, category: Category) -> Category:
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO categories (subject_id, name, weight) VALUES (?, ?, ?)",
                (category.subject_id, category.name, category.weight),
            )
        return replace(category, id=cur.lastrowid)

    def update_category(self, category: Category) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE categories SET name = ?, weight = ? WHERE id = ?",
                (category.name, category.weight, category.id),
            )

    def delete_category(self, category_id: int) -> None:
        """Raises sqlite3.IntegrityError while assignments use the category."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    def get_category(self, category_id: int) -> Category | None:
        row = self.conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
        return _category(row) if row else None

    def find_category(self, subject_id: int, name: str) -> Category | None:
        """Case-insensitive, so "tests" and "Tests" count as the same category."""
        row = self.conn.execute(
            "SELECT * FROM categories WHERE subject_id = ? AND name = ? COLLATE NOCASE",
            (subject_id, name),
        ).fetchone()
        return _category(row) if row else None

    def categories(self, subject_id: int) -> list[Category]:
        """The subject's categories, heaviest first."""
        rows = self.conn.execute(
            "SELECT * FROM categories WHERE subject_id = ? ORDER BY weight DESC, name COLLATE NOCASE, id",
            (subject_id,),
        )
        return [_category(r) for r in rows]

    # --- assignments ---------------------------------------------------------

    def add_assignment(self, assignment: Assignment) -> Assignment:
        a = assignment
        with transaction(self.conn):
            cur = self.conn.execute(
                "INSERT INTO assignments (subject_id, category_id, title, date, max_score) VALUES (?, ?, ?, ?, ?)",
                (a.subject_id, a.category_id, a.title, a.date.isoformat() if a.date else None, a.max_score),
            )
        return replace(assignment, id=cur.lastrowid)

    def update_assignment(self, assignment: Assignment) -> None:
        a = assignment
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE assignments SET category_id = ?, title = ?, date = ?, max_score = ? WHERE id = ?",
                (a.category_id, a.title, a.date.isoformat() if a.date else None, a.max_score, a.id),
            )

    def delete_assignment(self, assignment_id: int) -> None:
        """Delete an assignment with its scores."""
        with transaction(self.conn):
            self.conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))

    def get_assignment(self, assignment_id: int) -> Assignment | None:
        row = self.conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        return _assignment(row) if row else None

    def assignments(self, subject_id: int) -> list[Assignment]:
        """The subject's assignments by date, undated ones last, then in the order added."""
        rows = self.conn.execute(
            "SELECT * FROM assignments WHERE subject_id = ? ORDER BY date IS NULL, date, id",
            (subject_id,),
        )
        return [_assignment(r) for r in rows]

    def assignment_counts(self, subject_id: int) -> dict[int, int]:
        """{category id: assignments in it}; categories without any are left out."""
        rows = self.conn.execute(
            "SELECT category_id, count(*) AS n FROM assignments WHERE subject_id = ? GROUP BY category_id",
            (subject_id,),
        )
        return {r["category_id"]: r["n"] for r in rows}

    # --- scores --------------------------------------------------------------

    def save_score(self, assignment_id: int, student_id: int, score: float | None) -> None:
        """Enter or replace a student's score; None marks them exempt."""
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO scores (assignment_id, student_id, score) VALUES (?, ?, ?)
                ON CONFLICT (assignment_id, student_id) DO UPDATE SET score = excluded.score
                """,
                (assignment_id, student_id, score),
            )

    def clear_score(self, assignment_id: int, student_id: int) -> None:
        """Forget a student's score, as if nothing had been entered."""
        with transaction(self.conn):
            self.conn.execute(
                "DELETE FROM scores WHERE assignment_id = ? AND student_id = ?", (assignment_id, student_id)
            )

    def scores(self, subject_id: int) -> dict[tuple[int, int], float | None]:
        """{(assignment id, student id): score} of every score entered in the subject,
        None for an exempt student."""
        rows = self.conn.execute(
            """
            SELECT sc.assignment_id, sc.student_id, sc.score FROM scores sc
            JOIN assignments a ON a.id = sc.assignment_id
            WHERE a.subject_id = ?
            """,
            (subject_id,),
        )
        return {(r["assignment_id"], r["student_id"]): r["score"] for r in rows}

    def score_count(self, assignment_id: int) -> int:
        """How many scores (exemptions included) were entered for the assignment."""
        return self.conn.execute(
            "SELECT count(*) FROM scores WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()[0]
