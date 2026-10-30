"""Class, subject and student management: validation and rules on top of the repositories."""

import re
import sqlite3
from dataclasses import replace

from app.db.connection import transaction
from app.models import SchoolClass, Student, Subject
from app.repositories.class_repo import ClassRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.subject_repo import SubjectRepository


class RosterError(ValueError):
    """A user-facing validation error; the message is safe to show in the UI."""


def _clean(text: str | None) -> str:
    return (text or "").strip()


def next_term(term: str) -> str:
    """Suggest the school year after `term`: "2025-2026" -> "2026-2027", "2026" -> "2027".

    Every 4-digit year in the text moves on by one, keeping the rest as typed.
    Returns "" when there is no year to move on.
    """
    if not re.search(r"\b\d{4}\b", term):
        return ""
    return re.sub(r"\b\d{4}\b", lambda m: str(int(m.group()) + 1), term)


class RosterService:
    def __init__(
        self, classes: ClassRepository, students: StudentRepository, subjects: SubjectRepository
    ):
        self.classes = classes
        self.students = students
        self.subjects = subjects

    # --- classes ---------------------------------------------------------

    def list_classes(self, term: str | None = None) -> list[SchoolClass]:
        """All classes, or only those of one school year when `term` is given."""
        classes = self.classes.list_all()
        return classes if term is None else [c for c in classes if c.term == term]

    def list_terms(self) -> list[str]:
        return self.classes.list_terms()

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

    def _check_name_free(self, name: str, term: str, class_id: int | None) -> None:
        existing = self.classes.find_by_name(name, term)
        if existing and existing.id != class_id:
            year = f" in {term}" if term else " without a school year"
            raise RosterError(f"There is already a class called {existing.name}{year}.")

    def delete_class(self, class_id: int) -> None:
        """Delete a class (and its subjects) only if no students, grades or layouts refer to it."""
        try:
            self.classes.delete(class_id)
        except sqlite3.IntegrityError:
            raise RosterError(
                "This class still has students or other records and can't be deleted."
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
        if self.classes.get(subject.class_id) is None:
            raise RosterError("The selected class no longer exists.")
        existing = self.subjects.find_by_name(subject.class_id, subject.name)
        if existing and existing.id != subject.id:
            raise RosterError(f"This class already has a subject called {existing.name}.")

        if subject.id is None:
            return self.subjects.add(subject)
        self.subjects.update(subject)
        return subject

    def delete_subject(self, subject_id: int) -> None:
        """Delete a subject only if it has no grades or attendance yet."""
        try:
            self.subjects.delete(subject_id)
        except sqlite3.IntegrityError:
            raise RosterError(
                "This subject has grades or attendance and can't be deleted."
            ) from None

    # --- students --------------------------------------------------------

    def list_students(
        self, class_id: int, search: str = "", include_inactive: bool = False
    ) -> list[Student]:
        return self.students.list_for_class(class_id, _clean(search), include_inactive)

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
        if self.classes.get(student.class_id) is None:
            raise RosterError("The selected class no longer exists.")
        if student.student_no:
            existing = self.students.find_by_student_no(student.class_id, student.student_no)
            if existing and existing.id != student.id:
                raise RosterError(
                    f"Student number {student.student_no} is already used by {existing.full_name}."
                )

        if student.id is None:
            return self.students.add(student)
        self.students.update(student)
        return student

    def deactivate_student(self, student_id: int) -> None:
        """Hide a student from day-to-day lists. Their history is kept."""
        self.students.set_active(student_id, False)

    def reactivate_student(self, student_id: int) -> None:
        self.students.set_active(student_id, True)
