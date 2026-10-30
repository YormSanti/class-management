"""Classroom Manager entry point: resolve the data folder, back up, open the DB, show the UI."""

import logging
import sqlite3
import sys
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.config import (
    APP_NAME,
    AppConfig,
    default_data_dir,
    load_config,
    prepare_data_dir,
    save_config,
    settings_dir,
)
from app.db.connection import connect, init_db
from app.repositories.class_repo import ClassRepository
from app.repositories.dashboard_repo import DashboardRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository
from app.services.backup import auto_backup
from app.services.dashboard import DashboardService
from app.services.roster import RosterService
from app.ui.dialogs.setup_dialog import SetupDialog
from app.ui.main_window import MainWindow

log = logging.getLogger("classroom")


def _setup_logging() -> None:
    """Log to stderr and to a local rotating file in the settings folder."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        settings_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                settings_dir() / "classroom.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
        )
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def _install_excepthook() -> None:
    """Show unexpected errors instead of failing silently. Writes are transactional,
    so a failed action has already been rolled back when this runs."""

    def hook(exc_type, exc, tb) -> None:
        log.error("Unhandled error", exc_info=(exc_type, exc, tb))
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None,
                "Unexpected error",
                f"{exc_type.__name__}: {exc}\n\nNo partial changes were saved. "
                f"Details are in the log file in {settings_dir()}.",
            )

    sys.excepthook = hook


def _choose_data_dir(message: str = "", current: Path | None = None) -> Path | None:
    """Show the setup dialog until a usable folder is chosen. None = user quit."""
    while True:
        dialog = SetupDialog(default_data_dir(), current, message)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        chosen = dialog.chosen_dir()
        try:
            prepare_data_dir(chosen)
            return chosen
        except OSError as exc:
            QMessageBox.critical(None, "Can't use this folder", f"{chosen}\n\n{exc}")
            current = chosen


def _resolve_config() -> AppConfig | None:
    """Load config.json, running first-launch setup or recovery if needed."""
    config = load_config()
    if config is None:
        data_dir = _choose_data_dir()
        if data_dir is None:
            return None
        config = AppConfig(data_dir=data_dir)
        save_config(config)
        return config

    if not config.data_dir.is_dir():
        # e.g. a USB drive that isn't plugged in. Don't silently create an empty database.
        data_dir = _choose_data_dir(
            message=(
                f"The data folder {config.data_dir} can't be found. If it is on a USB or "
                "network drive, connect it and choose it again, or pick another folder."
            ),
            current=config.data_dir,
        )
        if data_dir is None:
            return None
        config = replace(config, data_dir=data_dir)
        save_config(config)
    return config


def main() -> int:
    _setup_logging()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("Classroom Manager")
    _install_excepthook()

    config = _resolve_config()
    if config is None:
        return 0

    try:
        auto_backup(config.db_path, config.backup_dir)
    except (OSError, sqlite3.Error) as exc:
        log.exception("Automatic backup failed")
        QMessageBox.warning(
            None,
            "Backup failed",
            f"The automatic backup could not be created:\n{exc}\n\n"
            "The app will continue, but consider making a manual backup.",
        )

    try:
        conn = connect(config.db_path)
        init_db(conn)
    except (sqlite3.Error, RuntimeError) as exc:
        log.exception("Could not open database")
        QMessageBox.critical(
            None,
            "Can't open database",
            f"{config.db_path}\n\n{exc}\n\nAutomatic backups are in {config.backup_dir}.",
        )
        return 1

    students = StudentRepository(conn)
    subjects = SubjectRepository(conn)
    roster = RosterService(ClassRepository(conn), students, subjects)
    dashboard = DashboardService(DashboardRepository(conn), students, subjects)
    window = MainWindow(roster, dashboard, config)
    window.show()
    try:
        return app.exec()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
