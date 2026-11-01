-- Dates are stored as ISO 8601 text (YYYY-MM-DD).
-- Students are never deleted (active = 0 instead), so tables referencing them
-- use the default RESTRICT behaviour to protect history.
--
-- A class is a group of students (e.g. 7B). Each class has subjects
-- (e.g. Mathematics, Science), and every subject has its own gradebook.

CREATE TABLE IF NOT EXISTS classes (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (trim(name) <> ''),
    term TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS subjects (
    id       INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id),
    name     TEXT NOT NULL CHECK (trim(name) <> ''),
    teacher  TEXT NOT NULL DEFAULT '',
    UNIQUE (class_id, name)
);

CREATE TABLE IF NOT EXISTS students (
    id         INTEGER PRIMARY KEY,
    class_id   INTEGER NOT NULL REFERENCES classes(id),
    student_no TEXT,
    first_name TEXT NOT NULL CHECK (trim(first_name) <> ''),
    last_name  TEXT NOT NULL CHECK (trim(last_name) <> ''),
    active     INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes      TEXT NOT NULL DEFAULT '',
    UNIQUE (class_id, student_no)
);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);

-- subject_id NULL = daily (homeroom) attendance; otherwise attendance for one subject's lesson.
CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id),
    subject_id INTEGER REFERENCES subjects(id),
    date       TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late', 'excused')),
    note       TEXT NOT NULL DEFAULT ''
);
-- One record per student, day and subject; coalesce() because NULLs never clash in UNIQUE.
CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_unique
    ON attendance(student_id, date, coalesce(subject_id, 0));
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);

CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    name       TEXT NOT NULL CHECK (trim(name) <> ''),
    weight     REAL NOT NULL CHECK (weight >= 0),
    UNIQUE (subject_id, name)
);

CREATE TABLE IF NOT EXISTS assignments (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL REFERENCES subjects(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    title       TEXT NOT NULL CHECK (trim(title) <> ''),
    date        TEXT,
    max_score   REAL NOT NULL CHECK (max_score > 0)
);
CREATE INDEX IF NOT EXISTS idx_assignments_subject ON assignments(subject_id);

-- score NULL = not submitted / exempt (ignored in grading), which differs from 0.
CREATE TABLE IF NOT EXISTS scores (
    id            INTEGER PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES students(id),
    score         REAL CHECK (score IS NULL OR score >= 0),
    UNIQUE (assignment_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_scores_student ON scores(student_id);

-- Seating belongs to the class; a class can keep several named layouts.
CREATE TABLE IF NOT EXISTS seat_layouts (
    id       INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id),
    name     TEXT NOT NULL CHECK (trim(name) <> ''),
    rows     INTEGER NOT NULL CHECK (rows > 0),
    cols     INTEGER NOT NULL CHECK (cols > 0),
    UNIQUE (class_id, name)
);

CREATE TABLE IF NOT EXISTS seats (
    layout_id  INTEGER NOT NULL REFERENCES seat_layouts(id) ON DELETE CASCADE,
    row        INTEGER NOT NULL,
    col        INTEGER NOT NULL,
    student_id INTEGER REFERENCES students(id),
    PRIMARY KEY (layout_id, row, col),
    UNIQUE (layout_id, student_id)
);
