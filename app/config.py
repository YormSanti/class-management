"""App configuration: where the database lives and user preferences.

config.json is kept in the per-user settings folder (never in the data folder),
so the app can always find it even when the data folder is on another drive.
"""

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import platformdirs

APP_NAME = "ClassroomManager"
CONFIG_FILENAME = "config.json"
DB_FILENAME = "classroom.db"
BACKUP_DIRNAME = "backups"
LOG_FILENAME = "classroom.log"  # in the settings folder, next to config.json

RANKING_METHODS = ("competition", "dense")
THEMES = ("system", "light", "dark")

log = logging.getLogger(__name__)


@dataclass
class AppConfig:
    data_dir: Path
    ranking_method: str = "competition"
    theme: str = "system"
    pass_mark: float = 60.0  # percent: an average under this is failing

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / BACKUP_DIRNAME


def settings_dir() -> Path:
    """Per-user folder holding config.json (e.g. %LOCALAPPDATA%\\ClassroomManager)."""
    return platformdirs.user_config_path(APP_NAME, appauthor=False)


def default_data_dir() -> Path:
    """Default folder for the database (e.g. %LOCALAPPDATA%\\ClassroomManager)."""
    return platformdirs.user_data_path(APP_NAME, appauthor=False)


def default_config_path() -> Path:
    return settings_dir() / CONFIG_FILENAME


def load_config(path: Path | None = None) -> AppConfig | None:
    """Return the saved config, or None if there is none yet (first launch).

    An unreadable or malformed file is also treated as "not configured" so the
    teacher gets the setup dialog instead of a crash.
    """
    path = path or default_config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        data_dir = Path(raw["data_dir"])
        # "" or a relative path would put the data wherever the app happens to be started.
        if not data_dir.is_absolute():
            raise ValueError(f"the data folder {raw['data_dir']!r} isn't a full path")
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Ignoring unreadable config %s: %s", path, exc)
        return None

    ranking_method = raw.get("ranking_method", "competition")
    if ranking_method not in RANKING_METHODS:
        ranking_method = "competition"
    theme = raw.get("theme", "system")
    if theme not in THEMES:
        theme = "system"
    pass_mark = raw.get("pass_mark", 60.0)
    if not isinstance(pass_mark, (int, float)) or isinstance(pass_mark, bool) or not 0 <= pass_mark <= 100:
        pass_mark = 60.0
    return AppConfig(data_dir=data_dir, ranking_method=ranking_method, theme=theme, pass_mark=float(pass_mark))


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """Write config.json atomically (temp file + rename) so a crash can't corrupt it."""
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    data["data_dir"] = str(config.data_dir)

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def prepare_data_dir(data_dir: Path) -> None:
    """Create the data folder if needed and confirm it is writable.

    Raises OSError with a readable message if the folder can't be used.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    probe = data_dir / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        probe.unlink(missing_ok=True)
