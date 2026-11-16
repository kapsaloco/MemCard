"""Discover RPCS3 paths without running the selected executable."""

from pathlib import Path

import pytest
import yaml

from memcard.discovery import discover_rpcs3
from memcard.paths import BackupError


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.delenv("RPCS3_CONFIG_DIR", raising=False)
    executable = tmp_path / "RPCS3" / "rpcs3.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"not an executable; must never be launched")
    return executable


def user(hdd0: Path, name="00000001") -> Path:
    folder = hdd0 / "home" / name / "savedata"
    folder.mkdir(parents=True)
    (folder / "SAVE.DAT").write_bytes(b"save data")
    return folder


def configure(root, data):
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "vfs.yml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_default_executable_tree(installation):
    savedata = user(installation.parent / "dev_hdd0")
    result = discover_rpcs3(installation)
    assert result.users == (savedata,)
    assert result.config_root == installation.parent
    assert result.hdd0 == installation.parent / "dev_hdd0"


def test_multiple_users_not_assumed_to_be_user_one(installation):
    hdd0 = installation.parent / "dev_hdd0"
    second = user(hdd0, "00000002")
    third = user(hdd0, "00000003")
    user(hdd0, "not-a-user")
    result = discover_rpcs3(installation)
    assert result.users == (second, third)


def test_custom_hdd_from_vfs(installation, tmp_path):
    hdd0 = tmp_path / "Custom HDD with spaces"
    savedata = user(hdd0, "00000005")
    configure(installation.parent, {"/dev_hdd0/": str(hdd0)})
    result = discover_rpcs3(installation)
    assert result.hdd0 == hdd0
    assert result.users == (savedata,)


def test_emulator_directory_placeholder(installation, tmp_path):
    emulator_dir = tmp_path / "Other data"
    savedata = user(emulator_dir / "custom-hdd")
    configure(installation.parent, {"$(EmulatorDir)": str(emulator_dir), "/dev_hdd0/": "$(EmulatorDir)custom-hdd/"})
    assert discover_rpcs3(installation).users == (savedata,)


def test_portable_root_precedes_environment_override(installation, tmp_path, monkeypatch):
    portable = installation.parent / "portable"
    savedata = user(portable / "dev_hdd0")
    monkeypatch.setenv("RPCS3_CONFIG_DIR", str(tmp_path / "unused") + "\\")
    assert discover_rpcs3(installation).users == (savedata,)


def test_environment_config_root(installation, tmp_path, monkeypatch):
    root = tmp_path / "redirected config"
    savedata = user(root / "dev_hdd0")
    monkeypatch.setenv("RPCS3_CONFIG_DIR", str(root) + "\\")
    assert discover_rpcs3(installation).users == (savedata,)


def test_environment_stripping_matches_rpc3_windows_code(installation, tmp_path, monkeypatch):
    savedata = user(tmp_path / "dev_hdd0")
    monkeypatch.setenv("RPCS3_CONFIG_DIR", str(tmp_path / "last-component"))
    assert discover_rpcs3(installation).users == (savedata,)


def test_legacy_root_vfs_and_current_config_precedence(installation, tmp_path):
    old, current = tmp_path / "old hdd", tmp_path / "new hdd"
    old_save, new_save = user(old), user(current)
    (installation.parent / "vfs.yml").write_text(yaml.safe_dump({"/dev_hdd0/": str(old)}), encoding="utf-8")
    assert discover_rpcs3(installation).users == (old_save,)
    configure(installation.parent, {"/dev_hdd0/": str(current)})
    assert discover_rpcs3(installation).users == (new_save,)


@pytest.mark.parametrize("data", [[], {"/dev_hdd0/": 123}, {"/dev_hdd0/": "relative/hdd"},
                                  {"$(EmulatorDir)": "relative"}, {"/dev_hdd0/": "$(Unknown)hdd"}])
def test_ambiguous_settings_never_guess_default(installation, data):
    user(installation.parent / "dev_hdd0")
    configure(installation.parent, data)
    with pytest.raises(BackupError):
        discover_rpcs3(installation)


def test_malformed_yaml_reports_manual_fallback(installation):
    configure(installation.parent, {})
    (installation.parent / "config" / "vfs.yml").write_text("/dev_hdd0/: [broken", encoding="utf-8")
    with pytest.raises(BackupError, match="select savedata manually"):
        discover_rpcs3(installation)


def test_no_savedata_users_returns_empty(installation):
    (installation.parent / "dev_hdd0" / "home" / "00000001").mkdir(parents=True)
    assert discover_rpcs3(installation).users == ()


def test_wrong_executable_rejected(tmp_path):
    path = tmp_path / "other.exe"
    path.write_bytes(b"test")
    with pytest.raises(BackupError, match="rpcs3.exe"):
        discover_rpcs3(path)
