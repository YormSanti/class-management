from datetime import date

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QHelpEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from app.repositories.dashboard_repo import AssignmentStats
from app.services.dashboard import (
    ABSENT,
    EXCUSED,
    GRADE_SCALE,
    LATE,
    LOW_AVERAGE,
    PRESENT,
    AttentionItem,
    DashboardService,
    DashboardSummary,
    DayAttendance,
    SubjectSummary,
    letter_grade,
)
from app.services.roster import RosterService

# (light theme, dark theme) colours for statuses; neutrals come from the palette.
_COLORS = {
    "accent": ("#2F6B4F", "#6FBF97"),
    "warn": ("#B7791F", "#E0A84A"),
    "danger": ("#B9412E", "#E57A66"),
    "info": ("#3F659C", "#7FA3D9"),
}
_STATUS_COLOR = {PRESENT: "accent", LATE: "warn", ABSENT: "danger", EXCUSED: "info"}
_KIND_COLOR = {"absent": "danger", "grades": "warn", "missing": "info", "late": "warn"}
_KIND_LABEL = {"absent": "Attendance", "grades": "Grades", "missing": "Missing", "late": "Late"}
ATTENTION_SHOWN = 5


def _is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


def _color(widget: QWidget, name: str) -> QColor:
    light, dark = _COLORS[name]
    return QColor(dark if _is_dark(widget) else light)


def _soft(widget: QWidget, name: str) -> QColor:
    """The status colour washed into the background, for pills and avatars."""
    color = _color(widget, name)
    color.setAlpha(40)
    return color


def _mix(a: QColor, b: QColor, amount: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
    )


def _label(text: str = "", size: float = 1.0, bold: bool = False, muted: bool = False) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * size)
    font.setBold(bold)
    label.setFont(font)
    if muted:
        label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    return label


def _caption(text: str) -> QLabel:
    """Small uppercase heading, e.g. table column names."""
    label = _label(text.upper(), 0.78, bold=True, muted=True)
    font = label.font()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
    label.setFont(font)
    return label


def _set_color(label: QLabel, color: QColor) -> None:
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, color)
    label.setPalette(palette)
    label.setForegroundRole(QPalette.ColorRole.WindowText)


def _clear(layout: QGridLayout | QVBoxLayout | QHBoxLayout) -> None:
    while (item := layout.takeAt(0)) is not None:
        if widget := item.widget():
            widget.deleteLater()
        elif child := item.layout():
            _clear(child)


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _short_date(day: date | None) -> str:
    return f"{day.day} {day:%b}" if day else "No date"


class Panel(QFrame):
    """A bordered card with an optional title row."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(12)
        if title:
            self.header = QHBoxLayout()
            titles = QVBoxLayout()
            titles.setSpacing(2)
            titles.addWidget(_label(title, 1.15, bold=True))
            if subtitle:
                sub = _label(subtitle, 0.85, muted=True)
                sub.setWordWrap(True)
                titles.addWidget(sub)
            self.header.addLayout(titles, stretch=1)
            self.body.addLayout(self.header)


class Meter(QWidget):
    """A horizontal bar showing value / maximum."""

    def __init__(self, color: str = "accent", width: int | None = None, height: int = 8):
        super().__init__()
        self.value, self.maximum, self.color = 0.0, 1.0, color
        self._height = height
        self.setFixedHeight(height)
        if width:
            self.setFixedWidth(width)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float, maximum: float, color: str | None = None) -> None:
        self.value, self.maximum = value, maximum or 1.0
        self.color = color or self.color
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self._height / 2
        palette = self.palette()
        painter.setBrush(_mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text), 0.08))
        painter.drawRoundedRect(QRectF(self.rect()), radius, radius)
        fraction = max(0.0, min(1.0, self.value / self.maximum))
        if fraction:
            painter.setBrush(_color(self, self.color))
            painter.drawRoundedRect(QRectF(0, 0, self.width() * fraction, self.height()), radius, radius)


class AttendanceChart(QWidget):
    """Stacked columns per day: present at the bottom, then excused, late, absent."""

    ORDER = (PRESENT, EXCUSED, LATE, ABSENT)
    LABEL_SPACE = 24

    def __init__(self):
        super().__init__()
        self.days: list[DayAttendance] = []
        self.today: date | None = None
        self.setMinimumHeight(190)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(520, 210)

    def set_days(self, days: list[DayAttendance], today: date) -> None:
        self.days, self.today = days, today
        self.update()

    def _column_rects(self) -> list[QRectF]:
        count = len(self.days)
        gap = 12
        width = (self.width() - gap * (count - 1)) / count
        height = self.height() - self.LABEL_SPACE
        return [QRectF(i * (width + gap), 0, width, height) for i in range(count)]

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            for day, rect in zip(self.days, self._column_rects()):
                if rect.left() <= event.position().x() <= rect.right():
                    parts = [f"{day.counts[s]} {s}" for s in self.ORDER if day.counts.get(s)]
                    QToolTip.showText(event.globalPos(), f"{day.day:%a %d %b}: " + ", ".join(parts), self)
                    return True
            QToolTip.hideText()
            return True
        return super().event(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        if not self.days:
            painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No attendance recorded yet.")
            return

        biggest = max(sum(d.counts.values()) for d in self.days) or 1
        for day, column in zip(self.days, self._column_rects()):
            is_today = day.day == self.today
            y = column.bottom()
            painter.setPen(Qt.PenStyle.NoPen)
            for status in self.ORDER:
                n = day.counts.get(status, 0)
                if not n:
                    continue
                height = column.height() * n / biggest
                color = _color(self, _STATUS_COLOR[status])
                if status == PRESENT and not is_today:
                    color = _mix(palette.color(QPalette.ColorRole.Base), color, 0.5)
                painter.setBrush(color)
                painter.drawRect(QRectF(column.left(), y - height, column.width(), height))
                y -= height

            font = painter.font()
            font.setBold(is_today)
            painter.setFont(font)
            role = QPalette.ColorRole.WindowText if is_today else QPalette.ColorRole.PlaceholderText
            painter.setPen(palette.color(role))
            label_rect = QRectF(column.left() - 6, column.bottom() + 4, column.width() + 12, self.LABEL_SPACE - 4)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, f"{day.day:%a}"[:2] + f" {day.day.day}")


class DashboardView(QWidget):
    """Overview of the selected class: key numbers, attendance, grades, students to check on."""

    navigate_requested = Signal(str)  # page name, e.g. "Attendance"
    create_class_requested = Signal()

    def __init__(self, dashboard: DashboardService, roster: RosterService, parent: QWidget | None = None):
        super().__init__(parent)
        self.dashboard = dashboard
        self.roster = roster
        self.class_id: int | None = None

        # --- header ---
        self.date_label = _caption("")
        self.title_label = _label("", 1.9)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(self.date_label)
        titles.addWidget(self.title_label)

        gradebook_button = QPushButton("Open gradebook")
        gradebook_button.clicked.connect(lambda: self.navigate_requested.emit("Gradebook"))
        attendance_button = QPushButton("Take attendance")
        attendance_button.setObjectName("Primary")
        attendance_button.clicked.connect(lambda: self.navigate_requested.emit("Attendance"))

        header = QHBoxLayout()
        header.addLayout(titles)
        header.addStretch()
        header.addWidget(gradebook_button, alignment=Qt.AlignmentFlag.AlignBottom)
        header.addWidget(attendance_button, alignment=Qt.AlignmentFlag.AlignBottom)

        # --- key numbers ---
        kpi_panel = QFrame()
        kpi_panel.setObjectName("Panel")
        kpi_layout = QHBoxLayout(kpi_panel)
        kpi_layout.setContentsMargins(0, 0, 0, 0)
        kpi_layout.setSpacing(0)
        self.kpis: dict[str, tuple[QLabel, QLabel]] = {}
        for i, name in enumerate(("Active students", "Attendance this week", "Class average", "Missing work")):
            if i:
                line = QFrame()
                line.setObjectName("Divider")
                line.setFixedWidth(1)
                kpi_layout.addWidget(line)
            cell = QVBoxLayout()
            cell.setContentsMargins(20, 16, 20, 16)
            cell.setSpacing(4)
            value, sub = _label("—", 2.1), _label("", 0.85, muted=True)
            sub.setWordWrap(True)
            cell.addWidget(_label(name, 0.92, muted=True))
            cell.addWidget(value)
            cell.addWidget(sub)
            cell.addStretch()
            kpi_layout.addLayout(cell, stretch=1)
            self.kpis[name] = (value, sub)

        # --- attendance chart + needs attention ---
        chart_panel = Panel("Attendance", "Last 10 days with attendance recorded · hover for details")
        legend = QHBoxLayout()
        legend.setSpacing(14)
        self.legend_swatches: list[tuple[QLabel, str]] = []
        for status in (PRESENT, LATE, ABSENT, EXCUSED):
            swatch = QLabel()
            swatch.setFixedSize(10, 10)
            self.legend_swatches.append((swatch, _STATUS_COLOR[status]))
            legend.addWidget(swatch)
            legend.addWidget(_label(status.capitalize(), 0.85, muted=True))
        legend.addStretch()
        chart_panel.body.addLayout(legend)
        self.chart = AttendanceChart()
        chart_panel.body.addWidget(self.chart, stretch=1)

        attention_panel = Panel("Needs attention")
        attention_panel.setMinimumWidth(280)
        attention_panel.setMaximumWidth(380)
        self.attention_count = _label("", 0.85, muted=True)
        attention_panel.header.addWidget(self.attention_count)
        self.attention_list = QVBoxLayout()
        self.attention_list.setSpacing(0)
        attention_panel.body.addLayout(self.attention_list)
        attention_panel.body.addStretch()

        middle = QHBoxLayout()
        middle.setSpacing(16)
        middle.addWidget(chart_panel, stretch=2)
        middle.addWidget(attention_panel, stretch=1)

        # --- recent assignments + grade distribution ---
        assignments_panel = Panel("Recent assignments")
        self.assignments_grid = QGridLayout()
        self.assignments_grid.setHorizontalSpacing(16)
        self.assignments_grid.setVerticalSpacing(10)
        assignments_panel.body.addLayout(self.assignments_grid)
        assignments_panel.body.addStretch()

        grades_panel = Panel("Grade distribution", "Current weighted averages")
        grades_panel.setMinimumWidth(260)
        grades_panel.setMaximumWidth(380)
        self.grade_rows: dict[str, tuple[Meter, QLabel]] = {}
        grades_grid = QGridLayout()
        grades_grid.setHorizontalSpacing(12)
        grades_grid.setVerticalSpacing(10)
        bounds = [lower for _, lower in GRADE_SCALE]
        for row, (letter, lower) in enumerate(GRADE_SCALE):
            upper = 100 if row == 0 else bounds[row - 1] - 1
            meter = Meter("accent", height=12)
            count = _label("0", bold=True)
            count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grades_grid.addWidget(_label(letter, 1.15, bold=True), row, 0)
            grades_grid.addWidget(meter, row, 1)
            grades_grid.addWidget(count, row, 2)
            grades_grid.addWidget(_label(f"{lower:.0f}–{upper:.0f}" if lower else f"below {bounds[row - 1]:.0f}", 0.85, muted=True), row, 3)
            self.grade_rows[letter] = (meter, count)
        grades_grid.setColumnStretch(1, 1)
        grades_panel.body.addLayout(grades_grid)
        grades_panel.body.addStretch()

        subjects_panel = Panel("Subjects", "Class average in each subject")
        self.subjects_grid = QGridLayout()
        self.subjects_grid.setHorizontalSpacing(16)
        self.subjects_grid.setVerticalSpacing(10)
        subjects_panel.body.addLayout(self.subjects_grid)
        subjects_panel.body.addStretch()

        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        bottom.addWidget(subjects_panel, stretch=2)
        bottom.addWidget(grades_panel, stretch=1)

        content = QWidget()
        content.setObjectName("DashboardContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(16)
        # Wrapped labels make the scroll area ignore the minimum height; enforce it.
        content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        content_layout.addLayout(header)
        content_layout.addWidget(kpi_panel)
        content_layout.addLayout(middle, stretch=1)
        content_layout.addLayout(bottom)
        content_layout.addWidget(assignments_panel)

        scroll = QScrollArea()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        # --- empty state (no class yet) ---
        empty_page = QWidget()
        empty_label = QLabel("<h2>No class selected</h2><p>Create a class to see its overview.</p>")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        create_button = QPushButton("Create a class…")
        create_button.clicked.connect(self.create_class_requested)
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.addStretch()
        empty_layout.addWidget(empty_label)
        empty_layout.addWidget(create_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()

        self.pages = QStackedWidget()
        self.pages.addWidget(empty_page)
        self.pages.addWidget(scroll)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pages)

        self._apply_style()

    # --- public ----------------------------------------------------------------

    def set_class(self, class_id: int | None) -> None:
        self.class_id = class_id
        self.refresh()

    def refresh(self) -> None:
        school_class = self.roster.get_class(self.class_id) if self.class_id is not None else None
        if school_class is None:
            self.pages.setCurrentIndex(0)
            return
        self.pages.setCurrentIndex(1)
        today = date.today()
        summary = self.dashboard.summary(school_class.id, today)

        self.date_label.setText(f"{today:%A}, {today.day} {today:%B}".upper())
        self.title_label.setText(f"Today in {school_class.name}")
        self._show_kpis(summary)
        self.chart.set_days(summary.attendance_days, today)
        self._show_attention(summary.attention)
        self._show_assignments(summary.recent_assignments, summary.active_students)
        self._show_grades(summary.grade_distribution)
        self._show_subjects(summary.subjects)

    # --- Qt events -------------------------------------------------------------

    def showEvent(self, event) -> None:
        # Other pages may have changed students, attendance or scores meanwhile.
        super().showEvent(event)
        self.refresh()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._apply_style()

    # --- helpers ---------------------------------------------------------------

    def _apply_style(self) -> None:
        palette = self.palette()
        self._border = _mix(palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text), 0.14)
        accent = _color(self, "accent")
        self.setStyleSheet(
            f"""
            #DashboardContent {{ background: palette(window); }}
            #Panel {{ background: palette(base); border: 1px solid {self._border.name()}; border-radius: 10px; }}
            #Panel QLabel {{ background: transparent; }}
            #Divider {{ background: {self._border.name()}; }}
            QPushButton#Primary {{
                background: {accent.name()}; color: {'#10241A' if _is_dark(self) else 'white'};
                border: none; border-radius: 6px; padding: 7px 16px; font-weight: 600;
            }}
            QPushButton#Primary:hover {{ background: {accent.darker(115).name()}; }}
            """
        )
        for swatch, color in self.legend_swatches:
            swatch.setStyleSheet(f"background: {_color(self, color).name()}; border-radius: 2px;")

    def _show_kpis(self, s: DashboardSummary) -> None:
        value, sub = self.kpis["Active students"]
        value.setText(str(s.active_students))
        sub.setText(f"{s.inactive_students} inactive" if s.inactive_students else "All active")

        value, sub = self.kpis["Attendance this week"]
        value.setText(_percent(s.week_rate))
        sub.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        if s.week_rate is None:
            sub.setText("Nothing recorded this week")
        elif s.previous_week_rate is None:
            sub.setText("No data for last week")
        else:
            change = s.week_rate - s.previous_week_rate
            sub.setText(f"{change:+.1f} pts vs last week")
            if abs(change) >= 0.05:
                _set_color(sub, _color(self, "accent" if change > 0 else "danger"))

        value, sub = self.kpis["Class average"]
        value.setText(_percent(s.class_average))
        sub.setText(
            f"Grade {letter_grade(s.class_average)} · weighted" if s.class_average is not None else "No scores yet"
        )

        value, sub = self.kpis["Missing work"]
        value.setText(str(s.missing_total))
        sub.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        if s.missing_total:
            sub.setText("Scores missing on past assignments")
            _set_color(sub, _color(self, "warn"))
        else:
            sub.setText("Nothing missing")

    def _show_attention(self, items: list[AttentionItem]) -> None:
        _clear(self.attention_list)
        self.attention_count.setText(f"{len(items)} student{'' if len(items) == 1 else 's'}" if items else "")
        if not items:
            self.attention_list.addWidget(_label("Nobody needs attention right now.", muted=True))
            return

        for i, item in enumerate(items[:ATTENTION_SHOWN]):
            color, soft = _color(self, _KIND_COLOR[item.kind]), _soft(self, _KIND_COLOR[item.kind])
            row = QFrame()
            row.setObjectName("AttentionRow")
            if i:
                row.setStyleSheet(f"#AttentionRow {{ border-top: 1px solid {self._border.name()}; }}")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 10, 0, 10)
            row_layout.setSpacing(12)

            initials = (item.student.first_name[:1] + item.student.last_name[:1]).upper()
            avatar = _label(initials, 0.85, bold=True)
            avatar.setFixedSize(34, 34)
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setStyleSheet(f"background: {soft.name(QColor.NameFormat.HexArgb)}; color: {color.name()}; border: none; border-radius: 17px;")

            text = QVBoxLayout()
            text.setSpacing(1)
            text.addWidget(_label(item.student.full_name, bold=True))
            text.addWidget(_label(item.reason, 0.85, muted=True))

            badge = _label(_KIND_LABEL[item.kind], 0.8, bold=True)
            badge.setStyleSheet(
                f"background: {soft.name(QColor.NameFormat.HexArgb)}; color: {color.name()}; border: none; border-radius: 9px; padding: 2px 8px;"
            )

            row_layout.addWidget(avatar)
            row_layout.addLayout(text, stretch=1)
            row_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)
            self.attention_list.addWidget(row)

        if len(items) > ATTENTION_SHOWN:
            more = _label(f"+ {len(items) - ATTENTION_SHOWN} more", 0.85, muted=True)
            more.setContentsMargins(0, 8, 0, 0)
            self.attention_list.addWidget(more)

    def _show_assignments(self, assignments: list[AssignmentStats], active_students: int) -> None:
        grid = self.assignments_grid
        _clear(grid)
        if not assignments:
            grid.addWidget(_label("No assignments yet. They will show up here once you add them.", muted=True), 0, 0)
            return

        headers = ("Assignment", "Subject", "Date", "Submitted", "Average")
        for col, text in enumerate(headers):
            caption = _caption(text)
            if col == 4:
                caption.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(caption, 0, col)
        for row, a in enumerate(assignments, start=1):
            grid.addWidget(_label(a.title, bold=True), row, 0)
            subject = _label(a.subject, 0.92, muted=True)
            subject.setToolTip(a.category)
            grid.addWidget(subject, row, 1)
            grid.addWidget(_label(_short_date(a.date), 0.92, muted=True), row, 2)

            submitted = QHBoxLayout()
            submitted.setSpacing(8)
            meter = Meter(width=70, height=6)
            meter.set_value(a.submitted, active_students, "accent" if a.submitted >= active_students else "warn")
            submitted.addWidget(meter)
            submitted.addWidget(_label(f"{a.submitted}/{active_students}", 0.92, muted=True))
            submitted.addStretch()
            grid.addLayout(submitted, row, 3)

            average = _label("—" if a.average_percent is None else f"{a.average_percent:.0f}%", bold=True)
            average.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(average, row, 4)
        grid.setColumnStretch(0, 1)

    def _show_grades(self, distribution: dict[str, int]) -> None:
        biggest = max(distribution.values(), default=0) or 1
        for letter, (meter, count) in self.grade_rows.items():
            n = distribution.get(letter, 0)
            meter.set_value(n, biggest, "warn" if letter in ("D", "F") else "accent")
            count.setText(str(n))

    def _show_subjects(self, subjects: list[SubjectSummary]) -> None:
        grid = self.subjects_grid
        _clear(grid)
        if not subjects:
            hint = _label("No subjects yet. Add one with the ⋯ button next to Subject in the sidebar.", muted=True)
            hint.setWordWrap(True)
            grid.addWidget(hint, 0, 0)
            return

        for col, text in enumerate(("Subject", "Teacher", "Class average", f"Below {LOW_AVERAGE:.0f}%")):
            caption = _caption(text)
            if col == 3:
                caption.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(caption, 0, col)
        for row, s in enumerate(subjects, start=1):
            grid.addWidget(_label(s.subject.name, bold=True), row, 0)
            grid.addWidget(_label(s.subject.teacher or "You", 0.92, muted=True), row, 1)

            average = QHBoxLayout()
            average.setSpacing(10)
            meter = Meter(height=8)
            if s.average is not None:
                color = "danger" if s.average < LOW_AVERAGE else "warn" if s.average < 70 else "accent"
                meter.set_value(s.average, 100, color)
            average.addWidget(meter, stretch=1)
            value = _label("No scores" if s.average is None else f"{s.average:.0f}% {letter_grade(s.average)}", 0.92, bold=s.average is not None, muted=s.average is None)
            value.setMinimumWidth(64)
            average.addWidget(value)
            grid.addLayout(average, row, 2)

            below = _label(str(s.below_pass) if s.scored else "—", bold=bool(s.below_pass), muted=not s.below_pass)
            below.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if s.below_pass:
                _set_color(below, _color(self, "danger"))
            grid.addWidget(below, row, 3)
        grid.setColumnStretch(2, 1)
