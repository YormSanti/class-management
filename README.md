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

Each start copies the database to `<data folder>/backups/` (the 10 newest are kept).

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
app/ui/              PySide6 main window, views and dialogs
tests/               pytest tests
```

The UI only talks to services, services only talk to repositories, and repositories are the
only code that runs SQL.
