import pytest

from app.models import SchoolClass, Student, Subject
from app.services.roster import RosterError, RosterService, move_up, next_term, number_key, parse_student_list


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


def test_repeated_spaces_in_names_are_collapsed(roster: RosterService, class_id: int):
    student = _add(roster, class_id, "Mary   Ann", "van  der Berg")
    assert (student.first_name, student.last_name) == ("Mary Ann", "van der Berg")
    school_class = roster.save_class(SchoolClass(name="Grade  7   Blue", term="2026 -  2027"))
    assert (school_class.name, school_class.term) == ("Grade 7 Blue", "2026 - 2027")
    subject = roster.save_subject(Subject(class_id=class_id, name="Social   Studies", teacher=" Mr  Lee "))
    assert (subject.name, subject.teacher) == ("Social Studies", "Mr Lee")


def test_student_requires_both_names(roster: RosterService, class_id: int):
    with pytest.raises(RosterError):
        _add(roster, class_id, "Ada", "")


def test_student_names_have_a_length_limit(roster: RosterService, class_id: int):
    _add(roster, class_id, "A" * 60, "Lovelace")
    with pytest.raises(RosterError, match="A last name can be at most 60 characters; this one has 61"):
        _add(roster, class_id, "Ada", "L" * 61)
    with pytest.raises(RosterError, match="A first name"):
        _add(roster, class_id, "A" * 61, "Lovelace")


def test_duplicate_student_number_in_same_class_is_rejected(roster: RosterService, class_id: int):
    _add(roster, class_id, "Ada", "Lovelace", no="001")
    with pytest.raises(RosterError, match="already used by Ada Lovelace"):
        _add(roster, class_id, "Alan", "Turing", no="001")


def test_student_numbers_differing_only_in_case_are_the_same(roster: RosterService, class_id: int):
    _add(roster, class_id, "Ada", "Lovelace", no="S007")
    with pytest.raises(RosterError, match="already used by Ada Lovelace"):
        _add(roster, class_id, "Alan", "Turing", no="s007")
    _add(roster, class_id, "Grace", "Hopper", no="s008")
    assert roster.suggest_student_no(class_id) == "s009"


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
    [("ada", ["Ada"]), ("LOVE", ["Ada"]), ("ada love", ["Ada"]), ("00", ["Ada", "Alan"]), ("x", []),
     ("lovelace ada", ["Ada"]), ("Turing, Al", ["Alan"]), ("ada  lovelace", ["Ada"])],
)
def test_search(roster: RosterService, class_id: int, term: str, expected: list[str]):
    _add(roster, class_id, "Ada", "Lovelace", no="001")
    _add(roster, class_id, "Alan", "Turing", no="002")
    assert [s.first_name for s in roster.list_students(class_id, search=term)] == expected


def test_search_looks_in_the_notes_too(roster: RosterService, class_id: int):
    roster.save_student(Student(class_id=class_id, first_name="Ada", last_name="Lovelace", notes="Nut allergy"))
    _add(roster, class_id, "Alan", "Turing")
    assert [s.first_name for s in roster.list_students(class_id, search="ALLERGY")] == ["Ada"]


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
    with pytest.raises(RosterError, match="it has 1 attendance mark recorded"):
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
    ada = _add(roster, class_id, "Ada", "Lovelace")
    conn.execute(
        "INSERT INTO attendance (student_id, subject_id, date, status) VALUES (?, ?, '2026-09-01', 'late')",
        (ada.id, maths),
    )
    with pytest.raises(RosterError, match="it has 1 attendance mark and 1 grade category recorded"):
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
    with pytest.raises(RosterError, match="it has 1 grade category recorded"):
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


def test_parse_student_list_reads_semicolon_columns():
    from app.services.roster import parse_student_list

    text = "No;First name;Last name\n1;Ada;Lovelace\nGrace ; Hopper\n;;\n"
    students, problems = parse_student_list(text)
    assert [(s.student_no, s.first_name, s.last_name) for s in students] == [
        ("1", "Ada", "Lovelace"),
        (None, "Grace", "Hopper"),
    ]
    assert problems == ["Line 4: expected first and last name columns: ;;"]


def test_repeated_names_in_a_pasted_list():
    from app.services.roster import parse_student_list, repeated_names

    students, _ = parse_student_list("Ada Lovelace\nAlan Turing\nada lovelace\nAda Lovelace\n")
    assert repeated_names(students) == ["Ada Lovelace"]
    assert repeated_names(students[:2]) == []


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


def test_number_students_numbers_those_without_one_in_name_order(roster: RosterService, class_id: int):
    _add(roster, class_id, "Ada", "Lovelace", no="S031")
    turing = _add(roster, class_id, "Alan", "Turing")
    hopper = _add(roster, class_id, "Grace", "Hopper")
    gone = _add(roster, class_id, "Old", "Student")
    roster.deactivate_student(gone.id)
    assert [s.id for s in roster.unnumbered_students(class_id)] == [hopper.id, turing.id]
    numbered = roster.number_students(class_id, "S030")
    assert [(s.id, s.student_no) for s in numbered] == [(hopper.id, "S030"), (turing.id, "S032")]  # S031 is taken
    assert roster.unnumbered_students(class_id) == []
    everyone = roster.list_students(class_id, include_inactive=True)
    assert [s.student_no for s in everyone if s.id == gone.id] == [None]  # inactive students are left alone


def test_number_students_needs_a_number_ending_in_digits(roster: RosterService, class_id: int):
    _add(roster, class_id, "Alan", "Turing")
    with pytest.raises(RosterError, match="end in digits"):
        roster.number_students(class_id, "S")
    assert roster.number_students(class_id, " 7 ")[0].student_no == "7"


def test_number_pasted_gives_the_next_free_numbers_in_list_order(roster: RosterService, class_id: int):
    _add(roster, class_id, "Ada", "Lovelace", no="S07")
    pasted, _ = parse_student_list("Grace Hopper\nS09 Alan Turing\nKay Mauchly\n")
    assert [p.student_no for p in roster.number_pasted(class_id, pasted)] == ["S10", "S09", "S11"]


def test_number_pasted_leaves_a_class_without_numbers_alone(roster: RosterService, class_id: int):
    pasted, _ = parse_student_list("Grace Hopper\nAlan Turing\n")
    assert roster.number_pasted(class_id, pasted) == pasted


def test_transfer_student_without_records_moves_them(roster: RosterService, class_id: int):
    other = roster.save_class(SchoolClass(name="7C", term="2026 T1")).id
    ada = _add(roster, class_id, "Ada", "Lovelace", no="5")
    moved = roster.transfer_student(ada.id, other)
    assert moved.id == ada.id and moved.class_id == other and moved.student_no == "5"
    assert roster.list_students(class_id, include_inactive=True) == []
    assert [s.id for s in roster.list_students(other)] == [ada.id]


def test_transfer_student_with_records_keeps_history_in_old_class(roster: RosterService, class_id: int, conn):
    other = roster.save_class(SchoolClass(name="7C", term="2026 T1")).id
    ada = _add(roster, class_id, "Ada", "Lovelace", no="5")
    _add(roster, other, "Alan", "Turing", no="5")
    conn.execute(
        "INSERT INTO attendance (student_id, date, status) VALUES (?, '2026-09-01', 'present')", (ada.id,)
    )
    moved = roster.transfer_student(ada.id, other)
    assert moved.id != ada.id and moved.student_no == "6"  # number 5 is taken in 7C
    old = roster.list_students(class_id, include_inactive=True)
    assert [(s.id, s.active) for s in old] == [(ada.id, False)]
    assert {s.full_name for s in roster.list_students(other)} == {"Ada Lovelace", "Alan Turing"}


def test_transfer_student_to_same_class_is_rejected(roster: RosterService, class_id: int):
    ada = _add(roster, class_id, "Ada", "Lovelace")
    with pytest.raises(RosterError, match="already in this class"):
        roster.transfer_student(ada.id, class_id)


def test_student_without_records_can_be_deleted(roster: RosterService, class_id: int):
    ada = _add(roster, class_id, "Ada", "Lovelace")
    assert roster.can_delete_student(ada.id)
    roster.delete_student(ada.id)
    assert roster.list_students(class_id, include_inactive=True) == []


def test_student_with_attendance_cannot_be_deleted(roster: RosterService, class_id: int, conn):
    ada = _add(roster, class_id, "Ada", "Lovelace")
    conn.execute(
        "INSERT INTO attendance (student_id, date, status) VALUES (?, '2026-09-01', 'present')", (ada.id,)
    )
    assert not roster.can_delete_student(ada.id)
    with pytest.raises(RosterError, match="Deactivate them instead"):
        roster.delete_student(ada.id)
    assert [s.id for s in roster.list_students(class_id)] == [ada.id]


def test_example_school_year():
    from datetime import date

    from app.services.roster import example_school_year

    assert example_school_year(date(2026, 11, 21)) == "2026-2027"
    assert example_school_year(date(2027, 3, 1)) == "2026-2027"
    assert example_school_year(date(2027, 7, 1)) == "2027-2028"


def test_subject_and_teacher_names_in_use(roster: RosterService, class_id: int):
    other = roster.save_class(SchoolClass(name="8A")).id
    roster.save_subject(Subject(class_id=class_id, name="science", teacher="Mr Lee"))
    roster.save_subject(Subject(class_id=other, name="Maths"))
    roster.save_subject(Subject(class_id=other, name="Science", teacher="Mr Lee"))
    assert roster.subject_names() == ["Maths", "science", "Science"]
    assert roster.teacher_names() == ["Mr Lee"]


def test_already_in_class_finds_pasted_names_the_class_has(roster: RosterService, class_id: int):
    from app.services.roster import parse_student_list

    _add(roster, class_id, "Ada", "Lovelace")
    gone = _add(roster, class_id, "Alan", "Turing")
    roster.deactivate_student(gone.id)
    pasted, _problems = parse_student_list("ada  LOVELACE\nGrace Hopper\nTuring, Alan")
    assert [p.line for p in roster.already_in_class(class_id, pasted)] == [1, 3]


@pytest.mark.parametrize(
    "typed, expected",
    [("LOVELACE", "Lovelace"), ("ada", "Ada"), ("anne-marie", "Anne-Marie"), ("O'BRIEN", "O'Brien"),
     ("mary ann", "Mary Ann"), ("McDonald", "McDonald"), ("van Gogh", "van Gogh"), ("Ada", "Ada"),
     ("ÉMILE", "Émile"), ("", "")],
)  # fmt: skip
def test_fix_name_case(typed: str, expected: str):
    from app.services.roster import fix_name_case

    assert fix_name_case(typed) == expected


def test_rename_term_changes_every_class_of_the_year(roster: RosterService):
    a = roster.save_class(SchoolClass(name="7B", term="2026-207")).id
    b = roster.save_class(SchoolClass(name="8C", term="2026-207")).id
    other = roster.save_class(SchoolClass(name="7B", term="2025-2026")).id

    assert roster.rename_term("2026-207", "  2026-2027 ") == 2
    assert {roster.get_class(i).term for i in (a, b)} == {"2026-2027"}
    assert roster.get_class(other).term == "2025-2026"
    assert roster.list_terms() == ["2026-2027", "2025-2026"]
    assert roster.rename_term("2026-2027", "2026-2027") == 0


def test_rename_term_gives_classes_without_a_year_one(roster: RosterService):
    a = roster.save_class(SchoolClass(name="7B")).id
    assert roster.rename_term("", "2026-2027") == 1
    assert roster.get_class(a).term == "2026-2027"


def test_rename_term_refuses_a_clash_and_changes_nothing(roster: RosterService):
    roster.save_class(SchoolClass(name="7B", term="2025-2026"))
    keep = roster.save_class(SchoolClass(name="8C", term="2026"))
    roster.save_class(SchoolClass(name="7b", term="2026"))
    with pytest.raises(RosterError, match="already a class called 7B in 2025-2026"):
        roster.rename_term("2026", "2025-2026")
    assert roster.get_class(keep.id).term == "2026"
    with pytest.raises(RosterError, match="Enter the school year"):
        roster.rename_term("2026", "  ")


def test_copy_subjects_adds_the_missing_ones_with_teachers(roster: RosterService):
    source = roster.save_class(SchoolClass(name="7A"), "Maths").id
    roster.save_subject(Subject(class_id=source, name="Science", teacher="Mr Smith"))
    target = roster.save_class(SchoolClass(name="7B"), "maths").id

    added = roster.copy_subjects(source, target)

    assert [(s.name, s.teacher) for s in added] == [("Science", "Mr Smith")]
    assert [s.name for s in roster.list_subjects(target)] == ["maths", "Science"]
    assert roster.copy_subjects(source, target) == []


def test_class_records_are_counted_and_described(roster: RosterService, conn):
    from app.repositories.class_repo import ClassRepository
    from app.services.roster import describe_records

    class_id = roster.save_class(SchoolClass(name="8A"), first_subject="Science").id
    other = roster.save_class(SchoolClass(name="8B")).id
    subject_id = roster.list_subjects(class_id)[0].id
    ada = _add(roster, class_id, "Ada", "Lovelace")
    for day in ("2026-09-01", "2026-09-02"):
        conn.execute("INSERT INTO attendance (student_id, date, status) VALUES (?, ?, 'present')", (ada.id, day))
    category = conn.execute(
        "INSERT INTO categories (subject_id, name, weight) VALUES (?, 'Tests', 1)", (subject_id,)
    ).lastrowid
    assignment = conn.execute(
        "INSERT INTO assignments (subject_id, category_id, title, max_score) VALUES (?, ?, 'Quiz', 10)",
        (subject_id, category),
    ).lastrowid
    conn.execute("INSERT INTO scores (assignment_id, student_id, score) VALUES (?, ?, 8)", (assignment, ada.id))
    layout = conn.execute(
        "INSERT INTO seat_layouts (class_id, name, rows, cols) VALUES (?, 'Main', 2, 2)", (other,)
    ).lastrowid
    conn.execute("INSERT INTO seats (layout_id, row, col, student_id) VALUES (?, 0, 0, ?)", (layout, ada.id))

    counts = ClassRepository(conn).recorded(class_id)
    assert counts == {"attendance": 2, "scores": 1, "assignments": 1, "categories": 1, "seating": 1}
    assert describe_records(counts) == (
        "2 attendance marks, 1 score, 1 assignment, 1 grade category and 1 seating plan"
    )
    assert describe_records({"attendance": 0}) == ""


def test_number_key_sorts_numbers_as_people_read_them():
    students = [Student(class_id=1, first_name=n, last_name="X", student_no=no)
                for n, no in (("a", "S10"), ("b", None), ("c", "s2"), ("d", "S1"), ("e", ""))]  # fmt: skip
    assert [s.first_name for s in sorted(students, key=number_key)] == ["d", "c", "a", "b", "e"]
