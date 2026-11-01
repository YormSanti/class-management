import pytest

from app.models import SchoolClass, Student, Subject
from app.services.roster import RosterError, RosterService, move_up, next_term


@pytest.fixture
def class_id(roster: RosterService) -> int:
    return roster.save_class(SchoolClass(name="7B", term="2026 T1")).id


def _add(roster: RosterService, class_id: int, first: str, last: str, no: str | None = None) -> Student:
    return roster.save_student(Student(class_id=class_id, first_name=first, last_name=last, student_no=no))


def test_class_requires_name(roster: RosterService):
    with pytest.raises(RosterError):
        roster.save_class(SchoolClass(name="   "))


def test_class_update(roster: RosterService, class_id: int):
    roster.save_class(SchoolClass(id=class_id, name="7C"))
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


def test_class_with_students_but_no_records_can_be_deleted(roster: RosterService, class_id: int):
    _add(roster, class_id, "Ada", "Lovelace")
    gone = _add(roster, class_id, "Alan", "Turing")
    roster.deactivate_student(gone.id)
    roster.delete_class(class_id)
    assert roster.list_classes() == []


def test_class_with_attendance_cannot_be_deleted(roster: RosterService, class_id: int, conn):
    ada = _add(roster, class_id, "Ada", "Lovelace")
    conn.execute(
        "INSERT INTO attendance (student_id, date, status) VALUES (?, '2026-09-01', 'present')", (ada.id,)
    )
    with pytest.raises(RosterError, match="attendance, grades or seating"):
        roster.delete_class(class_id)
    assert [s.id for s in roster.list_students(class_id)] == [ada.id]  # nothing was half-deleted


def test_new_class_can_get_its_first_subject(roster: RosterService):
    school_class = roster.save_class(SchoolClass(name="8A"), first_subject="  Science ")
    assert [s.name for s in roster.list_subjects(school_class.id)] == ["Science"]
    assert roster.list_subjects(roster.save_class(SchoolClass(name="8B")).id) == []


def test_subjects_are_sorted_and_trimmed(roster: RosterService, class_id: int):
    roster.save_subject(Subject(class_id=class_id, name="science", teacher=" Ms. Chen "))
    roster.save_subject(Subject(class_id=class_id, name="Art"))
    subjects = roster.list_subjects(class_id)
    assert [(s.name, s.teacher) for s in subjects] == [("Art", ""), ("science", "Ms. Chen")]


def test_subject_requires_name(roster: RosterService, class_id: int):
    with pytest.raises(RosterError):
        roster.save_subject(Subject(class_id=class_id, name="  "))


def test_duplicate_subject_name_is_rejected_ignoring_case(roster: RosterService, class_id: int):
    maths = roster.save_subject(Subject(class_id=class_id, name="Maths"))
    with pytest.raises(RosterError, match="already has a subject called Maths"):
        roster.save_subject(Subject(class_id=class_id, name="MATHS"))
    maths.teacher = "Mr. Ito"
    roster.save_subject(maths)  # renaming or editing itself is fine
    other = roster.save_class(SchoolClass(name="8A")).id
    roster.save_subject(Subject(class_id=other, name="Maths"))


def test_subject_with_grades_cannot_be_deleted(roster: RosterService, class_id: int, conn):
    maths = roster.save_subject(Subject(class_id=class_id, name="Maths")).id
    art = roster.save_subject(Subject(class_id=class_id, name="Art")).id
    conn.execute("INSERT INTO categories (subject_id, name, weight) VALUES (?, 'Tests', 1)", (maths,))
    with pytest.raises(RosterError):
        roster.delete_subject(maths)
    roster.delete_subject(art)
    assert [s.name for s in roster.list_subjects(class_id)] == ["Maths"]


def test_class_with_only_empty_subjects_can_be_deleted(roster: RosterService):
    school_class = roster.save_class(SchoolClass(name="8A"), first_subject="Science")
    roster.delete_class(school_class.id)
    assert roster.list_classes() == []


def test_class_with_graded_subject_cannot_be_deleted(roster: RosterService, conn):
    school_class = roster.save_class(SchoolClass(name="8A"), first_subject="Science")
    subject_id = roster.list_subjects(school_class.id)[0].id
    conn.execute("INSERT INTO categories (subject_id, name, weight) VALUES (?, 'Tests', 1)", (subject_id,))
    with pytest.raises(RosterError):
        roster.delete_class(school_class.id)
    assert roster.list_subjects(school_class.id)  # nothing was half-deleted


@pytest.mark.parametrize(
    "term, expected",
    [("2025-2026", "2026-2027"), ("2025 - 2026", "2026 - 2027"), ("2026", "2027"),
     ("Semester 1 2026", "Semester 1 2027"), ("Autumn", ""), ("", ""),
     ("2025-26", "2026-27"), ("2025/26", "2026/27"), ("2099-00", "2100-01"), ("SY 2025–26", "SY 2026–27")],
)  # fmt: skip
def test_next_term(term: str, expected: str):
    assert next_term(term) == expected


def test_class_names_are_unique_within_a_school_year(roster: RosterService):
    roster.save_class(SchoolClass(name="7B", term="2025-2026"))
    with pytest.raises(RosterError, match="already a class called 7B in 2025-2026"):
        roster.save_class(SchoolClass(name="7b", term="2025-2026"))
    roster.save_class(SchoolClass(name="7B", term="2026-2027"))  # another year is fine


def test_terms_and_classes_by_year(roster: RosterService):
    for name, term in [("7B", "2025-2026"), ("8A", "2026-2027"), ("7C", "2025-2026"), ("Club", "")]:
        roster.save_class(SchoolClass(name=name, term=term))
    assert roster.list_terms() == ["2026-2027", "2025-2026"]
    assert [c.name for c in roster.list_classes("2025-2026")] == ["7B", "7C"]
    assert [c.name for c in roster.list_classes("")] == ["Club"]
    assert len(roster.list_classes()) == 4


def test_start_new_year_copies_subjects_and_active_students(roster: RosterService):
    old = roster.save_class(SchoolClass(name="7B", term="2025-2026"), first_subject="Math")
    roster.save_subject(Subject(class_id=old.id, name="Science", teacher="Ms. Chen"))
    ada = _add(roster, old.id, "Ada", "Lovelace", no="001")
    ada.notes = "Front row"
    roster.save_student(ada)
    roster.deactivate_student(_add(roster, old.id, "Left", "School").id)

    (new,) = roster.start_new_year(" 2026-2027 ", [(old.id, " 8B ")])

    assert (new.name, new.term) == ("8B", "2026-2027")
    assert [(s.name, s.teacher) for s in roster.list_subjects(new.id)] == [("Math", ""), ("Science", "Ms. Chen")]
    (copy,) = roster.list_students(new.id, include_inactive=True)
    assert (copy.full_name, copy.student_no, copy.notes) == ("Ada Lovelace", "001", "Front row")
    assert copy.id != ada.id
    assert len(roster.list_students(old.id, include_inactive=True)) == 2  # last year is untouched


def test_start_new_year_without_students(roster: RosterService):
    old = roster.save_class(SchoolClass(name="7B", term="2025-2026"))
    _add(roster, old.id, "Ada", "Lovelace")
    (new,) = roster.start_new_year("2026-2027", [(old.id, "8B")], copy_students=False)
    assert roster.list_students(new.id) == []


@pytest.mark.parametrize(
    "term, names, message",
    [("", ["8B"], "new school year"), ("2026-2027", [""], "needs a name"),
     ("2026-2027", ["8B", "8b"], "used twice"), ("2026-2027", ["8A", "Taken"], "already a class called Taken")],
)  # fmt: skip
def test_start_new_year_is_all_or_nothing(roster: RosterService, term, names, message):
    a = roster.save_class(SchoolClass(name="7A", term="2025-2026")).id
    b = roster.save_class(SchoolClass(name="7B", term="2025-2026")).id
    roster.save_class(SchoolClass(name="Taken", term="2026-2027"))
    with pytest.raises(RosterError, match=message):
        roster.start_new_year(term, list(zip([a, b], names)))
    assert [c.name for c in roster.list_classes("2026-2027")] == ["Taken"]


@pytest.mark.parametrize(
    "name, expected", [("7B", "8B"), ("Grade 9 Blue", "Grade 10 Blue"), ("12A", "13A"), ("Choir", "Choir")]
)
def test_move_up(name: str, expected: str):
    assert move_up(name) == expected


def test_class_counts_active_students_and_subjects(roster: RosterService, class_id: int):
    empty = roster.save_class(SchoolClass(name="8A")).id
    _add(roster, class_id, "Ada", "Lovelace")
    gone = _add(roster, class_id, "Alan", "Turing")
    roster.deactivate_student(gone.id)
    roster.save_subject(Subject(class_id=class_id, name="Maths"))
    roster.save_subject(Subject(class_id=class_id, name="Science"))
    assert roster.class_counts() == {class_id: (1, 2), empty: (0, 0)}


def test_same_name_students_ignores_case_and_self(roster: RosterService, class_id: int):
    ada = _add(roster, class_id, "Ada", "Lovelace")
    other_class = roster.save_class(SchoolClass(name="8A")).id
    _add(roster, other_class, "Ada", "Lovelace")
    new = Student(class_id=class_id, first_name=" ada ", last_name="LOVELACE")
    assert [s.id for s in roster.same_name_students(new)] == [ada.id]
    assert roster.same_name_students(ada) == []


@pytest.mark.parametrize(
    "numbers, expected",
    [([], ""), (["abc"], ""), (["1", "2", "10"], "11"), (["007", "003"], "008"),
     (["S-099"], "S-100"), (["A1", "B7"], "B8")],
)  # fmt: skip
def test_suggest_student_no(roster: RosterService, class_id: int, numbers: list[str], expected: str):
    for i, number in enumerate(numbers):
        _add(roster, class_id, "Student", f"Number{i}", no=number)
    assert roster.suggest_student_no(class_id) == expected


def test_suggest_student_no_counts_inactive_students(roster: RosterService, class_id: int):
    gone = _add(roster, class_id, "Alan", "Turing", no="12")
    roster.deactivate_student(gone.id)
    assert roster.suggest_student_no(class_id) == "13"


def test_parse_student_list_formats():
    from app.services.roster import PastedStudent, parse_student_list

    text = """
Ada Lovelace
Hopper, Grace
007 Alan Turing
2. Mary Ann Evans
S-12\tKatherine\tJohnson
Edsger\tDijkstra
Plato
"""
    students, problems = parse_student_list(text)
    assert students == [
        PastedStudent(2, "Ada", "Lovelace"),
        PastedStudent(3, "Grace", "Hopper"),
        PastedStudent(4, "Alan", "Turing", "007"),
        PastedStudent(5, "Mary Ann", "Evans"),
        PastedStudent(6, "Katherine", "Johnson", "S-12"),
        PastedStudent(7, "Edsger", "Dijkstra"),
    ]
    assert problems == ["Line 8: needs a first and a last name: Plato"]


def test_parse_student_list_skips_spreadsheet_header():
    from app.services.roster import parse_student_list

    students, problems = parse_student_list("No.\tFirst name\tLast name\n1\tAda\tLovelace\n")
    assert [(s.student_no, s.first_name, s.last_name) for s in students] == [("1", "Ada", "Lovelace")]
    assert problems == []


def test_add_students_is_all_or_nothing(roster: RosterService, class_id: int):
    from app.services.roster import parse_student_list

    _add(roster, class_id, "Ada", "Lovelace", no="1")
    students, _ = parse_student_list("2 Alan Turing\n1 Grace Hopper\n")
    with pytest.raises(RosterError, match="Line 2: Student number 1 is already used by Ada Lovelace"):
        roster.add_students(class_id, students)
    assert [s.full_name for s in roster.list_students(class_id)] == ["Ada Lovelace"]

    students, _ = parse_student_list("2 Alan Turing\n3 Grace Hopper\n")
    added = roster.add_students(class_id, students)
    assert [s.student_no for s in added] == ["2", "3"]
    assert len(roster.list_students(class_id)) == 3
