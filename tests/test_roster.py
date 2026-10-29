import pytest

from app.models import SchoolClass, Student
from app.services.roster import RosterError, RosterService


@pytest.fixture
def class_id(roster: RosterService) -> int:
    return roster.save_class(SchoolClass(name="7B", subject="Maths", term="2026 T1")).id


def _add(roster: RosterService, class_id: int, first: str, last: str, no: str | None = None) -> Student:
    return roster.save_student(Student(class_id=class_id, first_name=first, last_name=last, student_no=no))


def test_class_requires_name(roster: RosterService):
    with pytest.raises(RosterError):
        roster.save_class(SchoolClass(name="   "))


def test_class_update(roster: RosterService, class_id: int):
    roster.save_class(SchoolClass(id=class_id, name="7C", subject="Maths"))
    assert roster.get_class(class_id).name == "7C"


def test_student_names_are_trimmed_and_blank_number_is_none(roster: RosterService, class_id: int):
    student = _add(roster, class_id, "  Ada ", " Lovelace ", no="  ")
    assert (student.first_name, student.last_name, student.student_no) == ("Ada", "Lovelace", None)


def test_student_requires_both_names(roster: RosterService, class_id: int):
    with pytest.raises(RosterError):
        _add(roster, class_id, "Ada", "")


def test_duplicate_student_number_in_same_class_is_rejected(roster: RosterService, class_id: int):
    _add(roster, class_id, "Ada", "Lovelace", no="001")
    with pytest.raises(RosterError, match="already used by Ada Lovelace"):
        _add(roster, class_id, "Alan", "Turing", no="001")


def test_same_student_number_allowed_in_other_class(roster: RosterService, class_id: int):
    other = roster.save_class(SchoolClass(name="8A")).id
    _add(roster, class_id, "Ada", "Lovelace", no="001")
    _add(roster, other, "Alan", "Turing", no="001")


def test_editing_student_keeps_own_number(roster: RosterService, class_id: int):
    student = _add(roster, class_id, "Ada", "Lovelace", no="001")
    student.notes = "Allergic to peanuts"
    roster.save_student(student)
    assert roster.list_students(class_id)[0].notes == "Allergic to peanuts"


def test_students_sorted_by_last_name(roster: RosterService, class_id: int):
    _add(roster, class_id, "Alan", "Turing")
    _add(roster, class_id, "Ada", "Lovelace")
    _add(roster, class_id, "Grace", "hopper")
    assert [s.last_name for s in roster.list_students(class_id)] == ["hopper", "Lovelace", "Turing"]


@pytest.mark.parametrize(
    "term, expected",
    [("ada", ["Ada"]), ("LOVE", ["Ada"]), ("ada love", ["Ada"]), ("00", ["Ada", "Alan"]), ("x", [])],
)
def test_search(roster: RosterService, class_id: int, term: str, expected: list[str]):
    _add(roster, class_id, "Ada", "Lovelace", no="001")
    _add(roster, class_id, "Alan", "Turing", no="002")
    assert [s.first_name for s in roster.list_students(class_id, search=term)] == expected


def test_search_treats_wildcards_literally(roster: RosterService, class_id: int):
    _add(roster, class_id, "Ada", "Lovelace")
    assert roster.list_students(class_id, search="%") == []
    assert roster.list_students(class_id, search="_") == []


def test_deactivated_students_are_hidden_but_kept(roster: RosterService, class_id: int):
    student = _add(roster, class_id, "Ada", "Lovelace")
    roster.deactivate_student(student.id)

    assert roster.list_students(class_id) == []
    hidden = roster.list_students(class_id, include_inactive=True)
    assert [(s.id, s.active) for s in hidden] == [(student.id, False)]

    roster.reactivate_student(student.id)
    assert roster.list_students(class_id)[0].active


def test_empty_class_can_be_deleted(roster: RosterService, class_id: int):
    roster.delete_class(class_id)
    assert roster.list_classes() == []


def test_class_with_students_cannot_be_deleted(roster: RosterService, class_id: int):
    _add(roster, class_id, "Ada", "Lovelace")
    with pytest.raises(RosterError):
        roster.delete_class(class_id)
    assert roster.get_class(class_id) is not None
