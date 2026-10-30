from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QListWidget,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.services.dashboard import DashboardService
from app.services.roster import RosterError, RosterService
from app.ui.dialogs.class_dialog import ClassDialog
from app.ui.dialogs.subject_dialog import SubjectDialog
from app.ui.views.classes_view import ClassesView
from app.ui.views.dashboard_view import DashboardView
from app.ui.views.placeholder_view import PlaceholderView
from app.ui.views.roster_view import RosterView


class MainWindow(QMainWindow):
    """Sidebar navigation and a stack of pages.

    The window keeps the current class and subject, which are chosen on the
    Classes page and shown in the title bar. Every page implements
    `set_class(class_id | None)` and is told whenever the class changes. Pages
    that work per subject (e.g. the gradebook) also implement `set_subject(subject_id | None)`.
    """

    def __init__(self, roster: RosterService, dashboard: DashboardService, config: AppConfig):
        super().__init__()
        self.roster = roster
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self._last_subject: dict[int, int] = {}  # class id -> subject picked in it this session
        self.resize(1100, 700)

        # --- pages ---
        self.dashboard_view = DashboardView(dashboard, roster)
        self.dashboard_view.create_class_requested.connect(lambda: self.new_class())
        self.dashboard_view.navigate_requested.connect(self.show_page)
        self.roster_view = RosterView(roster)
        self.roster_view.create_class_requested.connect(lambda: self.new_class())
        self.classes_view = ClassesView(roster)
        self.classes_view.class_selected.connect(self.select_class)
        self.classes_view.subject_selected.connect(self.select_subject)
        self.classes_view.new_class_requested.connect(lambda term: self.new_class(term))
        self.classes_view.edit_class_requested.connect(self.edit_class)
        self.classes_view.delete_class_requested.connect(self.delete_class)
        self.classes_view.new_subject_requested.connect(self.new_subject)
        self.classes_view.edit_subject_requested.connect(self.edit_subject)
        self.classes_view.delete_subject_requested.connect(self.delete_subject)
        self.pages: list[tuple[str, QWidget]] = [
            ("Dashboard", self.dashboard_view),
            ("Roster", self.roster_view),
            ("Attendance", PlaceholderView("Attendance", "Coming in Phase 2.")),
            ("Gradebook", PlaceholderView("Gradebook", "Coming in Phase 3.")),
            ("Rankings", PlaceholderView("Rankings", "Coming in Phase 4.")),
            ("Seating", PlaceholderView("Seating chart", "Coming in Phase 5.")),
            ("Manage classes", self.classes_view),
            ("Settings", PlaceholderView("Settings", "Coming in Phase 6.")),
        ]
        self.stack = QStackedWidget()
        for _name, page in self.pages:
            self.stack.addWidget(page)

        # --- sidebar ---
        self.nav = QListWidget()
        for name, _page in self.pages:
            self.nav.addItem(name)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        sidebar = QWidget()
        QVBoxLayout(sidebar).addWidget(self.nav)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 880])
        splitter.setCollapsible(0, False)
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(f"Data file: {config.db_path}")

        self.nav.setCurrentRow(0)
        self.select_class()

    def show_page(self, name: str) -> None:
        for row, (page_name, _page) in enumerate(self.pages):
            if page_name == name:
                self.nav.setCurrentRow(row)
                return

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
        answer = QMessageBox.question(
            self, "Delete class", f"Delete the class {school_class.display_name}?"
        )
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
