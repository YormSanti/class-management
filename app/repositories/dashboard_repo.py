"""Read-only aggregate queries for the dashboard. Inactive students are left out everywhere."""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass
class CategoryPoints:
    """One student's scored points in one category (scores that are NULL are skipped)."""

    student_id: int
    category_id: int
    weight: float
    earned: float
    possible: float


@dataclass
class AssignmentStats:
    id: int
    title: str
    category: str
    date: date | None
    max_score: float
    submitted: int  # active students with a score (not NULL)
    average_percent: float | None


class DashboardRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def count_students(self, class_id: int) -> tuple[int, int]:
        """(active, inactive) student counts."""
        row = self.conn.execute(
            """
            SELECT coalesce(sum(active = 1), 0) AS active, coalesce(sum(active = 0), 0) AS inactive
            FROM students WHERE class_id = ?
            """,
            (class_id,),
        ).fetchone()
        return row["active"], row["inactive"]

    def recent_attendance_dates(self, class_id: int, on_or_before: date, limit: int) -> list[date]:
        """The most recent days with any attendance recorded, oldest first."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT a.date FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE s.class_id = ? AND s.active = 1 AND a.date <= ?
            ORDER BY a.date DESC LIMIT ?
            """,
            (class_id, on_or_before.isoformat(), limit),
        )
        return sorted(date.fromisoformat(r["date"]) for r in rows)

    def attendance_by_student(
        self, class_id: int, start: date, end: date
    ) -> dict[int, dict[str, int]]:
        """{student_id: {status: count}} for days in [start, end]."""
        rows = self.conn.execute(
            """
            SELECT a.student_id, a.status, count(*) AS n FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE s.class_id = ? AND s.active = 1 AND a.date BETWEEN ? AND ?
            GROUP BY a.student_id, a.status
            """,
            (class_id, start.isoformat(), end.isoformat()),
        )
        result: dict[int, dict[str, int]] = defaultdict(dict)
        for r in rows:
            result[r["student_id"]][r["status"]] = r["n"]
        return dict(result)

    def attendance_by_date(
        self, class_id: int, start: date, end: date
    ) -> dict[date, dict[str, int]]:
        """{day: {status: count}} for days in [start, end]."""
        rows = self.conn.execute(
            """
            SELECT a.date, a.status, count(*) AS n FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE s.class_id = ? AND s.active = 1 AND a.date BETWEEN ? AND ?
            GROUP BY a.date, a.status
            """,
            (class_id, start.isoformat(), end.isoformat()),
        )
        result: dict[date, dict[str, int]] = defaultdict(dict)
        for r in rows:
            result[date.fromisoformat(r["date"])][r["status"]] = r["n"]
        return dict(result)

    def category_points(self, class_id: int) -> list[CategoryPoints]:
        rows = self.conn.execute(
            """
            SELECT sc.student_id, c.id AS category_id, c.weight,
                   sum(sc.score) AS earned, sum(a.max_score) AS possible
            FROM scores sc
            JOIN assignments a ON a.id = sc.assignment_id
            JOIN categories c ON c.id = a.category_id
            JOIN students s ON s.id = sc.student_id
            WHERE a.class_id = ? AND s.active = 1 AND sc.score IS NOT NULL
            GROUP BY sc.student_id, c.id
            """,
            (class_id,),
        )
        return [
            CategoryPoints(r["student_id"], r["category_id"], r["weight"], r["earned"], r["possible"])
            for r in rows
        ]

    def missing_by_student(self, class_id: int, on_or_before: date) -> dict[int, int]:
        """{student_id: number of dated assignments up to `on_or_before` without a score}."""
        rows = self.conn.execute(
            """
            SELECT s.id AS student_id, count(*) AS n
            FROM students s
            JOIN assignments a ON a.class_id = s.class_id
            LEFT JOIN scores sc ON sc.assignment_id = a.id AND sc.student_id = s.id
            WHERE s.class_id = ? AND s.active = 1
              AND a.date IS NOT NULL AND a.date <= ? AND sc.score IS NULL
            GROUP BY s.id
            """,
            (class_id, on_or_before.isoformat()),
        )
        return {r["student_id"]: r["n"] for r in rows}

    def recent_assignments(self, class_id: int, limit: int) -> list[AssignmentStats]:
        """Newest assignments first; undated ones come last."""
        rows = self.conn.execute(
            """
            SELECT a.id, a.title, c.name AS category, a.date, a.max_score,
                   count(s.id) AS submitted,
                   avg(CASE WHEN s.id IS NOT NULL THEN sc.score * 100.0 / a.max_score END) AS avg_pct
            FROM assignments a
            JOIN categories c ON c.id = a.category_id
            LEFT JOIN scores sc ON sc.assignment_id = a.id AND sc.score IS NOT NULL
            LEFT JOIN students s ON s.id = sc.student_id AND s.active = 1
            WHERE a.class_id = ?
            GROUP BY a.id
            ORDER BY a.date IS NULL, a.date DESC, a.id DESC
            LIMIT ?
            """,
            (class_id, limit),
        )
        return [
            AssignmentStats(
                id=r["id"],
                title=r["title"],
                category=r["category"],
                date=date.fromisoformat(r["date"]) if r["date"] else None,
                max_score=r["max_score"],
                submitted=r["submitted"],
                average_percent=r["avg_pct"],
            )
            for r in rows
        ]
