import os
import platform
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main  # noqa: E402
from app import __version__  # noqa: E402


def test_startup_banner_names_the_versions():
    banner = main.startup_banner()
    assert banner.startswith(f"Classroom Manager {__version__} starting")
    assert f"Python {platform.python_version()}" in banner
    assert f"SQLite {sqlite3.sqlite_version}" in banner
    assert "(Qt 6." in banner


def test_app_version_matches_pyproject():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__
