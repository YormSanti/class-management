"""The gradebook of the current subject: students down the side, assignments across."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from app.services.gradebook import GradebookService, GradeSheet
from app.services.roster import RosterService
from app.ui import style


class GradebookView(QWidget):
    manage_subjects_requested = Signal()  # the class has no subject to grade yet

    def __init__(self, grades: GradebookService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.grades = grades
        self.roster = roster
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self.sheet: GradeSheet | None = None

        self.title = style.label("Gradebook", 1.6, bold=True)
        self.subtitle = style.label("", 0.95, muted=True)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header = QHBoxLayout()
        header.addLayout(titles, stretch=1)

        self.sheet_page = QWidget()  # filled in by the steps that show the grades

        # --- empty states ---
        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_button = QPushButton()
        self.empty_button.setObjectName("Primary")
        self.empty_button.clicked.connect(self._empty_action)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        empty_layout.addWidget(self.empty_label)
        empty_layout.addWidget(self.empty_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()

        self.pages = QStackedWidget()
        self.pages.addWidget(empty)
        self.pages.addWidget(self.sheet_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(self.pages, stretch=1)
        self.setStyleSheet(style.card_stylesheet(self))
        self.refresh()

    # --- page protocol ---------------------------------------------------------

    def set_class(self, class_id: int | None) -> None:
        self.class_id = class_id
        self.subject_id = None  # MainWindow picks the subject next

    def set_subject(self, subject_id: int | None) -> None:
        self.subject_id = subject_id
        self.refresh()

    def refresh(self) -> None:
        """Read the current subject's gradebook from the database again."""
        self.sheet = self.grades.sheet(self.subject_id) if self.subject_id is not None else None
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if self.sheet is not None and school_class is not None:
            self.subtitle.setText(f"{self.sheet.subject.name} · {school_class.display_name}")
        else:
            self.subtitle.setText(school_class.display_name if school_class else "")
        self._show_state()

    def _show_state(self) -> None:
        if self.class_id is None:
            self._empty("<h2>No class selected</h2><p>Create a class to keep its grades.</p>")
        elif self.sheet is None:
            self._empty(
                "<h2>No subject yet</h2><p>Every subject of a class has its own gradebook. "
                "Add the subjects you teach this class first.</p>",
                "Add a subject",
            )
        else:
            self.pages.setCurrentWidget(self.sheet_page)

    def _empty(self, text: str, button: str = "") -> None:
        self.empty_label.setText(text)
        self.empty_button.setText(button)
        self.empty_button.setVisible(bool(button))
        self.pages.setCurrentIndex(0)

    def _empty_action(self) -> None:
        if self.class_id is not None and self.sheet is None:
            self.manage_subjects_requested.emit()
