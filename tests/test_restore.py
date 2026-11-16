import json
from pathlib import Path
import subprocess
import sys

import pytest

from memcard.manifest import verify_snapshot
from memcard.paths import BackupError, inventory
from memcard.snapshots import Cancelled, backup_pcsx2, restore_pcsx2


@pytest.fixture
def saved(tmp_path):
    source, library = tmp_path / "memcards", tmp_path / "library"
    source.mkdir()
    library.mkdir()
    (source / "card.ps2").write_bytes(bytes(range(256)) * 32)
    (source / "Folder card" / "empty").mkdir(parents=True)
    (source / "Folder card" / "日本語").write_bytes(b"folder data")
    (source / ".hidden").write_bytes(b"hidden data")
    snapshot = backup_pcsx2(source, library, emulator_closed=True)
    return source, library, snapshot, tmp_path / "Restored cards"


def restore(saved, **kwargs):
    _, library, snapshot, target = saved
    return restore_pcsx2(snapshot, library, target, **kwargs)


def test_round_trip_and_snapshot_unchanged(saved):
    source, _, snapshot, target = saved
    manifest_before = (snapshot / "manifest.json").read_bytes()
    result = restore(saved)
    assert result == target
    assert inventory(target)[0] == inventory(source)[0]
    assert inventory(target)[1].keys() == inventory(source)[1].keys()
    for path in source.rglob("*"):
        if path.is_file():
            assert (target / path.relative_to(source)).read_bytes() == path.read_bytes()
    assert not (target / "manifest.json").exists()
    assert (snapshot / "manifest.json").read_bytes() == manifest_before
    verify_snapshot(snapshot)


@pytest.mark.parametrize("kind", ["file", "empty_folder", "populated_folder"])
def test_existing_target_is_preserved(saved, kind):
    target = saved[3]
    if kind == "file":
        target.write_bytes(b"keep")
    else:
        target.mkdir()
        if kind == "populated_folder":
            (target / "keep").write_bytes(b"keep")
    with pytest.raises(BackupError, match="already exists"):
        restore(saved)
    if kind == "file":
        assert target.read_bytes() == b"keep"
    elif kind == "populated_folder":
        assert (target / "keep").read_bytes() == b"keep"
    assert not list(target.parent.glob(".memcard-restore-*"))


@pytest.mark.parametrize("kind", ["corrupt", "missing", "extra", "invalid_manifest"])
def test_bad_snapshot_publishes_nothing(saved, kind):
    snapshot, target = saved[2:]
    if kind == "corrupt":
        path = snapshot / "payload" / "card.ps2"
        path.write_bytes(b"x" * path.stat().st_size)
    elif kind == "missing":
        (snapshot / "payload" / "card.ps2").unlink()
    elif kind == "extra":
        (snapshot / "payload" / "extra").mkdir()
    else:
        path = snapshot / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["files"][0]["path"] = "../escape"
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BackupError):
        restore(saved)
    assert not target.exists()
    assert not list(target.parent.glob(".memcard-restore-*"))


def test_cancel_after_copy_publishes_nothing(saved):
    state = {"cancel": False}
    with pytest.raises(Cancelled):
        restore(saved, progress=lambda *_: state.update(cancel=True), cancelled=lambda: state["cancel"])
    assert not saved[3].exists()
    assert not list(saved[3].parent.glob(".memcard-restore-*"))
    verify_snapshot(saved[2])


def test_write_failure_cleans_up(saved, monkeypatch):
    original = Path.open
    def fail(path, mode="r", *args, **kwargs):
        if mode == "xb":
            raise OSError("Simulated full disk")
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError, match="full disk"):
        restore(saved)
    assert not saved[3].exists()
    assert not list(saved[3].parent.glob(".memcard-restore-*"))
    verify_snapshot(saved[2])


def test_target_appearing_during_copy_is_preserved(saved):
    target = saved[3]
    def create_target(done, total, name):
        if done == total:
            target.mkdir()
            (target / "keep").write_bytes(b"keep")
    with pytest.raises(BackupError, match="already exists"):
        restore(saved, progress=create_target)
    assert (target / "keep").read_bytes() == b"keep"
    assert not list(target.parent.glob(".memcard-restore-*"))


def test_copy_corruption_detected(saved):
    def corrupt(done, total, name):
        if done == total:
            staging = next(saved[3].parent.glob(".memcard-restore-*"))
            (staging / "card.ps2").write_bytes(b"bad")
    with pytest.raises(BackupError, match="verification"):
        restore(saved, progress=corrupt)
    assert not saved[3].exists()


def test_windows_publish_does_not_replace_racing_empty_target(saved, monkeypatch):
    original = Path.rename
    target = saved[3]
    def race(path, destination):
        if path.name.startswith(".memcard-restore-"):
            target.mkdir()
        return original(path, destination)
    monkeypatch.setattr(Path, "rename", race)
    with pytest.raises(OSError):
        restore(saved)
    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert not list(target.parent.glob(".memcard-restore-*"))


def test_inside_library_rejected(saved):
    with pytest.raises(BackupError, match="overlap"):
        restore_pcsx2(saved[2], saved[1], saved[1] / "restored")


def test_inside_configured_source_rejected(saved):
    with pytest.raises(BackupError, match="overlap"):
        restore_pcsx2(saved[2], saved[1], saved[0] / "restored", configured_sources=(saved[0],))


def test_missing_parent_rejected(saved):
    with pytest.raises(OSError):
        restore_pcsx2(saved[2], saved[1], saved[3] / "missing")
    assert not saved[3].exists()


def test_moved_library_and_missing_original_source(saved):
    source, library, snapshot, target = saved
    source.rename(source.with_name("old source"))
    moved = library.with_name("moved library")
    library.rename(moved)
    assert restore_pcsx2(moved / "snapshots" / snapshot.name, moved, target) == target


def test_junction_parent_rejected(saved):
    junction = saved[3]
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(saved[0])], capture_output=True)
    assert result.returncode == 0
    try:
        with pytest.raises(BackupError, match="reparse"):
            restore_pcsx2(saved[2], saved[1], junction / "restored")
        assert not (saved[0] / "restored").exists()
    finally:
        junction.rmdir()


def test_low_space_rejected(saved, monkeypatch):
    from memcard import snapshots
    monkeypatch.setattr(snapshots.shutil, "disk_usage", lambda _: type("Usage", (), {"free": 0})())
    with pytest.raises(BackupError, match="free space"):
        restore(saved)
    assert not saved[3].exists()


def test_staging_snapshot_rejected(saved):
    snapshot = saved[2]
    staging = snapshot.with_name(".staging-interrupted")
    snapshot.rename(staging)
    with pytest.raises(BackupError, match="finalized"):
        restore_pcsx2(staging, saved[1], saved[3])


@pytest.mark.parametrize("answer", ["y", "n"])
def test_cli_restore(saved, answer):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "tests" / "cli_runner.py"), "restore-pcsx2", str(saved[2]),
                             "--library", str(saved[1]), "--target", str(saved[3])],
                            input=answer + "\n", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert saved[3].exists() == (answer == "y")
