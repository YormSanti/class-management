from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSettings, QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.config import AppConfig
from app.services.attendance import AttendanceService
from app.services.backup import copy_database
from app.services.dashboard import DashboardService
from app.services.roster import RosterError, RosterService
from app.ui.dialogs.class_dialog import ClassDialog
from app.ui.dialogs.new_year_dialog import NewYearDialog
from app.ui.dialogs.subject_dialog import SubjectDialog
from app.ui.views.attendance_view import AttendanceView
from app.ui.views.classes_view import ClassesView
from app.ui.views.dashboard_view import DashboardView
from app.ui.views.placeholder_view import PlaceholderView
from app.ui.views.settings_view import SettingsView

BOTTOM_PAGES = ("Settings",)  # pinned to the bottom of the sidebar


class MainWindow(QMainWindow):
    """Sidebar navigation and a stack of pages.

    The window keeps the current class and subject, which are chosen on the
    Classes page and shown in the title bar. Every page implements
    `set_class(class_id | None)` and is told whenever the class changes. Pages
    that work per subject (e.g. the gradebook) also implement `set_subject(subject_id | None)`.
    """

    def __init__(
        self,
        roster: RosterService,
        dashboard: DashboardService,
        attendance: AttendanceService,
        config: AppConfig,
        settings: QSettings | None = None,
        save_config: Callable[[AppConfig], None] | None = None,
    ):
        """`settings` keeps window state between sessions; None remembers nothing.
        `save_config` writes changes made on the Settings page; None keeps them for this session."""
        super().__init__()
        self.roster = roster
        self.config = config
        self.settings = settings
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self._last_subject: dict[int, int] = {}  # class id -> subject picked in it this session
        self.resize(1100, 700)

        # --- pages ---
        self.dashboard_view = DashboardView(dashboard, roster)
        self.dashboard_view.create_class_requested.connect(lambda: self.new_class())
        self.dashboard_view.navigate_requested.connect(self.show_page)
        self.dashboard_view.manage_subjects_requested.connect(self.show_subjects)
        self.attendance_view = AttendanceView(attendance, roster)
        self.attendance_view.class_selected.connect(self.select_class)
        self.settings_view = SettingsView(config, save_config)
        self.settings_view.back_up_requested.connect(self.back_up_now)
        self.settings_view.config_changed.connect(lambda changed: setattr(self, "config", changed))
        self.classes_view = ClassesView(roster)
        self.classes_view.roster_view.create_class_requested.connect(lambda: self.new_class())
        self.classes_view.class_selected.connect(self.select_class)
        self.classes_view.subject_selected.connect(self.select_subject)
        self.classes_view.new_class_requested.connect(lambda term: self.new_class(term))
        self.classes_view.new_year_requested.connect(self.start_new_year)
        self.classes_view.edit_class_requested.connect(self.edit_class)
        self.classes_view.delete_class_requested.connect(self.delete_class)
        self.classes_view.new_subject_requested.connect(self.new_subject)
        self.classes_view.edit_subject_requested.connect(self.edit_subject)
        self.classes_view.delete_subject_requested.connect(self.delete_subject)
        self.pages: list[tuple[str, QWidget]] = [
            ("Dashboard", self.dashboard_view),
            ("Attendance", self.attendance_view),
            ("Gradebook", PlaceholderView("Gradebook", "Coming in Phase 3.")),
            ("Rankings", PlaceholderView("Rankings", "Coming in Phase 4.")),
            ("Seating", PlaceholderView("Seating chart", "Coming in Phase 5.")),
            ("Manage classes", self.classes_view),
            ("Settings", self.settings_view),
        ]
        self.stack = QStackedWidget()
        for _name, page in self.pages:
            self.stack.addWidget(page)

        # --- sidebar ---
        # Two lists sharing one selection: the pages at the top, Settings at the bottom.
        self.nav = QListWidget()
        self.nav_bottom = QListWidget()
        for index, (name, _page) in enumerate(self.pages):
            keys = QKeySequence(f"Ctrl+{index + 1}")
            item = QListWidgetItem(name)
            item.setToolTip(f"{name} ({keys.toString(QKeySequence.SequenceFormat.NativeText)})")
            item.setData(Qt.ItemDataRole.UserRole, index)
            (self.nav_bottom if name in BOTTOM_PAGES else self.nav).addItem(item)
            QShortcut(keys, self, activated=lambda index=index: self.go_to(index))
        for nav in (self.nav, self.nav_bottom):
            # Follow the selection, not the current item: Qt moves the current item
            # (without selecting it) when an empty list gets focus.
            nav.itemSelectionChanged.connect(lambda nav=nav: self._nav_picked(nav))
        self.nav_bottom.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_bottom.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.nav_bottom.setFixedHeight(
            self.nav_bottom.sizeHintForRow(0) * self.nav_bottom.count() + 2 * self.nav_bottom.frameWidth()
        )

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(self.nav, stretch=1)
        sidebar_layout.addWidget(self.nav_bottom)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(sidebar)
        self.splitter.addWidget(self.stack)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 880])
        self.splitter.setCollapsible(0, False)
        self.setCentralWidget(self.splitter)
        self._restore_window_state()

        self.statusBar().showMessage(f"Data file: {config.db_path}")
        self._build_menus()

        self.go_to(0)
        # Read both before select_class() picks (and saves) a subject of its own.
        saved_class, saved_subject = self._saved_id("class_id"), self._saved_id("subject_id")
        self.select_class(saved_class)
        if saved_subject is not None:
            self.select_subject(saved_subject)

    # --- menus ---------------------------------------------------------------

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        backup = file_menu.addAction("&Back up now…", self.back_up_now)
        backup.setShortcut(QKeySequence("Ctrl+Shift+B"))
        file_menu.addAction("&Open data folder", self.open_data_folder)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("&Quit", self.close)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("&About Classroom Manager", self.show_about)

    def back_up_now(self) -> None:
        """Save a copy of the database wherever the teacher likes, e.g. a USB stick."""
        # Not "classroom_…": that prefix marks automatic backups, which get pruned.
        start = Path.home() / f"Classroom backup {date.today().isoformat()}.db"
        path, _filter = QFileDialog.getSaveFileName(
            self, "Back up now", str(start), "Classroom Manager backups (*.db)"
        )
        if not path:
            return
        dest = Path(path) if path.lower().endswith(".db") else Path(path + ".db")
        if dest.resolve() == self.config.db_path.resolve():
            QMessageBox.warning(self, "Back up now", "Choose another file than the data file itself.")
            return
        try:
            copy_database(self.config.db_path, dest)
        except OSError as exc:
            QMessageBox.warning(self, "Back up now", f"The backup could not be saved:\n{exc}")
            return
        self.statusBar().showMessage(f"Backup saved to {dest}", 10_000)

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config.data_dir)))

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Classroom Manager",
            f"<h3>Classroom Manager {__version__}</h3>"
            "<p>Classes, attendance, grades and seating for one teacher, offline.</p>"
            f"<p>Data file:<br>{self.config.db_path}</p>"
            f"<p>Automatic backups:<br>{self.config.backup_dir}</p>",
        )

    # --- window state --------------------------------------------------------

    def _restore_window_state(self) -> None:
        if self.settings is None:
            return
        if geometry := self.settings.value("window/geometry"):
            self.restoreGeometry(geometry)
        if splitter := self.settings.value("window/splitter"):
            self.splitter.restoreState(splitter)

    def _saved_id(self, key: str) -> int | None:
        """A class or subject id saved last session, if any."""
        value = self.settings.value(f"session/{key}") if self.settings is not None else None
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _save_selection(self) -> None:
        if self.settings is not None:
            self.settings.setValue("session/class_id", "" if self.class_id is None else self.class_id)
            self.settings.setValue("session/subject_id", "" if self.subject_id is None else self.subject_id)

    def closeEvent(self, event) -> None:
        if self.settings is not None:
            self.settings.setValue("window/geometry", self.saveGeometry())
            self.settings.setValue("window/splitter", self.splitter.saveState())
            self.settings.sync()
        super().closeEvent(event)

    def go_to(self, index: int) -> None:
        """Show page `index` of `self.pages` and highlight it in the sidebar."""
        self.stack.setCurrentIndex(index)
        for nav in (self.nav, self.nav_bottom):
            rows = [r for r in range(nav.count()) if nav.item(r).data(Qt.ItemDataRole.UserRole) == index]
            with QSignalBlocker(nav):
                if rows:
                    nav.setCurrentRow(rows[0])
                else:
                    nav.clearSelection()

    def _nav_picked(self, nav: QListWidget) -> None:
        if selected := nav.selectedItems():
            self.go_to(selected[0].data(Qt.ItemDataRole.UserRole))

    def show_page(self, name: str) -> None:
        for index, (page_name, _page) in enumerate(self.pages):
            if page_name == name:
                self.go_to(index)
                return

    def show_subjects(self) -> None:
        """Open Manage classes on the Subjects tab of the current class."""
        self.show_page("Manage classes")
        self.classes_view.tabs.setCurrentWidget(self.classes_view.subject_box)

    # --- classes -------------------------------------------------------------

    def select_class(self, class_id: int | None = None) -> None:
        """Make `class_id` current, or keep the current class, or fall back to the
        first class of the newest school year.

        Call it after any change to the classes so every page reloads.
        """
        classes = self.roster.list_classes()
        wanted = class_id if class_id is not None else self.class_id
        if wanted in [c.id for c in classes]:
            self.class_id = wanted
        else:
            terms = self.roster.list_terms()
            newest = [c for c in classes if terms and c.term == terms[0]] or classes
            self.class_id = newest[0].id if newest else None
        for _name, page in self.pages:
            page.set_class(self.class_id)
        self.select_subject()

    def new_class(self, term: str | None = None) -> None:
        """Ask for a new class, suggesting `term` (default: the newest school year)."""
        terms = self.roster.list_terms()
        if term is None:
            term = terms[0] if terms else ""
        dialog = ClassDialog(self.roster.save_class, parent=self, terms=terms, default_term=term)
        if dialog.exec() and dialog.saved:
            self.select_class(dialog.saved.id)

    def start_new_year(self, from_term: str = "") -> None:
        """Copy classes into a new school year, then switch to the first new class."""
        dialog = NewYearDialog(self.roster, from_term, parent=self)
        if dialog.exec() and dialog.created:
            self.select_class(dialog.created[0].id)

    def edit_class(self) -> None:
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if school_class is None:
            return
        dialog = ClassDialog(
            self.roster.save_class, school_class, parent=self, terms=self.roster.list_terms()
        )
        if dialog.exec():
            self.select_class(school_class.id)

    def delete_class(self) -> None:
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if school_class is None:
            return
        students = self.roster.list_students(school_class.id, include_inactive=True)
        subjects = self.roster.list_subjects(school_class.id)
        also = [
            f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"
            for items, noun in ((students, "student"), (subjects, "subject"))
            if items
        ]
        question = f"Delete the class {school_class.display_name}"
        question += f" with its {' and '.join(also)}?" if also else "?"
        answer = QMessageBox.question(self, "Delete class", question + "\n\nThis can't be undone.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.roster.delete_class(school_class.id)
        except RosterError as exc:
            QMessageBox.information(self, "Delete class", str(exc))
            return
        self.select_class()

    # --- subjects ------------------------------------------------------------

    def select_subject(self, subject_id: int | None = None) -> None:
        """Make `subject_id` current within the current class.

        Falls back to the subject last picked in this class, then to the first one.
        Call it after any change to the subjects so every page reloads.
        """
        subject_ids = [s.id for s in self.roster.list_subjects(self.class_id)] if self.class_id else []
        for wanted in (subject_id, self._last_subject.get(self.class_id or 0)):
            if wanted in subject_ids:
                self.subject_id = wanted
                break
        else:
            self.subject_id = subject_ids[0] if subject_ids else None
        if self.class_id is not None and self.subject_id is not None:
            self._last_subject[self.class_id] = self.subject_id
        for _name, page in self.pages:
            if set_subject := getattr(page, "set_subject", None):
                set_subject(self.subject_id)
        self._update_title()
        self._save_selection()

    def new_subject(self) -> None:
        if self.class_id is None:
            return
        dialog = SubjectDialog(self.roster.save_subject, self.class_id, parent=self)
        if dialog.exec() and dialog.saved:
            self.select_subject(dialog.saved.id)

    def edit_subject(self) -> None:
        subject = self.roster.get_subject(self.subject_id) if self.subject_id is not None else None
        if subject is None:
            return
        dialog = SubjectDialog(self.roster.save_subject, subject.class_id, subject, parent=self)
        if dialog.exec():
            self.select_subject(subject.id)

    def delete_subject(self) -> None:
        subject = self.roster.get_subject(self.subject_id) if self.subject_id is not None else None
        if subject is None:
            return
        answer = QMessageBox.question(self, "Delete subject", f"Delete the subject {subject.name}?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.roster.delete_subject(subject.id)
        except RosterError as exc:
            QMessageBox.information(self, "Delete subject", str(exc))
            return
        self.select_subject()

    def _update_title(self) -> None:
        """Show the current class and subject, now that the sidebar has no pickers."""
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        subject = self.roster.get_subject(self.subject_id) if self.subject_id is not None else None
        context = " · ".join(
            x for x in (school_class and school_class.display_name, subject and subject.name) if x
        )
        self.setWindowTitle(f"Classroom Manager — {context}" if context else "Classroom Manager")
