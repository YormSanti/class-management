import os
import platform
import sqlite3

import pytest

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


def test_a_data_folder_that_cant_be_written_to_is_asked_for_again(tmp_path, monkeypatch):
    from pathlib import Path

    from app.config import AppConfig

    locked, usable = tmp_path / "usb", tmp_path / "other"
    locked.mkdir()
    asked, saved = [], []

    def prepare(folder: Path) -> None:
        if folder == locked:
            raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(main, "load_config", lambda: AppConfig(data_dir=locked))
    monkeypatch.setattr(main, "prepare_data_dir", prepare)
    monkeypatch.setattr(main, "_choose_data_dir", lambda message, current: asked.append((message, current)) or usable)
    monkeypatch.setattr(main, "save_config", saved.append)

    config = main._resolve_config()
    assert config.data_dir == usable and saved == [config]
    message, current = asked[0]
    assert current == locked and "can't save changes" in message and "Permission denied" in message


def test_a_writable_data_folder_is_used_without_asking(tmp_path, monkeypatch):
    from app.config import AppConfig

    monkeypatch.setattr(main, "load_config", lambda: AppConfig(data_dir=tmp_path))
    monkeypatch.setattr(main, "_choose_data_dir", lambda **kw: pytest.fail("shouldn't ask"))
    assert main._resolve_config().data_dir == tmp_path
