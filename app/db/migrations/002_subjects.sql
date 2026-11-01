-- Version 2: a class becomes a group of students, and grades move to subjects.
-- Every existing class gets one subject (its old "subject" text, or "General"),
-- which takes over the class's categories and assignments. Row ids are kept.
-- Runs inside one transaction with foreign keys off (see connection._migrate).

CREATE TABLE subjects (
    id       INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id),
    name     TEXT NOT NULL CHECK (trim(name) <> ''),
    teacher  TEXT NOT NULL DEFAULT '',
    UNIQUE (class_id, name)
);
INSERT INTO subjects (class_id, name)
    SELECT id, CASE WHEN trim(subject) <> '' THEN trim(subject) ELSE 'General' END FROM classes;
ALTER TABLE classes DROP COLUMN subject;

CREATE TABLE new_categories (
    id         INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    name       TEXT NOT NULL CHECK (trim(name) <> ''),
    weight     REAL NOT NULL CHECK (weight >= 0),
    UNIQUE (subject_id, name)
);
INSERT INTO new_categories (id, subject_id, name, weight)
    SELECT c.id, s.id, c.name, c.weight FROM categories c JOIN subjects s ON s.class_id = c.class_id;
DROP TABLE categories;
ALTER TABLE new_categories RENAME TO categories;

CREATE TABLE new_assignments (
    id          INTEGER PRIMARY KEY,
    subject_id  INTEGER NOT NULL REFERENCES subjects(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    title       TEXT NOT NULL CHECK (trim(title) <> ''),
    date        TEXT,
    max_score   REAL NOT NULL CHECK (max_score > 0)
);
INSERT INTO new_assignments (id, subject_id, category_id, title, date, max_score)
    SELECT a.id, s.id, a.category_id, a.title, a.date, a.max_score
    FROM assignments a JOIN subjects s ON s.class_id = a.class_id;
DROP TABLE assignments;
ALTER TABLE new_assignments RENAME TO assignments;
CREATE INDEX idx_assignments_subject ON assignments(subject_id);

CREATE TABLE new_attendance (
    id         INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id),
    subject_id INTEGER REFERENCES subjects(id),
    date       TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late', 'excused')),
    note       TEXT NOT NULL DEFAULT ''
);
INSERT INTO new_attendance (id, student_id, date, status, note)
    SELECT id, student_id, date, status, note FROM attendance;
DROP TABLE attendance;
ALTER TABLE new_attendance RENAME TO attendance;
CREATE UNIQUE INDEX idx_attendance_unique ON attendance(student_id, date, coalesce(subject_id, 0));
CREATE INDEX idx_attendance_date ON attendance(date);
