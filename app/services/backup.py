"""Database backups. Uses SQLite's online backup API rather than a file copy,
so the copy is consistent even while the app has the database open in WAL mode."""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

AUTO_BACKUP_PREFIX = "classroom_"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
KEEP_AUTO_BACKUPS = 10

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


def prune_auto_backups(backup_dir: Path, keep: int = KEEP_AUTO_BACKUPS) -> list[Path]:
    """Delete all but the `keep` newest automatic backups. Returns the removed paths."""
    removed = []
    for old in list_auto_backups(backup_dir)[keep:]:
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
) -> Path | None:
    """Back up the database into `backup_dir` with a timestamped name and prune old copies.

    Returns the new backup's path, or None if there is no database yet.
    """
    if not db_path.exists():
        return None
    stamp = (now or datetime.now()).strftime(TIMESTAMP_FORMAT)
    dest = backup_dir / f"{AUTO_BACKUP_PREFIX}{stamp}.db"
    copy_database(db_path, dest)
    prune_auto_backups(backup_dir, keep)
    log.info("Automatic backup written to %s", dest)
    return dest
