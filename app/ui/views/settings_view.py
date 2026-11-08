import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.config import DB_FILENAME, RANKING_METHODS, AppConfig, prepare_data_dir, settings_dir
from app.services.backup import (
    KEEP_AUTO_BACKUPS,
    KEEP_DAILY_BACKUPS,
    BackupError,
    backup_time,
    copy_database,
    list_auto_backups,
)
from app.ui import style
from app.ui.theme import THEME_LABELS, apply_theme

RANKING_CHOICES = {
    "competition": ("Shared places skip the next place", "1, 2, 2, 4: two students share 2nd, the next is 4th"),
    "dense": ("Shared places don't skip", "1, 2, 2, 3: two students share 2nd, the next is 3rd"),
}
SHOWN_BACKUPS = 8


def _path_label(text: str) -> QLabel:
    result = QLabel(text)
    result.setWordWrap(True)
    result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return result


def _open_folder(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class SettingsView(QWidget):
    """Where the data lives, its backups, the app's look, how rankings share places, and about the app.

    `save` writes the config (config.json); None keeps changes for this session only.
    `restore` puts a backup's data in place of the current data and returns where the
    current data was saved first; None hides the Restore button.
    """

    back_up_requested = Signal()
    config_changed = Signal(object)  # AppConfig
    restored = Signal()  # the data was replaced by a backup's
    close_requested = Signal()  # the data folder changed; the app must start again to use it

    def __init__(
        self,
        config: AppConfig,
        save: Callable[[AppConfig], None] | None = None,
        restore: Callable[[Path], Path] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self.save = save
        self.restore = restore
        self._shown_backups: list[Path] = []

        # --- your data ---
        data = style.Panel("Your data", "Everything is kept in one file on this computer.")
        self.data_path_label = _path_label(str(config.db_path))
        open_data = QPushButton("Open data folder")
        open_data.clicked.connect(lambda: _open_folder(self.config.data_dir))
        back_up = QPushButton("Back up now…")
        back_up.setObjectName("Primary")
        back_up.setToolTip("Save a copy anywhere, e.g. on a USB stick (Ctrl+Shift+B)")
        back_up.clicked.connect(self.back_up_requested)
        self.move_button = QPushButton("Move data…")
        self.move_button.setToolTip("Keep your data in another folder, e.g. a synced or USB drive")
        self.move_button.clicked.connect(self.move_data)
        self.move_button.setVisible(save is not None)  # the new folder must be remembered
        data_buttons = QHBoxLayout()
        data_buttons.addWidget(open_data)
        data_buttons.addWidget(self.move_button)
        data_buttons.addStretch()
        data_buttons.addWidget(back_up)
        data.body.addWidget(style.caption("Data file"))
        data.body.addWidget(self.data_path_label)
        data.body.addLayout(data_buttons)

        # --- automatic backups ---
        backups = style.Panel(
            "Automatic backups",
            f"A copy is made every time the app starts. The {KEEP_AUTO_BACKUPS} newest are kept, "
            f"plus the last one of each of the {KEEP_DAILY_BACKUPS} most recent days.",
        )
        self.backup_summary = style.label("", bold=True)
        self.backup_table = QTableWidget(0, 2)
        self.backup_table.setHorizontalHeaderLabels(["Made", "Size"])
        self.backup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backup_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.backup_table.itemSelectionChanged.connect(self._update_restore)
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backup_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.backup_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        open_backups = QPushButton("Open backups folder")
        open_backups.clicked.connect(lambda: _open_folder(self.config.backup_dir))
        backup_buttons = QHBoxLayout()
        self.restore_button = QPushButton("Restore…")
        self.restore_button.setToolTip("Replace your data with the selected backup")
        self.restore_button.clicked.connect(self.restore_selected)
        self.restore_button.setVisible(restore is not None)
        backup_buttons.addWidget(self.backup_summary, stretch=1)
        backup_buttons.addWidget(self.restore_button)
        backup_buttons.addWidget(open_backups)
        restore_hint = style.label(
            "To go back to a backup, select it and press Restore. Your data as it is now is "
            "saved as a new backup first, so a restore can be undone the same way.",
            0.85,
            muted=True,
        )
        restore_hint.setWordWrap(True)
        backups.body.addLayout(backup_buttons)
        backups.body.addWidget(self.backup_table)
        backups.body.addWidget(restore_hint)

        # --- rankings ---
        rankings = style.Panel("Rankings", "How places are numbered when students have the same score.")
        self.ranking_group = QButtonGroup(self)
        self.ranking_buttons: dict[str, QRadioButton] = {}
        for method in RANKING_METHODS:
            title, example = RANKING_CHOICES[method]
            button = QRadioButton(title)
            self.ranking_buttons[method] = button
            self.ranking_group.addButton(button)
            hint = style.label(example, 0.85, muted=True)
            hint.setContentsMargins(24, 0, 0, 0)
            choice = QVBoxLayout()
            choice.setSpacing(2)
            choice.addWidget(button)
            choice.addWidget(hint)
            rankings.body.addLayout(choice)
        self.ranking_buttons[config.ranking_method].setChecked(True)
        self.ranking_group.buttonToggled.connect(
            lambda button, checked: checked and self._choose("ranking_method", self.ranking_buttons, button)
        )

        # --- appearance ---
        appearance = style.Panel("Appearance")
        self.theme_group = QButtonGroup(self)
        self.theme_buttons: dict[str, QRadioButton] = {}
        theme_row = QHBoxLayout()
        theme_row.setSpacing(20)
        for theme, title in THEME_LABELS.items():
            button = QRadioButton(title)
            self.theme_buttons[theme] = button
            self.theme_group.addButton(button)
            theme_row.addWidget(button)
        theme_row.addStretch()
        appearance.body.addLayout(theme_row)
        self.theme_buttons[config.theme].setChecked(True)
        self.theme_group.buttonToggled.connect(
            lambda button, checked: checked and self._choose("theme", self.theme_buttons, button)
        )

        # --- about ---
        about = style.Panel("About")
        about.body.addWidget(style.label(f"Classroom Manager {__version__}", bold=True))
        about.body.addWidget(
            style.label("Classes, attendance, grades and seating for one teacher, offline.", muted=True)
        )
        about.body.addWidget(style.caption("Settings and log file"))
        about.body.addWidget(_path_label(str(settings_dir())))
        open_settings = QPushButton("Open settings folder")
        open_settings.clicked.connect(lambda: _open_folder(settings_dir()))
        about_buttons = QHBoxLayout()
        about_buttons.addWidget(open_settings)
        about_buttons.addStretch()
        about.body.addLayout(about_buttons)

        # --- page ---
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(24, 20, 24, 24)
        column.setSpacing(16)
        column.addWidget(style.caption("Classroom Manager"))
        column.addWidget(style.label("Settings", 1.9))
        for panel in (data, backups, appearance, rankings, about):
            column.addWidget(panel)
        column.addStretch()
        content.setMaximumWidth(760)

        centered = QWidget()
        row = QHBoxLayout(centered)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(content)
        row.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(centered)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

        self._apply_style()
        self.refresh()

    # --- page interface (see MainWindow) --------------------------------------

    def set_class(self, _class_id: int | None) -> None:
        pass  # nothing here depends on the class

    def refresh(self) -> None:
        found = list_auto_backups(self.config.backup_dir)
        if found:
            newest = backup_time(found[0])
            when = f"{newest:%A} {newest.day} {newest:%B %Y}, {newest:%H:%M}" if newest else found[0].name
            self.backup_summary.setText(f"{len(found)} backup{'' if len(found) == 1 else 's'} · newest {when}")
        else:
            self.backup_summary.setText("No automatic backups yet")
        shown = found[:SHOWN_BACKUPS]
        self._shown_backups = shown
        self.backup_table.clearSelection()
        self.backup_table.setRowCount(len(shown))
        for i, path in enumerate(shown):
            made = backup_time(path)
            self.backup_table.setItem(
                i, 0, QTableWidgetItem(f"{made:%a} {made.day} {made:%b %Y}, {made:%H:%M}" if made else path.name)
            )
            try:
                size = f"{path.stat().st_size / 1024:,.0f} KB"
            except OSError:
                size = "—"
            item = QTableWidgetItem(size)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.backup_table.setItem(i, 1, item)
        self.backup_table.setVisible(bool(shown))
        header = self.backup_table.horizontalHeader().height()
        rows = sum(self.backup_table.rowHeight(i) for i in range(len(shown)))
        self.backup_table.setFixedHeight(header + rows + 2 * self.backup_table.frameWidth())
        self._update_restore()

    def move_data(self) -> None:
        """Copy the data into another folder (or switch to the data already there), remember
        that folder and close the app, which then opens on the new folder."""
        if self.save is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Move data to", str(self.config.data_dir.parent))
        if not folder:
            return
        new_dir = Path(folder)
        if new_dir.resolve() == self.config.data_dir.resolve():
            QMessageBox.information(self, "Move data", "Your data is already in that folder.")
            return
        target = new_dir / DB_FILENAME
        if target.exists():
            question = (
                f"{new_dir} already has Classroom Manager data.\n\nSwitch to the data in that folder? "
                "Your current data stays where it is, untouched."
            )
        else:
            question = (
                f"Copy your data to {new_dir} and use it from there?\n\nThe current data file stays "
                "where it is as a spare copy. The app closes afterwards; open it again to continue."
            )
        if QMessageBox.question(self, "Move data", question) != QMessageBox.StandardButton.Yes:
            return
        if not target.exists():
            try:
                prepare_data_dir(new_dir)
                copy_database(self.config.db_path, target)
            except (OSError, sqlite3.Error) as exc:
                QMessageBox.warning(self, "Move data", f"Your data could not be copied there:\n{exc}")
                return
        changed = replace(self.config, data_dir=new_dir)
        try:
            self.save(changed)
        except OSError as exc:
            QMessageBox.warning(self, "Move data", f"The new folder could not be remembered:\n{exc}")
            return
        self.config = changed
        self.config_changed.emit(changed)
        QMessageBox.information(
            self, "Move data", f"Your data is now kept in\n{new_dir}\n\nThe app will close; open it again to continue."
        )
        self.close_requested.emit()

    def _selected_backup(self) -> Path | None:
        rows = self.backup_table.selectionModel().selectedRows()
        return self._shown_backups[rows[0].row()] if rows else None

    def _update_restore(self) -> None:
        self.restore_button.setEnabled(self._selected_backup() is not None)

    def restore_selected(self) -> None:
        """Ask, then replace the data with the selected backup's."""
        backup = self._selected_backup()
        if backup is None or self.restore is None:
            return
        made = backup_time(backup)
        when = f"{made:%A} {made.day} {made:%B %Y} at {made:%H:%M}" if made else backup.name
        answer = QMessageBox.question(
            self,
            "Restore backup",
            f"Replace all your data with the backup made on {when}?\n\n"
            "Your data as it is now is saved as a new backup first, so you can go back to it.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.restore(backup)
        except (BackupError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Restore backup", f"The backup could not be restored:\n{exc}")
            self.refresh()
            return
        self.refresh()
        self.restored.emit()
        QMessageBox.information(
            self,
            "Restore backup",
            f"Your data is back as it was on {when}.\n\n"
            "The data from just before is the newest backup in the list.",
        )

    # --- changes ---------------------------------------------------------------

    def _choose(self, field: str, buttons: dict[str, QRadioButton], button: QRadioButton) -> None:
        """Save the option picked with `button` as the config's `field`, and use it."""
        value = next(v for v, b in buttons.items() if b is button)
        if value == getattr(self.config, field):
            return
        changed = replace(self.config, **{field: value})
        if self.save is not None:
            try:
                self.save(changed)
            except OSError as exc:
                QMessageBox.warning(self, "Settings", f"The setting could not be saved:\n{exc}")
                buttons[getattr(self.config, field)].setChecked(True)  # put it back
                return
        self.config = changed
        if field == "theme" and (app := QApplication.instance()) is not None:
            apply_theme(app, value)
        self.config_changed.emit(changed)

    # --- Qt events -------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()  # a backup may have been made since

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(style.card_stylesheet(self))
