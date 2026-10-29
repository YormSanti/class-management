import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def connect(db_path: str | Path = ":memory:") -> sqlite3.Connection:
    """Open the database with WAL journaling, foreign keys and dict-like rows.

    The connection is in autocommit mode (isolation_level=None); every write
    goes through `transaction()` so the BEGIN/COMMIT boundaries are explicit.
    """
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block of writes atomically: commit on success, roll back on any error.

    Nested use joins the outer transaction, so a service can group several
    repository calls into one unit of work.
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init_db(conn: sqlite3.Connection) -> None:
    """Create missing tables and record the schema version. Safe on every start."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"This database was created by a newer version of the app "
            f"(schema {version}, this app supports {SCHEMA_VERSION})."
        )
    # executescript doesn't use `transaction()`, so wrap the DDL explicitly.
    try:
        conn.executescript(
            "BEGIN;\n"
            + SCHEMA_PATH.read_text(encoding="utf-8")
            + f"\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;"
        )
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
