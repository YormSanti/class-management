"""Class and student management: validation and rules on top of the repositories."""

import sqlite3
from dataclasses import replace

from app.models import SchoolClass, Student
from app.repositories.class_repo import ClassRepository
from app.repositories.student_repo import StudentRepository


class RosterError(ValueError):
    """A user-facing validation error; the message is safe to show in the UI."""


def _clean(text: str | None) -> str:
    return (text or "").strip()


class RosterService:
    def __init__(self, classes: ClassRepository, students: StudentRepository):
        self.classes = classes
        self.students = students

    # --- classes ---------------------------------------------------------

    def list_classes(self) -> list[SchoolClass]:
        return self.classes.list_all()

    def get_class(self, class_id: int) -> SchoolClass | None:
        return self.classes.get(class_id)

    def save_class(self, school_class: SchoolClass) -> SchoolClass:
        """Create the class if it has no id yet, otherwise update it."""
        school_class = replace(
            school_class,
            name=_clean(school_class.name),
            subject=_clean(school_class.subject),
            term=_clean(school_class.term),
        )
        if not school_class.name:
            raise RosterError("Class name is required.")
        if school_class.id is None:
            return self.classes.add(school_class)
        self.classes.update(school_class)
        return school_class

    def delete_class(self, class_id: int) -> None:
        """Delete a class only if nothing (students, grades, layouts) refers to it."""
        try:
            self.classes.delete(class_id)
        except sqlite3.IntegrityError:
            raise RosterError(
                "This class still has students or other records and can't be deleted."
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
