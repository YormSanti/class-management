import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
SCHEMA_VERSION = 2


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
    """Upgrade an older database, create missing tables and record the schema version.

    Safe on every start. A new database (version 0) gets schema.sql directly;
    an older one runs each `migrations/NNN_*.sql` up to SCHEMA_VERSION first.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"This database was created by a newer version of the app "
            f"(schema {version}, this app supports {SCHEMA_VERSION})."
        )
    if version > 0:
        for target in range(version + 1, SCHEMA_VERSION + 1):
            _migrate(conn, target)
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


def _migrate(conn: sqlite3.Connection, target: int) -> None:
    """Upgrade the database to version `target` in one transaction, or not at all.

    Migrations rebuild tables, so foreign keys are switched off while they run
    (the procedure in https://sqlite.org/lang_altertable.html) and every
    reference is checked before committing.
    """
    (script_path,) = MIGRATIONS_DIR.glob(f"{target:03d}_*.sql")
    conn.execute("PRAGMA foreign_keys = OFF")  # has no effect inside a transaction
    try:
        # executescript runs the BEGIN and leaves the transaction open for the checks below.
        conn.executescript("BEGIN;\n" + script_path.read_text(encoding="utf-8"))
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(
                f"Upgrading the database to version {target} would break "
                f"{len(broken)} reference(s); nothing was changed."
            )
        conn.execute(f"PRAGMA user_version = {target}")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
