import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.db.connection import transaction
from app.services.backup import auto_backup, copy_database, list_auto_backups


def _class_names(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT name FROM classes ORDER BY name")]
    finally:
        conn.close()


def test_no_backup_before_database_exists(tmp_path: Path):
    assert auto_backup(tmp_path / "classroom.db", tmp_path / "backups") is None
    assert not (tmp_path / "backups").exists()


def test_backup_includes_uncheckpointed_wal_data(
    db_path: Path, conn: sqlite3.Connection, tmp_path: Path
):
    # With the connection still open, recent writes may only be in the -wal file.
    with transaction(conn):
        conn.execute("INSERT INTO classes (name) VALUES ('7B')")

    dest = auto_backup(db_path, tmp_path / "backups", now=datetime(2026, 9, 1, 8, 0, 0))

    assert dest == tmp_path / "backups" / "classroom_2026-09-01_08-00-00.db"
    assert _class_names(dest) == ["7B"]
    assert not dest.with_name(dest.name + "-wal").exists()  # standalone file


def test_auto_backup_keeps_ten_newest_of_one_day(db_path: Path, conn: sqlite3.Connection, tmp_path: Path):
    backup_dir = tmp_path / "backups"
    start = datetime(2026, 9, 1, 8, 0, 0)
    for minute in range(12):
        auto_backup(db_path, backup_dir, now=start + timedelta(minutes=minute))

    names = [p.name for p in list_auto_backups(backup_dir)]
    assert len(names) == 10
    assert names[0] == "classroom_2026-09-01_08-11-00.db"
    assert names[-1] == "classroom_2026-09-01_08-02-00.db"


def test_many_starts_in_one_day_keep_earlier_days(db_path: Path, conn: sqlite3.Connection, tmp_path: Path):
    backup_dir = tmp_path / "backups"
    auto_backup(db_path, backup_dir, now=datetime(2026, 8, 28, 9, 0, 0))
    auto_backup(db_path, backup_dir, now=datetime(2026, 8, 28, 15, 0, 0))
    for minute in range(20):
        auto_backup(db_path, backup_dir, now=datetime(2026, 9, 1, 8, minute, 0))

    names = [p.name for p in list_auto_backups(backup_dir)]
    assert len(names) == 11  # ten from today, plus the last one of 28 August
    assert names[-1] == "classroom_2026-08-28_15-00-00.db"


def test_backups_to_remove_keeps_one_per_day_for_limited_days(tmp_path: Path):
    from app.services.backup import backups_to_remove

    backups = [tmp_path / f"classroom_2026-09-{day:02d}_{hour:02d}-00-00.db" for day in (5, 4, 3, 2, 1) for hour in (18, 9)]
    removed = backups_to_remove(backups, keep=1, keep_days=3)
    kept = [p.name for p in backups if p not in removed]
    assert kept == [
        "classroom_2026-09-05_18-00-00.db",
        "classroom_2026-09-04_18-00-00.db",
        "classroom_2026-09-03_18-00-00.db",
    ]


def test_pruning_ignores_other_files(db_path: Path, conn: sqlite3.Connection, tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    manual = backup_dir / "before-term-2.db"
    manual.write_bytes(b"keep me")
    auto_backup(db_path, backup_dir, keep=1)
    assert manual.exists()


def test_copy_database_replaces_existing_file(db_path: Path, conn: sqlite3.Connection, tmp_path: Path):
    dest = tmp_path / "usb" / "copy.db"
    copy_database(db_path, dest)
    with transaction(conn):
        conn.execute("INSERT INTO classes (name) VALUES ('8A')")
    copy_database(db_path, dest)
    assert _class_names(dest) == ["8A"]
    assert not dest.with_name("copy.db.tmp").exists()
