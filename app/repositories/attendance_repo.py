"""Attendance records: one per student, day and register.

A register is either the daily (homeroom) one, `subject_id` None, or one subject's
lessons. Every query takes the register explicitly, so the two never mix.
"""

import sqlite3
from collections import defaultdict
from datetime import date

from app.db.connection import transaction
from app.models import AttendanceRecord, AttendanceStatus

# Matches the unique index, which uses coalesce() because NULLs never clash.
_SAME_REGISTER = "coalesce(subject_id, 0) = coalesce(?, 0)"


def _from_row(row: sqlite3.Row) -> AttendanceRecord:
    return AttendanceRecord(
        id=row["id"],
        student_id=row["student_id"],
        subject_id=row["subject_id"],
        date=date.fromisoformat(row["date"]),
        status=AttendanceStatus(row["status"]),
        note=row["note"],
    )


class AttendanceRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, student_id: int, day: date, subject_id: int | None) -> AttendanceRecord | None:
        row = self.conn.execute(
            f"SELECT * FROM attendance WHERE student_id = ? AND date = ? AND {_SAME_REGISTER}",
            (student_id, day.isoformat(), subject_id),
        ).fetchone()
        return _from_row(row) if row else None

    def save(self, record: AttendanceRecord) -> None:
        """Insert the record, or replace the status and note of the existing one."""
        with transaction(self.conn):
            cur = self.conn.execute(
                f"""
                UPDATE attendance SET status = ?, note = ?
                WHERE student_id = ? AND date = ? AND {_SAME_REGISTER}
                """,
                (record.status.value, record.note, record.student_id, record.date.isoformat(), record.subject_id),
            )
            if cur.rowcount == 0:
                self.conn.execute(
                    "INSERT INTO attendance (student_id, subject_id, date, status, note) VALUES (?, ?, ?, ?, ?)",
                    (record.student_id, record.subject_id, record.date.isoformat(), record.status.value, record.note),
                )

    def save_many(self, records: list[AttendanceRecord]) -> None:
        with transaction(self.conn):
            for record in records:
                self.save(record)

    def delete(self, student_id: int, day: date, subject_id: int | None) -> None:
        with transaction(self.conn):
            self.conn.execute(
                f"DELETE FROM attendance WHERE student_id = ? AND date = ? AND {_SAME_REGISTER}",
                (student_id, day.isoformat(), subject_id),
            )

    def delete_day(self, class_id: int, day: date, subject_id: int | None) -> int:
        """Remove the register of one day for the class's active students; returns how many."""
        with transaction(self.conn):
            cur = self.conn.execute(
                f"""
                DELETE FROM attendance
                WHERE date = ? AND {_SAME_REGISTER}
                  AND student_id IN (SELECT id FROM students WHERE class_id = ? AND active = 1)
                """,
                (day.isoformat(), subject_id, class_id),
            )
        return cur.rowcount

    def replace_day(
        self, class_id: int, day: date, subject_id: int | None, records: list[AttendanceRecord]
    ) -> None:
        """Make the day's register for the class's active students exactly `records`."""
        with transaction(self.conn):
            self.delete_day(class_id, day, subject_id)
            self.save_many(records)

    def for_period(
        self, class_id: int, start: date, end: date, subject_id: int | None
    ) -> list[AttendanceRecord]:
        """Records of the class's active students for days in [start, end], by date."""
        rows = self.conn.execute(
            f"""
            SELECT a.* FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE s.class_id = ? AND s.active = 1 AND a.date BETWEEN ? AND ?
              AND coalesce(a.subject_id, 0) = coalesce(?, 0)
            ORDER BY a.date, a.student_id
            """,
            (class_id, start.isoformat(), end.isoformat(), subject_id),
        )
        return [_from_row(r) for r in rows]

    def counts_by_student(
        self, class_id: int, start: date, end: date, subject_id: int | None
    ) -> dict[int, dict[str, int]]:
        """{student_id: {status: count}} for days in [start, end]."""
        rows = self.conn.execute(
            """
            SELECT a.student_id, a.status, count(*) AS n FROM attendance a
            JOIN students s ON s.id = a.student_id
            WHERE s.class_id = ? AND s.active = 1 AND a.date BETWEEN ? AND ?
              AND coalesce(a.subject_id, 0) = coalesce(?, 0)
            GROUP BY a.student_id, a.status
            """,
            (class_id, start.isoformat(), end.isoformat(), subject_id),
        )
        result: dict[int, dict[str, int]] = defaultdict(dict)
        for r in rows:
            result[r["student_id"]][r["status"]] = r["n"]
        return dict(result)
