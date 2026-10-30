import sqlite3
from pathlib import Path

import pytest

from app.db.connection import SCHEMA_VERSION, connect, init_db, transaction

TABLES = {
    "classes",
    "subjects",
    "students",
    "attendance",
    "categories",
    "assignments",
    "scores",
    "seat_layouts",
    "seats",
}


def test_connection_uses_wal_and_foreign_keys(conn: sqlite3.Connection):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_schema_creates_all_tables(conn: sqlite3.Connection):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    assert TABLES <= {r["name"] for r in rows}
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_init_db_is_idempotent(conn: sqlite3.Connection):
    conn.execute("INSERT INTO classes (name) VALUES ('7B')")
    init_db(conn)
    assert conn.execute("SELECT count(*) FROM classes").fetchone()[0] == 1


def test_newer_schema_is_refused(conn: sqlite3.Connection):
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError):
        init_db(conn)


def test_foreign_keys_are_enforced(conn: sqlite3.Connection):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO students (class_id, first_name, last_name) VALUES (999, 'A', 'B')")


def test_transaction_rolls_back_on_error(conn: sqlite3.Connection):
    with pytest.raises(ZeroDivisionError):
        with transaction(conn):
            conn.execute("INSERT INTO classes (name) VALUES ('7B')")
            1 / 0
    assert conn.execute("SELECT count(*) FROM classes").fetchone()[0] == 0
    assert not conn.in_transaction


def test_nested_transaction_joins_outer(conn: sqlite3.Connection):
    with pytest.raises(ZeroDivisionError):
        with transaction(conn):
            with transaction(conn):
                conn.execute("INSERT INTO classes (name) VALUES ('inner')")
            conn.execute("INSERT INTO classes (name) VALUES ('outer')")
            1 / 0
    # The inner block did not commit on its own; everything was rolled back.
    assert conn.execute("SELECT count(*) FROM classes").fetchone()[0] == 0


def test_committed_data_survives_reopen(db_path: Path, conn: sqlite3.Connection):
    with transaction(conn):
        conn.execute("INSERT INTO classes (name) VALUES ('7B')")
    other = connect(db_path)
    try:
        assert other.execute("SELECT name FROM classes").fetchone()["name"] == "7B"
    finally:
        other.close()


def test_null_score_is_distinct_from_zero(conn: sqlite3.Connection):
    conn.execute("INSERT INTO classes (id, name) VALUES (1, '7B')")
    conn.execute("INSERT INTO students (id, class_id, first_name, last_name) VALUES (1, 1, 'A', 'B')")
    conn.execute("INSERT INTO subjects (id, class_id, name) VALUES (1, 1, 'Maths')")
    conn.execute("INSERT INTO categories (id, subject_id, name, weight) VALUES (1, 1, 'Homework', 20)")
    conn.execute(
        "INSERT INTO assignments (id, subject_id, category_id, title, max_score) VALUES (1, 1, 1, 'HW1', 10)"
    )
    conn.execute("INSERT INTO scores (assignment_id, student_id, score) VALUES (1, 1, NULL)")
    with pytest.raises(sqlite3.IntegrityError):  # one score per student per assignment
        conn.execute("INSERT INTO scores (assignment_id, student_id, score) VALUES (1, 1, 0)")
    assert conn.execute("SELECT score FROM scores").fetchone()["score"] is None
