import copy
import os
from pathlib import Path
import subprocess
import sys

import pytest

from memcard.manifest import validate, verify_snapshot
from memcard.paths import BackupError, relative_name
from memcard.snapshots import Cancelled, backup_pcsx2


@pytest.fixture
def folders(tmp_path):
    source = tmp_path / "memcards"
    library = tmp_path / "library"
    source.mkdir()
    library.mkdir()
    (source / "Mcd001.ps2").write_bytes(bytes(range(256)) * 64)
    (source / "Folder card" / "empty").mkdir(parents=True)
    (source / "Folder card" / "日本語 save").write_bytes(b"folder-card-data")
    (source / ".hidden").write_bytes(b"hidden")
    return source, library


def backup(folders, **kwargs):
    return backup_pcsx2(*folders, emulator_closed=True, **kwargs)


def test_pcsx2_cards_and_complete_tree(folders):
    source, library = folders
    snapshot = backup(folders)
    data = verify_snapshot(snapshot)
    assert data["preset"]["kind"] == "pcsx2_memory_cards"
    assert data["source_path"] == str(source)
    assert (snapshot / "payload" / "Folder card" / "empty").is_dir()
    for path in source.rglob("*"):
        if path.is_file():
            assert (snapshot / "payload" / path.relative_to(source)).read_bytes() == path.read_bytes()
    assert not list((library / "snapshots").glob(".staging-*"))
    assert backup(folders) != snapshot


@pytest.mark.parametrize("change", ["same_size", "missing", "extra_file", "extra_directory", "missing_directory"])
def test_corruption_is_rejected(folders, change):
    snapshot = backup(folders)
    payload = snapshot / "payload"
    if change == "same_size":
        path = payload / "Mcd001.ps2"
        content = path.read_bytes()
        path.write_bytes(b"x" + content[1:])
    elif change == "missing":
        (payload / "Mcd001.ps2").unlink()
    elif change == "extra_file":
        (payload / "unexpected").write_bytes(b"x")
    elif change == "extra_directory":
        (payload / "unexpected").mkdir()
    else:
        (payload / "Folder card" / "empty").rmdir()
    with pytest.raises(BackupError):
        verify_snapshot(snapshot)


def test_source_change_aborts_and_preserves_previous(folders):
    source, library = folders
    previous = backup(folders)

    def mutate(done, total, name):
        if done == total:
            (source / "new save").write_bytes(b"changed")

    with pytest.raises(BackupError, match="Source changed"):
        backup(folders, progress=mutate)
    verify_snapshot(previous)
    assert list((library / "snapshots").iterdir()) == [previous]


def test_cancel_before_publication(folders):
    state = {"cancel": False}
    with pytest.raises(Cancelled):
        backup(folders, progress=lambda *_: state.update(cancel=True),
               cancelled=lambda: state["cancel"])
    assert not list((folders[1] / "snapshots").iterdir())


def test_write_failure_cleans_staging_and_preserves_previous(folders, monkeypatch):
    previous = backup(folders)
    original = Path.open

    def fail_write(path, mode="r", *args, **kwargs):
        if mode == "xb":
            raise OSError("Simulated disk full")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_write)
    with pytest.raises(OSError, match="disk full"):
        backup(folders)
    verify_snapshot(previous)
    assert list((folders[1] / "snapshots").iterdir()) == [previous]


def test_read_failure_cleans_staging(folders, monkeypatch):
    source, library = folders
    original = Path.open

    def fail_read(path, mode="r", *args, **kwargs):
        if mode == "rb" and source in path.parents:
            raise PermissionError("Simulated unreadable save")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_read)
    with pytest.raises(PermissionError):
        backup(folders)
    assert not list((library / "snapshots").iterdir())


def test_space_check(folders, monkeypatch):
    from memcard import snapshots
    monkeypatch.setattr(snapshots.shutil, "disk_usage", lambda _: type("Usage", (), {"free": 0})())
    with pytest.raises(BackupError, match="free space"):
        backup(folders)


def test_requires_closed_emulator(folders):
    with pytest.raises(BackupError, match="Close PCSX2"):
        backup_pcsx2(*folders, emulator_closed=False)


@pytest.mark.parametrize("direction", ["same", "library_inside", "source_inside"])
def test_overlap_rejected(folders, direction):
    source, library = folders
    if direction == "same":
        library = source
    elif direction == "library_inside":
        library = source / "backups"
        library.mkdir()
    else:
        library = source.parent
    with pytest.raises(BackupError, match="overlap"):
        backup((source, library))


def test_empty_source_rejected(folders):
    source, library = folders
    empty = source.parent / "empty"
    empty.mkdir()
    with pytest.raises(BackupError, match="no files"):
        backup((empty, library))


@pytest.mark.parametrize("name", ["../escape", "a/../b", "/absolute", "C:/drive", "a\\b",
                                  "CON", "nul.txt", "COM1.sav", "bad:stream", "trailing.",
                                  "trailing ", "a//b", "bad?name", "a/./b", "LPT¹"])
def test_invalid_windows_paths(name):
    with pytest.raises(BackupError):
        relative_name(name)


@pytest.mark.parametrize("mutation", ["version", "bool_size", "hash", "duplicate", "collision", "parent", "conflict", "uuid"])
def test_manifest_validation(folders, mutation):
    data = copy.deepcopy(verify_snapshot(backup(folders)))
    if mutation == "version":
        data["schema_version"] = True
    elif mutation == "bool_size":
        data["files"][0]["size_bytes"] = True
    elif mutation == "hash":
        data["files"][0]["sha256"] = "invalid"
    elif mutation == "duplicate":
        data["files"].append(data["files"][0])
    elif mutation == "collision":
        entry = dict(data["files"][0])
        entry["path"] = entry["path"].upper()
        data["files"].append(entry)
    elif mutation == "parent":
        data["directories"] = []
    elif mutation == "conflict":
        data["directories"].append(data["files"][0]["path"])
    else:
        data["preset"]["id"] = "invalid"
    with pytest.raises(BackupError):
        validate(data)


def test_duplicate_json_key(folders):
    snapshot = backup(folders)
    manifest = snapshot / "manifest.json"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'), encoding="utf-8")
    with pytest.raises(BackupError, match="Duplicate JSON"):
        verify_snapshot(snapshot)


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions")
def test_junction_source_and_payload_rejected(folders):
    source, library = folders
    snapshot = backup(folders)
    junction = source / "linked"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(library)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    try:
        with pytest.raises(BackupError, match="reparse"):
            backup(folders)
        with pytest.raises(BackupError, match="reparse"):
            backup((junction, source))
    finally:
        junction.rmdir()
    junction = snapshot / "payload" / "linked"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(source)], capture_output=True)
    assert result.returncode == 0
    try:
        with pytest.raises(BackupError, match="reparse"):
            verify_snapshot(snapshot)
    finally:
        junction.rmdir()


def test_cli_backup_automatically_verifies(folders):
    source, library = folders
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "tests" / "cli_runner.py"), "backup-pcsx2", "--source", str(source),
                             "--library", str(library), "--emulator-closed", "--yes"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    snapshot = next((library / "snapshots").iterdir())
    assert len(verify_snapshot(snapshot)["files"]) == 3
    assert "Verified snapshot created" in result.stdout


def test_cli_manual_verification_not_available():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "tests" / "cli_runner.py"), "verify", "unused"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_cli_declining_creates_nothing(folders):
    source, library = folders
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "tests" / "cli_runner.py"), "backup-pcsx2", "--source", str(source),
                             "--library", str(library), "--emulator-closed"], input="n\n", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not list(library.iterdir())


@pytest.mark.skipif(os.name != "nt", reason="Windows mutex")
def test_second_instance_is_blocked():
    from uuid import uuid4
    from memcard.instance import single_instance
    name = f"Local\\MemCard.Test.{uuid4()}"
    with single_instance(name):
        with pytest.raises(BackupError, match="already running"):
            with single_instance(name):
                pytest.fail("Second instance entered")
