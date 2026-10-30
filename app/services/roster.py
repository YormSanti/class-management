"""Class, subject and student management: validation and rules on top of the repositories."""

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


class RosterService:
    def __init__(
        self, classes: ClassRepository, students: StudentRepository, subjects: SubjectRepository
    ):
        self.classes = classes
        self.students = students
        self.subjects = subjects

    # --- classes ---------------------------------------------------------

    def list_classes(self) -> list[SchoolClass]:
        return self.classes.list_all()

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
        if school_class.id is not None:
            self.classes.update(school_class)
            return school_class
        with transaction(self.classes.conn):
            school_class = self.classes.add(school_class)
            if _clean(first_subject):
                self.save_subject(Subject(class_id=school_class.id, name=first_subject))
        return school_class

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
