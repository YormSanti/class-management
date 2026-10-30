import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db.connection import connect, init_db
from app.repositories.class_repo import ClassRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.roster import RosterService


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "classroom.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    # A real file (not :memory:) so WAL mode behaves as it does in the app.
    conn = connect(db_path)
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def roster(conn: sqlite3.Connection) -> RosterService:
    return RosterService(ClassRepository(conn), StudentRepository(conn), SubjectRepository(conn))
