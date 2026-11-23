"""Class, subject and student management: validation and rules on top of the repositories."""

import csv
import re
import sqlite3
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date

from app.db.connection import transaction
from app.models import SchoolClass, Student, Subject
from app.repositories.class_repo import ClassRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository


class RosterError(ValueError):
    """A user-facing validation error; the message is safe to show in the UI."""


NAME_MAX = 60  # characters in a first or last name: room for long double names, not a paragraph
STUDENT_NO_MAX = 20  # characters: a school's ID, not a sentence
STUDENT_NOTES_MAX = 1000  # characters: allergies, who collects them, a few lines more
CLASS_NAME_MAX = 40  # characters: "Grade 7 Blue (afternoon group)" fits
TERM_MAX = 30  # characters in a school year: "2026-2027 second semester" fits
SUBJECT_NAME_MAX = 60  # characters in a subject or teacher name


def _check_length(text: str, limit: int, what: str) -> None:
    """Refuse `text` longer than `limit` characters, e.g. a whole list pasted into one field."""
    if len(text) > limit:
        raise RosterError(f"{what} can be at most {limit} characters; this one has {len(text)}.")


def _clean(text: str | None) -> str:
    """Trimmed, with runs of spaces (e.g. from copying) collapsed: "Ada  Lovelace" -> "Ada Lovelace"."""
    return " ".join((text or "").split())


def fold(text: str) -> str:
    """`text` without accents and case, for searching: "José Ñúñez" -> "jose nunez"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def matches(student: Student, search: str) -> bool:
    """True if `search` is part of the student's number, first name, last name, "first
    last", "last first", "last, first" or notes, ignoring case and accents."""
    wanted = fold(_clean(search))
    s = student
    fields = (s.student_no or "", s.first_name, s.last_name, f"{s.first_name} {s.last_name}",
              f"{s.last_name} {s.first_name}", f"{s.last_name}, {s.first_name}", s.notes)  # fmt: skip
    return any(wanted in fold(field) for field in fields)


def natural_key(text: str) -> tuple:
    """Sorts text as people read it, numbers by value: "7B" before "10A", "S2" before "S10"."""
    parts = re.split(r"(\d+)", text.casefold())
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p)


def number_key(student: Student) -> tuple:
    """Sorts students by number as people read them ("S2" before "S10"); those
    without a number come last, in the usual name order."""
    if not student.student_no:
        return (1, ())
    return (0, natural_key(student.student_no))


def _numbers_after(numbers: list[str]) -> Iterator[str]:
    """The free numbers after the highest of `numbers`, keeping its prefix and zero
    padding: "S007" -> "S008", "S009", ... Nothing if none of them ends in digits."""
    best: tuple[int, str, int] | None = None  # (value, prefix, digit count)
    for number in numbers:
        if m := re.fullmatch(r"(.*?)(\d+)", number):
            candidate = (int(m.group(2)), m.group(1), len(m.group(2)))
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is not None:
        value, prefix, width = best
        yield from _free_numbers(prefix, value + 1, width, numbers)


def _free_numbers(prefix: str, value: int, width: int, taken: list[str]) -> Iterator[str]:
    """prefix + value, value + 1, ... zero-padded to `width` digits, leaving out the
    numbers in `taken` (ignoring case: "s008" takes "S008" too)."""
    used = {number.casefold() for number in taken}
    while True:
        number = f"{prefix}{value:0{width}d}"
        if number.casefold() not in used:
            yield number
        value += 1


# "2025-26" style: a full year, a dash or slash, then the next year's last two digits.
_SHORT_YEAR_RANGE = r"\b(\d{4})(\s*[-/–]\s*)(\d{2})\b"


def next_term(term: str) -> str:
    """Suggest the school year after `term`: "2025-2026" -> "2026-2027", "2026" -> "2027",
    "2025-26" -> "2026-27".

    Every year in the text moves on by one, keeping the rest as typed.
    Returns "" when there is no year to move on.
    """
    if not re.search(r"\b\d{4}\b", term):
        return ""

    def bump(m: re.Match[str]) -> str:
        if m.group(1) is None:
            return str(int(m.group()) + 1)
        return f"{int(m.group(1)) + 1}{m.group(2)}{(int(m.group(3)) + 1) % 100:02d}"

    return re.sub(_SHORT_YEAR_RANGE + r"|\b\d{4}\b", bump, term)


def example_school_year(today: date) -> str:
    """A school year written the usual way, for placeholder text: the one that has
    started by `today` if school years start in the second half of the calendar year."""
    first = today.year if today.month >= 7 else today.year - 1
    return f"{first}-{first + 1}"


def move_up(name: str) -> str:
    """The class name one grade up: "7B" -> "8B", "Grade 7 Blue" -> "Grade 8 Blue".

    Only the first number changes; a name without one stays as it is.
    """
    return re.sub(r"\d+", lambda m: str(int(m.group()) + 1), name, count=1)


@dataclass
class PastedStudent:
    """One student read from a pasted list; `line` is 1-based, for error messages."""

    line: int
    first_name: str
    last_name: str
    student_no: str | None = None
    notes: str = ""


_STUDENT_NO = re.compile(r"[A-Za-z]{0,3}[-_]?\d+")  # 7, 007, S007, S-007
_LIST_NUMBER = re.compile(r"\d+[.)]")  # "1." or "1)" from a numbered list
_BULLET = re.compile(r"[-*•·◦▪–]\s*")  # "- " or "• " from a bulleted list


def _unquote(text: str) -> str:
    """`text` without the double quotes a CSV file puts around a cell: '"Ada"' -> "Ada"."""
    text = text.strip()
    return text[1:-1].replace('""', '"').strip() if len(text) >= 2 and text[0] == text[-1] == '"' else text


def _parse_name(text: str) -> tuple[str, str] | None:
    """(first, last) from "Last, First", "LAST First" or "First [Middle] Last"; None if
    there is one word."""
    if "," in text:
        last, _, first = text.partition(",")
        first, last = first.strip(), last.strip()
        return (first, last) if first and last else None
    words = text.split()
    if len(words) < 2:
        return None
    # "LOVELACE Ada" or "VAN DER BERG Anna": the surname first, in capitals, as some
    # school systems print it. Only when the rest isn't in capitals too.
    capitals = 0
    while capitals < len(words) and words[capitals].isupper() and len(words[capitals]) > 1:
        capitals += 1
    if 0 < capitals < len(words):
        return " ".join(words[capitals:]), " ".join(words[:capitals])
    return " ".join(words[:-1]), words[-1]


def parse_student_list(text: str) -> tuple[list[PastedStudent], list[str]]:
    """Read students from pasted text, one per line. Returns (students, problems).

    A line can be "First Last", "Last, First", either one after a student number
    ("007 Ada Lovelace"), or columns copied from a spreadsheet or a CSV file
    separated by tabs, semicolons or (two or more) commas: first and last name;
    number, first and last name; or number, first and last name and notes. Blank lines and a heading row (containing "name") are skipped.
    """
    students: list[PastedStudent] = []
    problems: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        # Two commas or more are CSV columns; one is "Last, First".
        separator = "\t" if "\t" in line else ";" if ";" in line else "," if line.count(",") >= 2 else None
        if separator:
            if separator == ",":  # a quoted cell may hold a comma: "Lovelace, Ada" in a CSV line
                cells = [c.strip() for c in next(csv.reader([line], skipinitialspace=True))]
            else:
                cells = [_unquote(c) for c in line.split(separator)]
            cells = [c for c in cells if c]
            if "name" in line.casefold() and not students and not problems:
                continue  # header row
            if len(cells) == 2:
                students.append(PastedStudent(line_no, cells[0], cells[1]))
            elif len(cells) == 3:
                students.append(PastedStudent(line_no, cells[1], cells[2], cells[0]))
            elif len(cells) == 4:
                students.append(PastedStudent(line_no, cells[1], cells[2], cells[0], cells[3]))
            else:
                problems.append(f"Line {line_no}: expected first and last name columns: {line}")
            continue

        student_no = None
        line = _unquote(_BULLET.sub("", line, count=1) if _BULLET.match(line) else line)
        first_word, _, rest = line.partition(" ")
        if _LIST_NUMBER.fullmatch(first_word):
            line = rest.strip()
        elif _STUDENT_NO.fullmatch(first_word) and rest.strip():
            student_no, line = first_word, rest.strip()
        name = _parse_name(line)
        if name is None:
            problems.append(f"Line {line_no}: needs a first and a last name: {raw.strip()}")
        else:
            students.append(PastedStudent(line_no, name[0], name[1], student_no))
    return students, problems


def repeated_names(students: list[PastedStudent]) -> list[str]:
    """Names that appear more than once in a pasted list, ignoring case, each named once
    as first written."""
    first_seen: dict[tuple[str, str], str] = {}
    repeated: dict[tuple[str, str], str] = {}
    for s in students:
        key = (s.first_name.casefold(), s.last_name.casefold())
        if key in first_seen:
            repeated.setdefault(key, first_seen[key])
        else:
            first_seen[key] = f"{s.first_name} {s.last_name}"
    return list(repeated.values())


def fix_name_case(name: str) -> str:
    """A name typed all in capitals or all in lowercase, written the usual way:
    "LOVELACE" -> "Lovelace", "anne-marie o'brien" -> "Anne-Marie O'Brien".

    A name that already mixes cases is left as typed ("McDonald", "van Gogh").
    """
    if name.upper() != name and name.lower() != name:
        return name
    return re.sub(r"(^|[\s\-'’])(\w)", lambda m: m.group(1) + m.group(2).upper(), name.lower())


def fix_pasted_case(students: list[PastedStudent]) -> list[PastedStudent]:
    """The pasted students with fix_name_case() applied to their first and last names."""
    return [
        replace(s, first_name=fix_name_case(s.first_name), last_name=fix_name_case(s.last_name))
        for s in students
    ]


_RECORD_WORDS = {  # what recorded() counts, in words: (one, many)
    "attendance": ("attendance mark", "attendance marks"),
    "scores": ("score", "scores"),
    "assignments": ("assignment", "assignments"),
    "categories": ("grade category", "grade categories"),
    "seating": ("seating plan", "seating plans"),
}


def describe_records(counts: dict[str, int]) -> str:
    """e.g. "120 attendance marks, 4 assignments and 1 seating plan"; "" if all are 0."""
    parts = [
        f"{n} {_RECORD_WORDS[key][0] if n == 1 else _RECORD_WORDS[key][1]}"
        for key, n in counts.items()
        if n and key in _RECORD_WORDS
    ]
    return ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else "".join(parts)


class RosterService:
    def __init__(
        self, classes: ClassRepository, students: StudentRepository, subjects: SubjectRepository
    ):
        self.classes = classes
        self.students = students
        self.subjects = subjects

    # --- classes ---------------------------------------------------------

    def list_classes(self, term: str | None = None) -> list[SchoolClass]:
        """All classes, or only those of one school year when `term` is given, sorted
        as people read the names ("7B" before "10A")."""
        classes = sorted(self.classes.list_all(), key=lambda c: (natural_key(c.name), c.term, c.id))
        return classes if term is None else [c for c in classes if c.term == term]

    def list_terms(self) -> list[str]:
        return self.classes.list_terms()

    def class_counts(self) -> dict[int, tuple[int, int]]:
        """{class id: (active students, subjects)}."""
        return self.classes.counts()

    def get_class(self, class_id: int) -> SchoolClass | None:
        return self.classes.get(class_id)

    def save_class(self, school_class: SchoolClass, first_subject: str = "") -> SchoolClass:
        """Create the class if it has no id yet, otherwise update it.

        `first_subject`, if given for a new class, is created with it in one step.
        """
        school_class = replace(
            school_class, name=_clean(school_class.name), term=_clean(school_class.term)
        )
        if not school_class.name:
            raise RosterError("Class name is required.")
        _check_length(school_class.name, CLASS_NAME_MAX, "A class name")
        _check_length(school_class.term, TERM_MAX, "A school year")
        self._check_name_free(school_class.name, school_class.term, school_class.id)
        if school_class.id is not None:
            self.classes.update(school_class)
            return school_class
        with transaction(self.classes.conn):
            school_class = self.classes.add(school_class)
            if _clean(first_subject):
                self.save_subject(Subject(class_id=school_class.id, name=first_subject))
        return school_class

    def start_new_year(
        self, new_term: str, plan: list[tuple[int, str]], copy_students: bool = True
    ) -> list[SchoolClass]:
        """Create next year's classes from existing ones, all at once or not at all.

        `plan` lists (existing class id, name for the new class), e.g. (7B's id, "8B").
        Each new class gets the old class's subjects and teachers and, if
        `copy_students`, its active students (as new records, so last year's
        attendance and grades stay with last year's class). Nothing else is copied.
        """
        new_term = _clean(new_term)
        if not new_term:
            raise RosterError("Enter the new school year, e.g. 2026-2027.")
        if not plan:
            raise RosterError("Choose at least one class to copy.")
        names = [_clean(name) for _id, name in plan]
        if not all(names):
            raise RosterError("Every new class needs a name.")
        seen: set[str] = set()
        for name in names:
            if name.casefold() in seen:
                raise RosterError(f"The name {name} is used twice.")
            seen.add(name.casefold())

        created = []
        with transaction(self.classes.conn):
            for (source_id, _), name in zip(plan, names):
                if self.classes.get(source_id) is None:
                    raise RosterError("One of the classes to copy no longer exists.")
                new_class = self.save_class(SchoolClass(name=name, term=new_term))
                for subject in self.subjects.list_for_class(source_id):
                    self.subjects.add(
                        Subject(class_id=new_class.id, name=subject.name, teacher=subject.teacher)
                    )
                if copy_students:
                    for student in self.students.list_for_class(source_id):
                        self.students.add(replace(student, id=None, class_id=new_class.id))
                created.append(new_class)
        return created

    def rename_term(self, old: str, new: str) -> int:
        """Change the school year of every class in `old` to `new`, e.g. to fix a typo
        ("2026-207"), or give the classes without a school year (`old` "") one.
        Returns how many classes changed. All or nothing: a class name already used
        in `new` stops the whole rename."""
        new = _clean(new)
        if not new:
            raise RosterError("Enter the school year, e.g. 2026-2027.")
        _check_length(new, TERM_MAX, "A school year")
        if new == old:
            return 0
        classes = self.list_classes(old)
        if not classes:
            raise RosterError("There are no classes in that school year any more.")
        with transaction(self.classes.conn):
            for school_class in classes:
                self._check_name_free(school_class.name, new, school_class.id)
            return self.classes.rename_term(old, new)

    def _check_name_free(self, name: str, term: str, class_id: int | None) -> None:
        existing = self.classes.find_by_name(name, term)
        if existing and existing.id != class_id:
            year = f" in {term}" if term else " without a school year"
            raise RosterError(f"There is already a class called {existing.name}{year}.")

    def delete_class(self, class_id: int) -> None:
        """Delete a class with its students and subjects, but only while nothing is
        recorded for them: no attendance, grades, grade categories or seating.

        This is for undoing a mistake, e.g. a class created in the wrong school year.
        """
        try:
            self.classes.delete(class_id)
        except sqlite3.IntegrityError:
            what = describe_records(self.classes.recorded(class_id)) or "attendance, grades or seating"
            raise RosterError(
                f"This class can't be deleted: it has {what} recorded. Its school year keeps it "
                "as it is; to start a new year, use New school year."
            ) from None

    # --- subjects --------------------------------------------------------

    def list_subjects(self, class_id: int) -> list[Subject]:
        return self.subjects.list_for_class(class_id)

    def get_subject(self, subject_id: int) -> Subject | None:
        return self.subjects.get(subject_id)

    def save_subject(self, subject: Subject) -> Subject:
        """Validate and create (id is None) or update a subject."""
        subject = replace(subject, name=_clean(subject.name), teacher=_clean(subject.teacher))
        if not subject.name:
            raise RosterError("Subject name is required.")
        _check_length(subject.name, SUBJECT_NAME_MAX, "A subject name")
        _check_length(subject.teacher, SUBJECT_NAME_MAX, "A teacher's name")
        if self.classes.get(subject.class_id) is None:
            raise RosterError("The selected class no longer exists.")
        existing = self.subjects.find_by_name(subject.class_id, subject.name)
        if existing and existing.id != subject.id:
            raise RosterError(f"This class already has a subject called {existing.name}.")

        if subject.id is None:
            return self.subjects.add(subject)
        self.subjects.update(subject)
        return subject

    def copy_subjects(self, from_class_id: int, to_class_id: int) -> list[Subject]:
        """Give `to_class_id` each subject of `from_class_id` it doesn't have yet (by name,
        ignoring case), with its teacher. Grades and attendance aren't copied.
        Returns the subjects added, which may be none."""
        if self.classes.get(to_class_id) is None or self.classes.get(from_class_id) is None:
            raise RosterError("The selected class no longer exists.")
        added = []
        with transaction(self.subjects.conn):
            for subject in self.subjects.list_for_class(from_class_id):
                if self.subjects.find_by_name(to_class_id, subject.name) is None:
                    added.append(self.subjects.add(Subject(to_class_id, subject.name, subject.teacher)))
        return added

    def subject_names(self) -> list[str]:
        """Subject names used in any class, to offer while typing a new one."""
        return self.subjects.distinct_values("name")

    def teacher_names(self) -> list[str]:
        """Teachers named on any subject, to offer while typing one."""
        return self.subjects.distinct_values("teacher")

    def delete_subject(self, subject_id: int) -> None:
        """Delete a subject only if it has no grades or attendance yet."""
        try:
            self.subjects.delete(subject_id)
        except sqlite3.IntegrityError:
            what = describe_records(self.subjects.recorded(subject_id)) or "grades or attendance"
            raise RosterError(f"This subject can't be deleted: it has {what} recorded.") from None

    # --- students --------------------------------------------------------

    def list_students(
        self, class_id: int, search: str = "", include_inactive: bool = False
    ) -> list[Student]:
        """The class's students in name order; with `search`, only those matching()."""
        students = self.students.list_for_class(class_id, include_inactive)
        return [s for s in students if matches(s, search)] if _clean(search) else students

    def save_student(self, student: Student) -> Student:
        """Validate and create (id is None) or update a student."""
        student = replace(
            student,
            first_name=_clean(student.first_name),
            last_name=_clean(student.last_name),
            student_no=_clean(student.student_no) or None,
            notes=(student.notes or "").strip(),
        )
        if not student.first_name or not student.last_name:
            raise RosterError("First and last name are required.")
        _check_length(student.first_name, NAME_MAX, "A first name")
        _check_length(student.last_name, NAME_MAX, "A last name")
        if student.student_no:
            _check_length(student.student_no, STUDENT_NO_MAX, "A student number")
        _check_length(student.notes, STUDENT_NOTES_MAX, "The notes")
        if self.classes.get(student.class_id) is None:
            raise RosterError("The selected class no longer exists.")
        if student.student_no:
            existing = self.students.find_by_student_no(student.class_id, student.student_no)
            if existing and existing.id != student.id:
                who = existing.full_name
                if not existing.active:  # hidden from the list, so say why the number is taken
                    who += ", who is inactive but keeps it"
                raise RosterError(f"Student number {student.student_no} is already used by {who}.")

        if student.id is None:
            return self.students.add(student)
        self.students.update(student)
        return student

    def add_students(self, class_id: int, pasted: list[PastedStudent]) -> list[Student]:
        """Add several students at once, all or none. A problem in any one of them
        raises RosterError naming its line, and nothing is added."""
        added = []
        with transaction(self.students.conn):
            for p in pasted:
                student = Student(
                    class_id=class_id,
                    first_name=p.first_name,
                    last_name=p.last_name,
                    student_no=p.student_no,
                    notes=p.notes,
                )
                try:
                    added.append(self.save_student(student))
                except RosterError as exc:
                    raise RosterError(f"Line {p.line}: {exc}") from None
        return added

    def already_in_class(self, class_id: int, pasted: list[PastedStudent]) -> list[PastedStudent]:
        """The pasted students whose name a student of the class already has (ignoring
        case, inactive students included), e.g. when an updated list is pasted again."""
        return [
            p
            for p in pasted
            if self.students.find_by_name(class_id, _clean(p.first_name), _clean(p.last_name))
        ]

    def number_problems(self, class_id: int, pasted: list[PastedStudent]) -> list[str]:
        """Why add_students() would refuse the pasted numbers, one line each, so the list
        can be fixed before adding: a number another student of the class has."""
        problems = []
        for p in pasted:
            if p.student_no and (owner := self.students.find_by_student_no(class_id, p.student_no)):
                problems.append(f"Line {p.line}: student number {p.student_no} is already used by {owner.full_name}.")
        return problems

    def transfer_student(self, student_id: int, class_id: int) -> Student:
        """Move a student to another class, e.g. after a change of homeroom.

        A student with nothing recorded yet simply moves. Otherwise their
        attendance and grades stay with the old class: that record is made
        inactive and a new, active one is created in `class_id`. The student
        number is kept unless another student in the new class has it; then
        they get the new class's next free number.
        Returns the student as they are in the new class.
        """
        student = self.students.get(student_id)
        if student is None:
            raise RosterError("This student no longer exists.")
        if self.classes.get(class_id) is None:
            raise RosterError("The selected class no longer exists.")
        if student.class_id == class_id:
            raise RosterError(f"{student.full_name} is already in this class.")

        student_no = student.student_no
        if student_no and self.students.find_by_student_no(class_id, student_no):
            student_no = self.suggest_student_no(class_id) or None  # taken: the next free one
        with transaction(self.students.conn):
            if not self.students.has_records(student.id):
                moved = replace(student, class_id=class_id, student_no=student_no, active=True)
                self.students.update(moved)
                self.students.set_class(student.id, class_id)
                return moved
            self.students.set_active(student.id, False)
            return self.students.add(
                replace(student, id=None, class_id=class_id, student_no=student_no, active=True)
            )

    def suggest_student_no(self, class_id: int) -> str:
        """The number after the highest one in the class, keeping its prefix and
        zero padding: "S007" -> "S008". "" if the class uses no numbers yet."""
        numbers = self._numbers(class_id)
        return next(_numbers_after(numbers), "")

    def number_pasted(self, class_id: int, pasted: list[PastedStudent]) -> list[PastedStudent]:
        """`pasted`, with the next free numbers of the class given, in list order, to
        those without one. Unchanged if neither the class nor the list uses numbers."""
        numbers = self._numbers(class_id) + [p.student_no for p in pasted if p.student_no]
        free = _numbers_after(numbers)
        return [p if p.student_no else replace(p, student_no=next(free, None)) for p in pasted]

    def _numbers(self, class_id: int) -> list[str]:
        """Every number used in the class, inactive students' too."""
        return [s.student_no for s in self.students.list_for_class(class_id, include_inactive=True) if s.student_no]

    def unnumbered_students(self, class_id: int) -> list[Student]:
        """The class's active students without a student number, in name order."""
        return [s for s in self.students.list_for_class(class_id) if not s.student_no]

    def number_students(self, class_id: int, first: str) -> list[Student]:
        """Give each active student without a number one, in name order, counting up
        from `first` ("S031", "S032", ...) and skipping numbers already used.
        Returns the students numbered."""
        m = re.fullmatch(r"(.*?)(\d+)", _clean(first))
        if m is None:
            raise RosterError("The first number has to end in digits, e.g. 31 or S031.")
        prefix, digits = m.groups()
        free = _free_numbers(prefix, int(digits), len(digits), self._numbers(class_id))
        numbered = []
        with transaction(self.students.conn):
            for student in self.unnumbered_students(class_id):
                student = replace(student, student_no=next(free))
                self.students.update(student)
                numbered.append(student)
        return numbered

    def same_name_students(self, student: Student) -> list[Student]:
        """Other students in the same class with the same name, so the UI can ask
        before adding a second one. Two students may share a name, so this isn't an error."""
        matches = self.students.find_by_name(
            student.class_id, _clean(student.first_name), _clean(student.last_name)
        )
        return [s for s in matches if s.id != student.id]

    def can_delete_student(self, student_id: int) -> bool:
        """True while no attendance, score or seat refers to the student."""
        return not self.students.has_records(student_id)

    def delete_student(self, student_id: int) -> None:
        """Delete a student added by mistake, but only while nothing is recorded for
        them; otherwise they can only be deactivated, so their history is kept."""
        with transaction(self.students.conn):
            if self.students.has_records(student_id):
                raise RosterError(
                    "This student has attendance, grades or a seat recorded and can't be "
                    "deleted. Deactivate them instead."
                )
            try:
                self.students.delete(student_id)
            except sqlite3.IntegrityError:
                raise RosterError("This student has records and can't be deleted.") from None

    def deactivate_student(self, student_id: int) -> None:
        """Hide a student from day-to-day lists. Their history is kept."""
        self.students.set_active(student_id, False)

    def reactivate_student(self, student_id: int) -> None:
        self.students.set_active(student_id, True)
