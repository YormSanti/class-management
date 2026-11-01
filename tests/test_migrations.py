import sqlite3
from pathlib import Path

import pytest

from app.db.connection import SCHEMA_VERSION, connect, init_db

SCHEMA_V1 = Path(__file__).with_name("data") / "schema_v1.sql"


def _v1_database(path: Path) -> sqlite3.Connection:
    """A database exactly as version 1 of the app created it, with some data."""
    conn = connect(path)
    conn.executescript(SCHEMA_V1.read_text(encoding="utf-8") + "\nPRAGMA user_version = 1;")
    conn.executescript(
        """
        INSERT INTO classes (id, name, subject, term) VALUES (1, '7B', 'Maths', 'T1'), (2, '8A', '', '');
        INSERT INTO students (id, class_id, first_name, last_name) VALUES (1, 1, 'Ada', 'L'), (2, 2, 'Alan', 'T');
        INSERT INTO categories (id, class_id, name, weight) VALUES (10, 1, 'Tests', 40), (20, 2, 'Tests', 50);
        INSERT INTO assignments (id, class_id, category_id, title, date, max_score)
            VALUES (100, 1, 10, 'Unit 1', '2026-10-01', 50), (200, 2, 20, 'Quiz', NULL, 10);
        INSERT INTO scores (assignment_id, student_id, score) VALUES (100, 1, 45), (200, 2, NULL);
        INSERT INTO attendance (student_id, date, status, note) VALUES (1, '2026-10-01', 'late', 'bus');
        INSERT INTO seat_layouts (id, class_id, name, rows, cols) VALUES (1, 1, 'Default', 5, 6);
        INSERT INTO seats (layout_id, row, col, student_id) VALUES (1, 0, 0, 1);
        """
    )
    return conn


def _schema(conn: sqlite3.Connection) -> dict[str, object]:
    """Columns, foreign keys and indexes of every table, for comparing two databases."""
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {
        t: (
            [tuple(r)[1:] for r in conn.execute(f"PRAGMA table_info({t})")],
            sorted(tuple(r)[2:] for r in conn.execute(f"PRAGMA foreign_key_list({t})")),
            sorted(
                (r["name"], r["unique"], tuple(c[2] for c in conn.execute(f"PRAGMA index_xinfo({r['name']})")))
                for r in conn.execute(f"PRAGMA index_list({t})")
            ),
        )
        for t in sorted(tables)
    }


def test_v1_database_is_upgraded(tmp_path: Path):
    conn = _v1_database(tmp_path / "old.db")
    init_db(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

    subjects = {r["class_id"]: (r["id"], r["name"]) for r in conn.execute("SELECT * FROM subjects")}
    assert {c: name for c, (_id, name) in subjects.items()} == {1: "Maths", 2: "General"}
    maths, general = subjects[1][0], subjects[2][0]

    categories = conn.execute("SELECT id, subject_id, name, weight FROM categories ORDER BY id")
    assert [tuple(r) for r in categories] == [(10, maths, "Tests", 40), (20, general, "Tests", 50)]
    assignments = conn.execute("SELECT id, subject_id, category_id, date FROM assignments ORDER BY id")
    assert [tuple(r) for r in assignments] == [(100, maths, 10, "2026-10-01"), (200, general, 20, None)]
    scores = conn.execute("SELECT assignment_id, score FROM scores ORDER BY assignment_id")
    assert [tuple(r) for r in scores] == [(100, 45), (200, None)]
    attendance = conn.execute("SELECT student_id, subject_id, status, note FROM attendance").fetchall()
    assert [tuple(r) for r in attendance] == [(1, None, "late", "bus")]
    assert conn.execute("SELECT count(*) FROM seats").fetchone()[0] == 1
    assert [tuple(r) for r in conn.execute("SELECT * FROM classes ORDER BY id")] == [(1, "7B", "T1"), (2, "8A", "")]


def test_upgraded_schema_matches_new_database(tmp_path: Path):
    old = _v1_database(tmp_path / "old.db")
    init_db(old)
    new = connect(tmp_path / "new.db")
    init_db(new)
    assert _schema(old) == _schema(new)


def test_upgrade_is_idempotent(tmp_path: Path):
    conn = _v1_database(tmp_path / "old.db")
    init_db(conn)
    init_db(conn)
    assert conn.execute("SELECT count(*) FROM subjects").fetchone()[0] == 2


def test_failed_upgrade_changes_nothing(tmp_path: Path):
    conn = _v1_database(tmp_path / "old.db")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO scores (assignment_id, student_id, score) VALUES (100, 999, 1)")  # orphan
    conn.execute("PRAGMA foreign_keys = ON")

    with pytest.raises(RuntimeError, match="nothing was changed"):
        init_db(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "subject" in [r["name"] for r in conn.execute("PRAGMA table_info(classes)")]
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'subjects'").fetchone() is None
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not conn.in_transaction
