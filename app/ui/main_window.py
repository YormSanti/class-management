from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
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
    """Sidebar (class and subject pickers + navigation) and a stack of pages.

    Every page implements `set_class(class_id | None)` and is told whenever
    the selected class changes. Pages that work per subject (e.g. the gradebook)
    also implement `set_subject(subject_id | None)`.
    """

    def __init__(self, roster: RosterService, dashboard: DashboardService, config: AppConfig):
        super().__init__()
        self.roster = roster
        self._last_subject: dict[int, int] = {}  # class id -> subject picked in it this session
        self.setWindowTitle("Classroom Manager")
        self.resize(1100, 700)

        # --- pages ---
        self.dashboard_view = DashboardView(dashboard, roster)
        self.dashboard_view.create_class_requested.connect(self.new_class)
        self.dashboard_view.navigate_requested.connect(self.show_page)
        self.roster_view = RosterView(roster)
        self.roster_view.create_class_requested.connect(self.new_class)
        self.classes_view = ClassesView(roster)
        self.classes_view.class_selected.connect(self.reload_classes)
        self.classes_view.subject_selected.connect(self.reload_subjects)
        self.classes_view.new_class_requested.connect(self.new_class)
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
            ("Classes", self.classes_view),
            ("Settings", PlaceholderView("Settings", "Coming in Phase 6.")),
        ]
        self.stack = QStackedWidget()
        for _name, page in self.pages:
            self.stack.addWidget(page)

        # --- sidebar ---
        self.class_combo = QComboBox()
        self.class_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.class_combo.currentIndexChanged.connect(self._on_class_changed)

        class_menu = QMenu(self)
        class_menu.addAction("New class…", self.new_class)
        self.edit_class_action = class_menu.addAction("Edit class…", self.edit_class)
        self.delete_class_action = class_menu.addAction("Delete class", self.delete_class)
        class_button = QToolButton()
        class_button.setText("⋯")
        class_button.setToolTip("Manage classes")
        class_button.setMenu(class_menu)
        class_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        class_row = QHBoxLayout()
        class_row.addWidget(self.class_combo, stretch=1)
        class_row.addWidget(class_button)

        self.subject_combo = QComboBox()
        self.subject_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.subject_combo.setPlaceholderText("No subjects yet")
        self.subject_combo.currentIndexChanged.connect(self._on_subject_changed)

        subject_menu = QMenu(self)
        self.new_subject_action = subject_menu.addAction("New subject…", self.new_subject)
        self.edit_subject_action = subject_menu.addAction("Edit subject…", self.edit_subject)
        self.delete_subject_action = subject_menu.addAction("Delete subject", self.delete_subject)
        subject_button = QToolButton()
        subject_button.setText("⋯")
        subject_button.setToolTip("Manage subjects")
        subject_button.setMenu(subject_menu)
        subject_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        subject_row = QHBoxLayout()
        subject_row.addWidget(self.subject_combo, stretch=1)
        subject_row.addWidget(subject_button)

        self.nav = QListWidget()
        for name, _page in self.pages:
            self.nav.addItem(name)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(QLabel("<b>Class</b>"))
        sidebar_layout.addLayout(class_row)
        sidebar_layout.addWidget(QLabel("<b>Subject</b>"))
        sidebar_layout.addLayout(subject_row)
        sidebar_layout.addSpacing(8)
        sidebar_layout.addWidget(self.nav, stretch=1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 880])
        splitter.setCollapsible(0, False)
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(f"Data file: {config.db_path}")

        self.nav.setCurrentRow(0)
        self.reload_classes()

    def show_page(self, name: str) -> None:
        for row, (page_name, _page) in enumerate(self.pages):
            if page_name == name:
                self.nav.setCurrentRow(row)
                return

    # --- classes -------------------------------------------------------------

    def current_class_id(self) -> int | None:
        return self.class_combo.currentData()

    def reload_classes(self, select_id: int | None = None) -> None:
        """Refill the class picker, keeping (or switching to) `select_id`."""
        select_id = select_id if select_id is not None else self.current_class_id()
        self.class_combo.blockSignals(True)
        self.class_combo.clear()
        for school_class in self.roster.list_classes():
            self.class_combo.addItem(school_class.display_name, school_class.id)
        index = self.class_combo.findData(select_id) if select_id is not None else -1
        self.class_combo.setCurrentIndex(index if index >= 0 else 0)
        self.class_combo.blockSignals(False)
        self._on_class_changed()

    def _on_class_changed(self, _index: int = -1) -> None:
        class_id = self.current_class_id()
        self.edit_class_action.setEnabled(class_id is not None)
        self.delete_class_action.setEnabled(class_id is not None)
        self.new_subject_action.setEnabled(class_id is not None)
        for _name, page in self.pages:
            page.set_class(class_id)
        self.reload_subjects()

    def new_class(self) -> None:
        dialog = ClassDialog(self.roster.save_class, parent=self)
        if dialog.exec() and dialog.saved:
            self.reload_classes(dialog.saved.id)

    def edit_class(self) -> None:
        class_id = self.current_class_id()
        school_class = self.roster.get_class(class_id) if class_id is not None else None
        if school_class is None:
            return
        dialog = ClassDialog(self.roster.save_class, school_class, parent=self)
        if dialog.exec():
            self.reload_classes(class_id)

    def delete_class(self) -> None:
        class_id = self.current_class_id()
        if class_id is None:
            return
        name = self.class_combo.currentText()
        answer = QMessageBox.question(self, "Delete class", f"Delete the class {name}?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.roster.delete_class(class_id)
        except RosterError as exc:
            QMessageBox.information(self, "Delete class", str(exc))
            return
        self.reload_classes()

    # --- subjects ------------------------------------------------------------

    def current_subject_id(self) -> int | None:
        return self.subject_combo.currentData()

    def reload_subjects(self, select_id: int | None = None) -> None:
        """Refill the subject picker for the current class.

        Selects `select_id`, else the subject last picked in this class, else the first.
        """
        class_id = self.current_class_id()
        if select_id is None and class_id is not None:
            select_id = self._last_subject.get(class_id)
        self.subject_combo.blockSignals(True)
        self.subject_combo.clear()
        if class_id is not None:
            for subject in self.roster.list_subjects(class_id):
                self.subject_combo.addItem(subject.name, subject.id)
        index = self.subject_combo.findData(select_id) if select_id is not None else -1
        self.subject_combo.setCurrentIndex(index if index >= 0 else (0 if self.subject_combo.count() else -1))
        self.subject_combo.setEnabled(self.subject_combo.count() > 0)
        self.subject_combo.blockSignals(False)
        self._on_subject_changed()

    def _on_subject_changed(self, _index: int = -1) -> None:
        class_id, subject_id = self.current_class_id(), self.current_subject_id()
        if class_id is not None and subject_id is not None:
            self._last_subject[class_id] = subject_id
        self.edit_subject_action.setEnabled(subject_id is not None)
        self.delete_subject_action.setEnabled(subject_id is not None)
        for _name, page in self.pages:
            if set_subject := getattr(page, "set_subject", None):
                set_subject(subject_id)

    def new_subject(self) -> None:
        class_id = self.current_class_id()
        if class_id is None:
            return
        dialog = SubjectDialog(self.roster.save_subject, class_id, parent=self)
        if dialog.exec() and dialog.saved:
            self.reload_subjects(dialog.saved.id)

    def edit_subject(self) -> None:
        subject_id = self.current_subject_id()
        subject = self.roster.get_subject(subject_id) if subject_id is not None else None
        if subject is None:
            return
        dialog = SubjectDialog(self.roster.save_subject, subject.class_id, subject, parent=self)
        if dialog.exec():
            self.reload_subjects(subject_id)

    def delete_subject(self) -> None:
        subject_id = self.current_subject_id()
        if subject_id is None:
            return
        name = self.subject_combo.currentText()
        answer = QMessageBox.question(self, "Delete subject", f"Delete the subject {name}?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.roster.delete_subject(subject_id)
        except RosterError as exc:
            QMessageBox.information(self, "Delete subject", str(exc))
            return
        self.reload_subjects()
