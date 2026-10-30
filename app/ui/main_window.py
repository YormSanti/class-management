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
from app.ui.views.dashboard_view import DashboardView
from app.ui.views.placeholder_view import PlaceholderView
from app.ui.views.roster_view import RosterView


class MainWindow(QMainWindow):
    """Sidebar (class picker + navigation) and a stack of pages.

    Every page implements `set_class(class_id | None)` and is told whenever
    the selected class changes.
    """

    def __init__(self, roster: RosterService, dashboard: DashboardService, config: AppConfig):
        super().__init__()
        self.roster = roster
        self.setWindowTitle("Classroom Manager")
        self.resize(1100, 700)

        # --- pages ---
        self.dashboard_view = DashboardView(dashboard, roster)
        self.dashboard_view.create_class_requested.connect(self.new_class)
        self.dashboard_view.navigate_requested.connect(self.show_page)
        self.roster_view = RosterView(roster)
        self.roster_view.create_class_requested.connect(self.new_class)
        self.pages: list[tuple[str, QWidget]] = [
            ("Dashboard", self.dashboard_view),
            ("Roster", self.roster_view),
            ("Attendance", PlaceholderView("Attendance", "Coming in Phase 2.")),
            ("Gradebook", PlaceholderView("Gradebook", "Coming in Phase 3.")),
            ("Rankings", PlaceholderView("Rankings", "Coming in Phase 4.")),
            ("Seating", PlaceholderView("Seating chart", "Coming in Phase 5.")),
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

        self.nav = QListWidget()
        for name, _page in self.pages:
            self.nav.addItem(name)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(QLabel("<b>Class</b>"))
        sidebar_layout.addLayout(class_row)
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
        for _name, page in self.pages:
            page.set_class(class_id)

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
