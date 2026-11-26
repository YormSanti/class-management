"""Rankings: the current class's students in order of their averages."""

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.dashboard import letter_grade
from app.services.export import ranking_tsv, write_ranking_csv
from app.services.gradebook import PASS_MARK, format_number
from app.services.rankings import Ranking, RankingService
from app.services.roster import RosterService
from app.ui import style
from app.ui.files import ask_save_path

COLUMNS = ("Place", "Student", "Average", "Grade")
OVERALL = -1  # the "All subjects" choice of Rank by


def average_text(value: float) -> str:
    """One decimal, so averages that look the same are the ones sharing a place."""
    return f"{value:.1f}%"


def place_text(place: int, shared: bool) -> str:
    """ "2" or, when another student has the same place, "2=" as in a results table."""
    return f"{place}=" if shared else str(place)


def overall_tip(counted: int, subjects: int) -> str:
    """What an overall average is made of: `counted` of the `subjects` with scores."""
    if subjects == 1:
        return "The average in the only subject with scores"
    if counted == subjects:
        return f"The mean of the averages in all {subjects} subjects with scores"
    return (
        f"The mean of the averages in {counted} of the {subjects} subjects with scores; "
        "nothing is scored in the others yet"
    )


class RankingsView(QWidget):
    manage_subjects_requested = Signal()  # the class has no subject to rank by yet
    navigate_requested = Signal(str)  # a page name, e.g. "Gradebook"
    subject_selected = Signal(int)  # picked under Rank by: make it the current subject

    def __init__(self, rankings: RankingService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.rankings = rankings
        self.roster = roster
        self.class_id: int | None = None
        self.subject_id: int | None = None
        self.ranking: Ranking | None = None
        self.overall = False  # ranked by all subjects instead of the current one
        self.pass_mark = PASS_MARK

        self.title = style.label("Rankings", 1.6, bold=True)
        self.subtitle = style.label("", 0.95, muted=True)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header = QHBoxLayout()
        header.addLayout(titles, stretch=1)
        self.scope = QComboBox()
        self.scope.setToolTip("Rank by the average of all subjects, or of one subject")
        self.scope.currentIndexChanged.connect(self._scope_picked)
        rank_by = QLabel("&Rank by")
        rank_by.setBuddy(self.scope)
        header.addWidget(rank_by, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(self.scope, alignment=Qt.AlignmentFlag.AlignBottom)
        self.export_button = QPushButton("E&xport…")
        self.export_button.setToolTip("Save the ranking as a CSV file")
        self.export_button.clicked.connect(self.export_csv)
        header.addWidget(self.export_button, alignment=Qt.AlignmentFlag.AlignBottom)

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
        copy = QShortcut(QKeySequence.StandardKey.Copy, self)
        copy.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy.activated.connect(self.copy_ranking)
        self.refresh()

    def copy_ranking(self) -> None:
        """Copy the whole ranking, to paste into a spreadsheet."""
        if self.ranking is not None and self.ranking.ranked:
            QApplication.clipboard().setText(ranking_tsv(self.ranking, self.overall))

    # --- page protocol ---------------------------------------------------------

    def set_class(self, class_id: int | None) -> None:
        self.class_id = class_id
        self.subject_id = None  # MainWindow picks the subject next

    def set_subject(self, subject_id: int | None) -> None:
        self.subject_id = subject_id
        self.refresh()

    def showEvent(self, event) -> None:
        # Scores may have been entered in the gradebook meanwhile.
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """Rank the students again from the database."""
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if school_class is None:
            self.class_id = None
        subjects = self.roster.list_subjects(school_class.id) if school_class else []
        subject = next((x for x in subjects if x.id == self.subject_id), None)
        self._fill_scope(subjects)
        if not subjects:
            self.ranking = None
        elif self.overall:
            self.ranking = self.rankings.overall_ranking(school_class.id)
        else:
            self.ranking = self.rankings.subject_ranking(subject.id) if subject else None
        scope = "All subjects" if self.overall else subject and subject.name
        context = [x for x in (scope if subjects else None, school_class and school_class.display_name) if x]
        self.subtitle.setText(" · ".join(context))
        self.export_button.setEnabled(self.ranking is not None and bool(self.ranking.ranked))
        self._show_state(subject.name if subject else "")

    def export_csv(self) -> None:
        if self.ranking is None or not self.ranking.ranked:
            return
        name = self.subtitle.text().replace(" · ", " ")  # e.g. "Maths 7B (2026-2027)"
        path = ask_save_path(self, "Export ranking", f"{name} ranking", "CSV files", ".csv")
        if path is None:
            return
        try:
            write_ranking_csv(path, self.ranking, overall=self.overall)
        except OSError as exc:
            QMessageBox.warning(self, "Export ranking", f"The file could not be saved:\n{exc}")
            return
        n = len(self.ranking.ranked)
        QMessageBox.information(
            self, "Export ranking", f"Saved the ranking of {n} student{'' if n == 1 else 's'} to\n{path}"
        )

    def set_overall(self, overall: bool) -> None:
        """Rank by all subjects, or by the current one."""
        self.overall = overall
        self.refresh()

    def _fill_scope(self, subjects: list) -> None:
        with QSignalBlocker(self.scope):
            self.scope.clear()
            if subjects:
                self.scope.addItem("All subjects", OVERALL)
                for subject in subjects:
                    self.scope.addItem(subject.name, subject.id)
            index = self.scope.findData(OVERALL if self.overall else self.subject_id)
            self.scope.setCurrentIndex(max(index, 0) if subjects else -1)
        self.scope.setEnabled(bool(subjects))

    def _scope_picked(self, index: int) -> None:
        picked = self.scope.itemData(index)
        if picked is None:
            return
        if picked == OVERALL:
            self.set_overall(True)
        else:
            self.overall = False
            if picked == self.subject_id:
                self.refresh()
            else:
                self.subject_selected.emit(picked)  # MainWindow calls set_subject back

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
            where = "any subject" if self.overall else subject_name
            self._empty(
                f"<h2>Nothing scored in {where} yet</h2><p>Students are ranked once "
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
            self._set_row(row, place_text(ranked.place, ranked.shared), ranked.student.full_name,
                          average_text(ranked.average), letter_grade(ranked.average))
            tips = []
            if self.overall:
                counted = ranking.subjects_counted.get(ranked.student.id, 0)
                tips.append(overall_tip(counted, ranking.subjects))
            if ranked.average < self.pass_mark:
                tips.insert(0, f"Under the pass mark of {format_number(self.pass_mark)}%")
                for col in (2, 3):
                    table.item(row, col).setForeground(style.color(self, "danger"))
            table.item(row, 2).setToolTip("\n".join(tips))
            if ranked.shared:
                others = [r.student.full_name for r in ranking.ranked if r.place == ranked.place and r is not ranked]
                table.item(row, 0).setToolTip("Shared with " + ", ".join(others))
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for row, student in enumerate(ranking.unranked, start=len(ranking.ranked)):
            self._set_row(row, "—", student.full_name, "—", "")
            for col in range(len(COLUMNS)):
                table.item(row, col).setForeground(muted)
                table.item(row, col).setToolTip("Nothing scored yet")
        self.summary.setText(self._summary_text() + " · Ctrl+C copies the ranking for a spreadsheet")

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
        failing = sum(r.average < self.pass_mark for r in ranking.ranked)
        if failing:
            text += f" · {failing} under the pass mark of {format_number(self.pass_mark)}%"
        if ranking.unranked:
            text += f" · {len(ranking.unranked)} with nothing scored yet, listed last"
        return text
