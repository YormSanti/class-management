import json
from pathlib import Path

from app.config import AppConfig, load_config, prepare_data_dir, save_config


def test_missing_config_means_first_launch(tmp_path: Path):
    assert load_config(tmp_path / "config.json") is None


def test_save_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "settings" / "config.json"
    config = AppConfig(data_dir=tmp_path / "data", ranking_method="dense")
    save_config(config, path)

    assert load_config(path) == config
    assert not list(path.parent.glob("*.tmp"))  # temp file was renamed away


def test_corrupt_config_is_treated_as_missing(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_config(path) is None


def test_unknown_ranking_method_falls_back_to_competition(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"data_dir": str(tmp_path), "ranking_method": "bogus"}))
    assert load_config(path).ranking_method == "competition"


def test_db_and_backup_paths_live_in_data_dir(tmp_path: Path):
    config = AppConfig(data_dir=tmp_path)
    assert config.db_path == tmp_path / "classroom.db"
    assert config.backup_dir == tmp_path / "backups"


def test_prepare_data_dir_creates_folder(tmp_path: Path):
    target = tmp_path / "nested" / "ClassroomData"
    prepare_data_dir(target)
    assert target.is_dir()
    assert list(target.iterdir()) == []  # write probe cleaned up
