# Classroom Manager

An offline desktop app for teachers to manage classes, rosters, attendance, grades and seating.
All data stays in a single SQLite file on your computer.

## Run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

On first launch you choose where to keep the data (default: your user app-data folder,
e.g. `C:\Users\<name>\AppData\Local\ClassroomManager\`). The choice is saved in
`config.json` in the app's settings folder; delete that file to see the setup dialog again.
To keep the data somewhere else later, use **Settings → Move data…**.

Each start copies the database to `<data folder>/backups/`. The 10 newest copies are kept,
plus the last copy of each of the 30 most recent days. Every copy is checked for damage
before it is kept.
To go back to one, select it on the Settings page and press **Restore…**; a copy saved
elsewhere with **File → Back up now…** (e.g. on a USB stick) can be restored with
**Restore from file…**. Either way the current data is first saved as a backup marked
"from just before a restore". **Check for damage** on the Settings page runs SQLite's
integrity check on demand.

Problems are logged to `classroom.log` in the settings folder (next to `config.json`);
**File → Open log file** opens it.

## Keyboard

**Help → Keyboard shortcuts** (F1) lists them all. The main ones: Ctrl+1 … Ctrl+7 switch
pages, F5 reloads the page, Ctrl+Shift+B backs up.

On the Attendance page's Day tab:

- P, L, A and E (or 1 to 4; Space for present) mark the selected student and move to the next.
- Delete clears a mark, N writes a note (↑ ↓ go to the next note), U goes to the next student not marked yet.
- D marks the student for several days at once, e.g. a sick note; H shows their history.
- Ctrl+Enter marks the rest present, Ctrl+Shift+C copies the day's absences for the school office.
- Ctrl+F finds a student, Alt+← / Alt+→ change the day, Alt+Home goes to today.
- Ctrl+Z undoes and Ctrl+Y redoes.

On the Month tab the same letters mark the selected cell, and Alt+← / Alt+→ (or Page Up /
Page Down) change the month. Right-clicking a student on the Day tab lists what can be done.

On the Gradebook page, type a score in a cell and press Enter to go to the next student
(Shift+Enter goes back). Delete clears the selected scores, Ctrl+C / Ctrl+V copy scores to
and from a spreadsheet (one value pasted over several selected cells goes in each), Ctrl+Z
undoes, Ctrl+F finds a student and Ctrl+N adds an assignment. Double-click a column header
to edit the assignment; right-click it to fill its empty cells or delete it.

On the Rankings page, Alt+R chooses what to rank by: all subjects or one of them, and
Ctrl+C copies the ranking for a spreadsheet.

On the Seating page, click a student, then a seat (or select them and press Enter or
Space). Esc puts the student down again, Delete takes a student out of their seat, Ctrl+F
finds a student's seat, and Ctrl+Z / Ctrl+Y undo and redo any change to the plan.

On the Manage classes page:

- In the class list, Ctrl+N adds a student, Enter or F2 edits one and Delete deletes a
  student added by mistake (one with anything recorded is deactivated instead).
- Ctrl+V adds the students copied from a spreadsheet, a CSV file or a typed list, after a
  preview; Ctrl+C copies the students shown. In the Add student dialog, Ctrl+Enter saves
  and starts on the next student.
- F2 edits the selected class or subject and Delete deletes it, while nothing is recorded
  in it. Right-clicking a student, class or subject lists what can be done.

## Classes and students

A pasted list can have one student per line (`Ada Lovelace`, `Lovelace, Ada` or
`LOVELACE Ada`, optionally after a number or a bullet) or columns separated by tabs,
semicolons or commas: first and last name; number, first and last name; or number, first
and last name and notes. The preview points out lines it can't read, names listed twice and
numbers already used before anything is added.

**Copy…** under Classes sets up another class of the same school year with the same
subjects, and **Export year…** saves the students of every class of a school year in one
CSV file, e.g. for the school office. The class list's search ignores accents, so "Jose"
finds "José".

## Grades

Every subject of a class has its own gradebook. Assignments belong to a category with a
weight, e.g. Tests 50 and Homework 20; weights are compared with each other, so they
needn't add up to 100. A new subject is offered Tests, Quizzes, Homework and Participation
to start with, or **Categories…** sets up your own.

A score can be typed as points (`8`, `8,5`), a percentage of the maximum (`85%`), points
out of another total (`17/20`, for a paper marked out of 20) or `ex` for an exempt student. A student's average is each category's points scored over points
possible, counted by its weight; categories with nothing scored yet, exempt students and
empty cells are left out, while a 0 counts. Points above the maximum are bonus points.
Averages under the pass mark (60% unless changed under **Settings → Grades**) are shown
in red, here and on the dashboard. Clicking **Average** lists the best average first, and
**Export…** saves the scores, category percents, averages and letter grades as CSV.
An empty cell of a dated assignment counts as missing work on the dashboard once the date
has passed; an exempt one doesn't.

New school year, **Copy…** and Copy subjects bring each subject's categories along.

## Rankings

The Rankings page lists the students of the current class best average first, in one
subject or, under **Rank by**, in all subjects: then each student's average is the mean
of their subject averages, leaving out subjects they have nothing scored in yet, as on
the dashboard. Students with nothing scored are listed last, without a place.

Averages are shown to one decimal, and students whose averages look the same share a
place, marked `2=`. Whether the next place is then 4th or 3rd is set under
**Settings → Rankings**. Averages under the pass mark are shown in red, and **Export…**
saves the ranking as CSV.

## Seating

A class can keep several seating plans, e.g. one for tests and one for group work. Each
plan is a room of up to 12 rows of up to 12 seats, shown as the teacher sees it from the
front: row 1, the front row, is at the bottom.

Click a student under **Not seated**, then a seat. Click a seated student, then another
seat to move them; if that seat is taken, the two swap. **Seat the rest** puts everyone
not seated yet in the free seats by name, front row first, and **Shuffle** seats the
whole class at random; Ctrl+Z undoes either. **Edit…** renames the plan or changes the
room, asking first if a smaller room would leave someone without a seat, **Copy…** starts
a new plan from the one shown with everyone in the same seat, and **Save PDF…** saves the
plan to print, e.g. for a substitute teacher. The plan last shown in each class is shown
again next time.

Rooms aren't always full rows: right-click a free seat and choose **No desk here** for an
aisle or a gap. Nobody is seated there, not even by Seat the rest or Shuffle, and the
printed plan leaves it blank.

A student who is deactivated leaves their seat free. Deleting a class deletes its seating
plans while nobody is seated in them; clear a plan first to delete a class set up by mistake.

## Test

```bash
pytest
```

## Layout

```
main.py              startup: config → backup → database → main window
app/config.py        config.json and data-folder resolution
app/db/              connection (WAL, foreign keys, transactions) and schema.sql
app/models.py        dataclasses for every table
app/repositories/    all SQL, one repository per table group
app/services/        business logic, no Qt imports (roster, backup, ...)
app/ui/              PySide6 main window, views and dialogs; style.py, theme.py
                     and files.py (save dialogs) are shared by every page
tests/               pytest tests
```

The UI only talks to services, services only talk to repositories, and repositories are the
only code that runs SQL.
