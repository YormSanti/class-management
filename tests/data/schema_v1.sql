-- Dates are stored as ISO 8601 text (YYYY-MM-DD).
-- Students are never deleted (active = 0 instead), so tables referencing them
-- use the default RESTRICT behaviour to protect history.

CREATE TABLE IF NOT EXISTS classes (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL CHECK (trim(name) <> ''),
    subject TEXT NOT NULL DEFAULT '',
    term    TEXT NOT NULL DEFAULT ''
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

CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id),
    date       TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late', 'excused')),
    note       TEXT NOT NULL DEFAULT '',
    UNIQUE (student_id, date)
);
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);

CREATE TABLE IF NOT EXISTS categories (
    id       INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id),
    name     TEXT NOT NULL CHECK (trim(name) <> ''),
    weight   REAL NOT NULL CHECK (weight >= 0),
    UNIQUE (class_id, name)
);

CREATE TABLE IF NOT EXISTS assignments (
    id          INTEGER PRIMARY KEY,
    class_id    INTEGER NOT NULL REFERENCES classes(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    title       TEXT NOT NULL CHECK (trim(title) <> ''),
    date        TEXT,
    max_score   REAL NOT NULL CHECK (max_score > 0)
);
CREATE INDEX IF NOT EXISTS idx_assignments_class ON assignments(class_id);

-- score NULL = not submitted / exempt (ignored in grading), which differs from 0.
CREATE TABLE IF NOT EXISTS scores (
    id            INTEGER PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES students(id),
    score         REAL CHECK (score IS NULL OR score >= 0),
    UNIQUE (assignment_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_scores_student ON scores(student_id);

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
