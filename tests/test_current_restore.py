"""Replacement is prepared first; the previous save folder always survives."""

from pathlib import Path

import pytest

from memcard import snapshots
from memcard.manifest import verify_snapshot
from memcard.paths import BackupError
from memcard.snapshots import Cancelled


@pytest.fixture(params=["pcsx2", "rpcs3"])
def recovery(request, tmp_path):
    source, library, target = tmp_path / "backup source", tmp_path / "library", tmp_path / "current saves"
    source.mkdir()
    library.mkdir()
    target.mkdir()
    (source / "new.dat").write_bytes(b"recovered data")
    (source / "nested" / "empty").mkdir(parents=True)
    (target / "old.dat").write_bytes(b"previous data")
    (target / "empty").mkdir()
    backup = getattr(snapshots, f"backup_{request.param}")
    snapshot = backup(source, library, emulator_closed=True)
    restore = getattr(snapshots, f"restore_{request.param}_current")
    return restore, snapshot, library, target


def run(recovery, **kwargs):
    restore, snapshot, library, target = recovery
    return restore(snapshot, library, target, emulator_closed=True, configured_sources=(target,), **kwargs)


def test_current_folder_swap_preserves_previous(recovery):
    result = run(recovery)
    assert (result.target / "new.dat").read_bytes() == b"recovered data"
    assert (result.target / "nested" / "empty").is_dir()
    assert not (result.target / "old.dat").exists()
    assert (result.previous / "old.dat").read_bytes() == b"previous data"
    assert (result.previous / "empty").is_dir()
    verify_snapshot(recovery[1])


def test_closed_emulator_required(recovery):
    restore, snapshot, library, target = recovery
    with pytest.raises(BackupError, match="Close"):
        restore(snapshot, library, target, emulator_closed=False)
    assert (target / "old.dat").read_bytes() == b"previous data"


def test_corrupt_snapshot_never_moves_current_folder(recovery):
    _, snapshot, _, target = recovery
    (snapshot / "payload" / "new.dat").write_bytes(b"corruption")
    with pytest.raises(BackupError):
        run(recovery)
    assert (target / "old.dat").read_bytes() == b"previous data"
    assert not list(target.parent.glob("*.before-MemCard-*"))


def test_cancel_never_moves_current_folder(recovery):
    state = {"cancel": False}
    with pytest.raises(Cancelled):
        run(recovery, progress=lambda *_: state.update(cancel=True), cancelled=lambda: state["cancel"])
    target = recovery[3]
    assert (target / "old.dat").read_bytes() == b"previous data"
    assert not list(target.parent.glob("*.before-MemCard-*"))


def test_publication_failure_rolls_previous_folder_back(recovery, monkeypatch):
    original = Path.rename
    def fail_ready(path, destination):
        if path.name.startswith(".memcard-ready-"):
            raise OSError("Simulated final rename failure")
        return original(path, destination)
    monkeypatch.setattr(Path, "rename", fail_ready)
    with pytest.raises(OSError, match="final rename"):
        run(recovery)
    target = recovery[3]
    assert (target / "old.dat").read_bytes() == b"previous data"
    assert not list(target.parent.glob("*.before-MemCard-*"))
    assert not list(target.parent.glob(".memcard-ready-*"))


def test_competing_target_does_not_destroy_previous_or_new_data(recovery, monkeypatch):
    original = Path.rename
    target = recovery[3]
    def race(path, destination):
        if path.name.startswith(".memcard-ready-"):
            target.mkdir()
            (target / "other process.dat").write_bytes(b"keep")
        return original(path, destination)
    monkeypatch.setattr(Path, "rename", race)
    with pytest.raises(OSError) as error:
        run(recovery)
    assert (target / "other process.dat").read_bytes() == b"keep"
    previous = next(target.parent.glob("*.before-MemCard-*"))
    ready = next(target.parent.glob(".memcard-ready-*"))
    assert (previous / "old.dat").read_bytes() == b"previous data"
    assert (ready / "new.dat").read_bytes() == b"recovered data"
    assert str(previous) in "\n".join(error.value.__notes__)


def test_changes_to_current_saves_abort_before_swap(recovery):
    target = recovery[3]
    def change(*_):
        (target / "new live save.dat").write_bytes(b"live changes")
    with pytest.raises(BackupError, match="changed"):
        run(recovery, progress=change)
    assert (target / "old.dat").read_bytes() == b"previous data"
    assert (target / "new live save.dat").read_bytes() == b"live changes"
    assert not list(target.parent.glob("*.before-MemCard-*"))


def test_failed_write_preserves_current_saves(recovery, monkeypatch):
    original = Path.open
    def fail(path, mode="r", *args, **kwargs):
        if mode == "xb":
            raise OSError("Simulated disk full")
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError):
        run(recovery)
    assert (recovery[3] / "old.dat").read_bytes() == b"previous data"
    assert not list(recovery[3].parent.glob("*.before-MemCard-*"))


def test_library_cannot_be_current_target(recovery):
    restore, snapshot, library, _ = recovery
    with pytest.raises(BackupError, match="overlap"):
        restore(snapshot, library, library, emulator_closed=True)
    verify_snapshot(snapshot)
