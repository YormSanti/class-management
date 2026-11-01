"""Database backups. Uses SQLite's online backup API rather than a file copy,
so the copy is consistent even while the app has the database open in WAL mode."""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

AUTO_BACKUP_PREFIX = "classroom_"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
KEEP_AUTO_BACKUPS = 10  # the newest ones, whatever their date
KEEP_DAILY_BACKUPS = 30  # plus the last one of each of this many days

log = logging.getLogger(__name__)


def copy_database(src: Path, dest: Path) -> None:
    """Write a consistent, standalone copy of the database at `src` to `dest`.

    The copy is written to a temp file first and renamed into place, so an
    interrupted backup never leaves a half-written file under the final name.
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
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def list_auto_backups(backup_dir: Path) -> list[Path]:
    """Automatic backups, newest first."""
    if not backup_dir.is_dir():
        return []
    # Timestamps are zero-padded, so name order is chronological order.
    return sorted(backup_dir.glob(f"{AUTO_BACKUP_PREFIX}*.db"), reverse=True)


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
