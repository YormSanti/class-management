"""Grade categories, assignments and scores of one subject's gradebook.

A category (e.g. Tests, weight 50) groups assignments; every assignment has a
maximum score; a score is what one student got on one assignment. A score row
with score NULL means "exempt / not submitted", which is ignored in averages
and differs both from 0 and from no row at all (nothing entered yet).
"""

import sqlite3
from dataclasses import replace

from app.db.connection import transaction
from app.models import Category


def _category(row: sqlite3.Row) -> Category:
    return Category(id=row["id"], subject_id=row["subject_id"], name=row["name"], weight=row["weight"])


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
