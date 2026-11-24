"""Database backups. Uses SQLite's online backup API rather than a file copy,
so the copy is consistent even while the app has the database open in WAL mode."""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from app.db.connection import SCHEMA_VERSION, find_problems, init_db

AUTO_BACKUP_PREFIX = "classroom_"
BEFORE_RESTORE_SUFFIX = "-before-restore"  # marks the copy of the data made just before a restore
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
KEEP_AUTO_BACKUPS = 10  # the newest ones, whatever their date
KEEP_DAILY_BACKUPS = 30  # plus the last one of each of this many days
REQUIRED_TABLES = {"classes", "students", "attendance"}  # in the data of every version
REMIND_AFTER_DAYS = 30  # suggest "Back up now" when no copy was saved elsewhere for this long

log = logging.getLogger(__name__)


class BackupError(Exception):
    """A user-facing error; the message is safe to show in the UI."""


def copy_database(src: Path, dest: Path) -> None:
    """Write a consistent, standalone copy of the database at `src` to `dest`.

    The copy is written to a temp file first, checked with SQLite's quick check and
    only then renamed into place, so a failed or damaged copy never ends up under the
    final name (or replaces a good older one). Raises sqlite3.DatabaseError if the
    check fails.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        src_conn = sqlite3.connect(src)
        try:
            dest_conn = sqlite3.connect(tmp)
            try:
                src_conn.backup(dest_conn)
                # Single-file journal so the copy is self-contained (no -wal/-shm files).
                dest_conn.execute("PRAGMA journal_mode = DELETE")
            finally:
                dest_conn.close()
        finally:
            src_conn.close()
        if problems := find_problems(tmp):
            raise sqlite3.DatabaseError(f"The copy failed its check: {problems[0]}")
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def manual_backup_reminder(last: datetime | None, now: datetime) -> str | None:
    """A nudge to save a copy elsewhere (automatic backups sit on the same disk as the
    data), or None while the last manual backup is recent enough."""
    if last is None:
        return "Your data has never been backed up elsewhere."
    days = (now - last).days
    if days < REMIND_AFTER_DAYS:
        return None
    return f"Your data was last backed up elsewhere {days} days ago."


def list_auto_backups(backup_dir: Path) -> list[Path]:
    """Automatic backups, newest first."""
    if not backup_dir.is_dir():
        return []
    # Timestamps are zero-padded, so name order is chronological order.
    return sorted(backup_dir.glob(f"{AUTO_BACKUP_PREFIX}*.db"), reverse=True)


def backup_time(path: Path) -> datetime | None:
    """When an automatic backup was made, read from its name; None if the name isn't one of ours."""
    stamp = path.stem[len(AUTO_BACKUP_PREFIX) :].removesuffix(BEFORE_RESTORE_SUFFIX)
    try:
        return datetime.strptime(stamp, TIMESTAMP_FORMAT)
    except ValueError:
        return None


def is_before_restore(path: Path) -> bool:
    """True for the copy of the data that restore_backup() saved just before a restore."""
    return path.stem.endswith(BEFORE_RESTORE_SUFFIX)


def _backup_day(path: Path) -> str:
    """"2026-09-01" from "classroom_2026-09-01_08-00-00.db"."""
    return path.name[len(AUTO_BACKUP_PREFIX) : len(AUTO_BACKUP_PREFIX) + 10]


def backups_to_remove(backups: list[Path], keep: int, keep_days: int) -> list[Path]:
    """Which of `backups` (newest first) to delete: all but the `keep` newest and the
    last backup of each of the `keep_days` most recent days.

    So starting the app many times in one day can't push out last week's backups.
    """
    kept = set(backups[:keep])
    days: set[str] = set()
    for path in backups:
        day = _backup_day(path)
        if day not in days and len(days) < keep_days:
            days.add(day)
            kept.add(path)
    return [p for p in backups if p not in kept]


def prune_auto_backups(
    backup_dir: Path, keep: int = KEEP_AUTO_BACKUPS, keep_days: int = KEEP_DAILY_BACKUPS
) -> list[Path]:
    """Delete old automatic backups (see backups_to_remove). Returns the removed paths."""
    removed = []
    for old in backups_to_remove(list_auto_backups(backup_dir), keep, keep_days):
        try:
            old.unlink()
            removed.append(old)
        except OSError as exc:
            log.warning("Could not remove old backup %s: %s", old, exc)
    return removed


def auto_backup(
    db_path: Path,
    backup_dir: Path,
    keep: int = KEEP_AUTO_BACKUPS,
    now: datetime | None = None,
    keep_days: int = KEEP_DAILY_BACKUPS,
) -> Path | None:
    """Back up the database into `backup_dir` with a timestamped name and prune old copies.

    Returns the new backup's path, or None if there is no database yet.
    """
    if not db_path.exists():
        return None
    stamp = (now or datetime.now()).strftime(TIMESTAMP_FORMAT)
    dest = backup_dir / f"{AUTO_BACKUP_PREFIX}{stamp}.db"
    copy_database(db_path, dest)
    prune_auto_backups(backup_dir, keep, keep_days)
    log.info("Automatic backup written to %s", dest)
    return dest


def restore_backup(backup: Path, conn: sqlite3.Connection, db_path: Path, backup_dir: Path) -> Path:
    """Replace the data in the open database `conn` (the file `db_path`) with `backup`.

    The current data is first saved as a new automatic backup, returned, so the restore
    can itself be undone. Nothing is pruned, so the backup being restored stays put.
    Raises BackupError if the backup is damaged, from a newer version of the app or
    not the app's data at all (e.g. another program's SQLite file).
    """
    if problems := find_problems(backup):
        raise BackupError(f"This backup is damaged and can't be restored:\n{problems[0]}")
    check = sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        version = check.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        check.close()
    if version > SCHEMA_VERSION:
        raise BackupError("This backup was made by a newer version of the app.")
    # Every version of the app numbers its data and has these tables; another program's
    # SQLite file would otherwise replace the data with nothing the app can use.
    if version < 1 or not REQUIRED_TABLES <= tables:
        raise BackupError("This file isn't Classroom Manager data, so it can't be restored.")

    stamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    safety = backup_dir / f"{AUTO_BACKUP_PREFIX}{stamp}{BEFORE_RESTORE_SUFFIX}.db"
    copy_database(db_path, safety)

    source = sqlite3.connect(backup)
    try:
        source.backup(conn)
    finally:
        source.close()
    init_db(conn)  # an older backup is brought up to date
    log.info("Restored %s (current data saved to %s)", backup, safety)
    return safety
