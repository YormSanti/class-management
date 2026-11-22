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
