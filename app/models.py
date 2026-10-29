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
    name: str
    subject: str = ""
    term: str = ""
    id: int | None = None

    @property
    def display_name(self) -> str:
        details = " · ".join(part for part in (self.subject, self.term) if part)
        return f"{self.name} ({details})" if details else self.name


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
    id: int | None = None


@dataclass
class Category:
    class_id: int
    name: str
    weight: float
    id: int | None = None


@dataclass
class Assignment:
    class_id: int
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
