"""Plain dataclasses mirroring the database tables. `id` is None until saved."""

from dataclasses import dataclass
from datetime import date
from enum import Enum


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"


@dataclass
class SchoolClass:
    """A group of students, e.g. 7B. Grades are kept per subject."""

    name: str
    term: str = ""
    id: int | None = None

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.term})" if self.term else self.name


@dataclass
class Subject:
    """A subject taught to one class, e.g. Mathematics in 7B, with its own gradebook."""

    class_id: int
    name: str
    teacher: str = ""  # empty when the app's user teaches it
    id: int | None = None


@dataclass
class Student:
    class_id: int
    first_name: str
    last_name: str
    student_no: str | None = None
    active: bool = True
    notes: str = ""
    id: int | None = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


@dataclass
class AttendanceRecord:
    student_id: int
    date: date
    status: AttendanceStatus
    note: str = ""
    subject_id: int | None = None  # None = daily (homeroom) attendance
    id: int | None = None


@dataclass
class Category:
    subject_id: int
    name: str
    weight: float
    id: int | None = None


@dataclass
class Assignment:
    subject_id: int
    category_id: int
    title: str
    max_score: float
    date: date | None = None
    id: int | None = None


@dataclass
class Score:
    assignment_id: int
    student_id: int
    score: float | None  # None = not submitted / exempt, not zero
    id: int | None = None


@dataclass
class SeatLayout:
    class_id: int
    name: str
    rows: int
    cols: int
    id: int | None = None


@dataclass
class Seat:
    layout_id: int
    row: int
    col: int
    student_id: int | None = None
