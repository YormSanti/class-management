"""Rankings: the current class's students in order of their averages."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.dashboard import letter_grade
from app.services.rankings import Ranking, RankingService
from app.services.roster import RosterService
from app.ui import style

COLUMNS = ("Place", "Student", "Average", "Grade")


def average_text(value: float) -> str:
    """One decimal, so averages that look the same are the ones sharing a place."""
    return f"{value:.1f}%"


class RankingsView(QWidget):
    manage_subjects_requested = Signal()  # the class has no subject to rank by yet
    navigate_requested = Signal(str)  # a page name, e.g. "Gradebook"

    def __init__(self, rankings: RankingService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.rankings = rankings
        self.roster = roster
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self.ranking: Ranking | None = None

        self.title = style.label("Rankings", 1.6, bold=True)
        self.subtitle = style.label("", 0.95, muted=True)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header = QHBoxLayout()
        header.addLayout(titles, stretch=1)

        self.summary = style.label("", 0.95, muted=True)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.ranking_page = QWidget()
        ranking_layout = QVBoxLayout(self.ranking_page)
        ranking_layout.setContentsMargins(0, 0, 0, 0)
        ranking_layout.addWidget(self.summary)
        ranking_layout.addWidget(self.table, stretch=1)

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
        self.pages.addWidget(self.ranking_page)

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
        """Rank the students again from the database."""
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        subject = self.roster.get_subject(self.subject_id) if self.subject_id is not None else None
        if school_class is None:
            self.class_id = None
        self.ranking = self.rankings.subject_ranking(subject.id) if subject and school_class else None
        context = [x for x in (subject and subject.name, school_class and school_class.display_name) if x]
        self.subtitle.setText(" · ".join(context))
        self._show_state(subject.name if subject else "")

    def _show_state(self, subject_name: str) -> None:
        if self.class_id is None:
            self._empty("<h2>No class selected</h2><p>Create a class to rank its students.</p>")
        elif self.ranking is None:
            self._empty(
                "<h2>No subject yet</h2><p>Students are ranked by their averages in a subject. "
                "Add the subjects you teach this class first.</p>",
                "Add a subject",
            )
        elif not self.ranking.ranked:
            self._empty(
                f"<h2>Nothing scored in {subject_name} yet</h2><p>Students are ranked once "
                "the gradebook has scores to make their averages from.</p>",
                "Open the gradebook",
            )
        else:
            self._fill_table()
            self.pages.setCurrentWidget(self.ranking_page)

    def _empty(self, text: str, button: str = "") -> None:
        self.empty_label.setText(text)
        self.empty_button.setText(button)
        self.empty_button.setVisible(bool(button))
        self.pages.setCurrentIndex(0)

    def _empty_action(self) -> None:
        if self.ranking is None:
            self.manage_subjects_requested.emit()
        else:
            self.navigate_requested.emit("Gradebook")

    # --- the table -------------------------------------------------------------

    def _fill_table(self) -> None:
        ranking = self.ranking
        table = self.table
        table.clearContents()
        table.setRowCount(len(ranking.ranked) + len(ranking.unranked))
        for row, ranked in enumerate(ranking.ranked):
            self._set_row(row, str(ranked.place), ranked.student.full_name,
                          average_text(ranked.average), letter_grade(ranked.average))
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for row, student in enumerate(ranking.unranked, start=len(ranking.ranked)):
            self._set_row(row, "—", student.full_name, "—", "")
            for col in range(len(COLUMNS)):
                table.item(row, col).setForeground(muted)
                table.item(row, col).setToolTip("Nothing scored yet")
        self.summary.setText(self._summary_text())

    def _set_row(self, row: int, *texts: str) -> None:
        for col, text in enumerate(texts):
            item = QTableWidgetItem(text)
            if col != 1:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, col, item)

    def _summary_text(self) -> str:
        ranking = self.ranking
        n = len(ranking.ranked)
        text = f"{n} student{'' if n == 1 else 's'} ranked"
        if ranking.unranked:
            text += f" · {len(ranking.unranked)} with nothing scored yet, listed last"
        return text
