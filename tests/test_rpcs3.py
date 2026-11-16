"""RPCS3 users remain independent; save companions are opaque bytes."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from memcard.manifest import verify_snapshot
from memcard.paths import BackupError
from memcard.snapshots import (
    Cancelled, backup_pcsx2, backup_rpcs3, restore_pcsx2, restore_rpcs3,
)


@pytest.fixture
def ps3(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    sources = []
    for user in ("00000001", "00000002"):
        savedata = tmp_path / "RPCS3" / "dev_hdd0" / "home" / user / "savedata"
        game = savedata / "BLUS12345-SAVE"
        (game / "empty").mkdir(parents=True)
        for name, data in {"PARAM.SFO": b"SFO" + user.encode(), "PARAM.PFD": bytes(range(256)),
                           "ICON0.PNG": b"image", "SAVE.DAT": b"save" + user.encode(),
                           ".hidden": b"hidden"}.items():
            (game / name).write_bytes(data)
        sources.append(savedata)
    return sources, library


def assert_same_tree(source, target):
    assert {p.relative_to(source) for p in source.rglob("*")} == {p.relative_to(target) for p in target.rglob("*")}
    for path in source.rglob("*"):
        if path.is_file():
            assert (target / path.relative_to(source)).read_bytes() == path.read_bytes()


def test_two_users_round_trip_independently(ps3, tmp_path):
    sources, library = ps3
    for index, source in enumerate(sources, 1):
        snapshot = backup_rpcs3(source, library, emulator_closed=True)
        data = verify_snapshot(snapshot)
        assert data["preset"]["kind"] == "rpcs3_savedata"
        assert data["preset"]["label"] == f"RPCS3 user {index:08}"
        target = tmp_path / f"Restored-{index}"
        restore_rpcs3(snapshot, library, target, configured_sources=tuple(sources))
        assert_same_tree(source, target)
        verify_snapshot(snapshot)
    assert len(list((library / "snapshots").iterdir())) == 2


def test_cross_emulator_restore_rejected(ps3, tmp_path):
    sources, library = ps3
    ps3_snapshot = backup_rpcs3(sources[0], library, emulator_closed=True)
    with pytest.raises(BackupError, match="PCSX2"):
        restore_pcsx2(ps3_snapshot, library, tmp_path / "wrong-ps2")
    ps2 = tmp_path / "memcards"
    ps2.mkdir()
    (ps2 / "card.ps2").write_bytes(b"card")
    ps2_snapshot = backup_pcsx2(ps2, library, emulator_closed=True)
    with pytest.raises(BackupError, match="RPCS3"):
        restore_rpcs3(ps2_snapshot, library, tmp_path / "wrong-ps3")
    assert not (tmp_path / "wrong-ps2").exists()
    assert not (tmp_path / "wrong-ps3").exists()


@pytest.mark.parametrize("change", ["same_size", "missing_companion", "extra_file", "bad_manifest"])
def test_rpc3_corruption_never_publishes(ps3, tmp_path, change):
    sources, library = ps3
    snapshot = backup_rpcs3(sources[0], library, emulator_closed=True)
    game = snapshot / "payload" / "BLUS12345-SAVE"
    if change == "same_size":
        (game / "PARAM.PFD").write_bytes(b"x" * 256)
    elif change == "missing_companion":
        (game / "PARAM.SFO").unlink()
    elif change == "extra_file":
        (game / "extra").write_bytes(b"extra")
    else:
        manifest = snapshot / "manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["files"][0]["path"] = "../escape"
        manifest.write_text(json.dumps(data), encoding="utf-8")
    target = tmp_path / "restored"
    with pytest.raises(BackupError):
        restore_rpcs3(snapshot, library, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".memcard-restore-*"))


def test_rpc3_confirmation_and_cancelled_backup(ps3):
    sources, library = ps3
    with pytest.raises(BackupError, match="Close RPCS3"):
        backup_rpcs3(sources[0], library, emulator_closed=False)
    state = {"cancel": False}
    with pytest.raises(Cancelled):
        backup_rpcs3(sources[0], library, emulator_closed=True,
                     progress=lambda *_: state.update(cancel=True), cancelled=lambda: state["cancel"])
    assert not list((library / "snapshots").iterdir())


def test_rpc3_restore_existing_or_live_source_rejected(ps3, tmp_path):
    sources, library = ps3
    snapshot = backup_rpcs3(sources[0], library, emulator_closed=True)
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep").write_bytes(b"keep")
    with pytest.raises(BackupError, match="already exists"):
        restore_rpcs3(snapshot, library, existing)
    assert (existing / "keep").read_bytes() == b"keep"
    with pytest.raises(BackupError, match="overlap"):
        restore_rpcs3(snapshot, library, sources[1] / "new", configured_sources=tuple(sources))


def test_rpc3_cancelled_restore_preserves_snapshot(ps3, tmp_path):
    sources, library = ps3
    snapshot = backup_rpcs3(sources[0], library, emulator_closed=True)
    state = {"cancel": False}
    target = tmp_path / "restored"
    with pytest.raises(Cancelled):
        restore_rpcs3(snapshot, library, target, progress=lambda *_: state.update(cancel=True),
                      cancelled=lambda: state["cancel"])
    assert not target.exists()
    assert not list(tmp_path.glob(".memcard-restore-*"))
    verify_snapshot(snapshot)


def test_rpc3_failed_write_cleanup(ps3, tmp_path, monkeypatch):
    sources, library = ps3
    snapshot = backup_rpcs3(sources[0], library, emulator_closed=True)
    original = Path.open
    def fail(path, mode="r", *args, **kwargs):
        if mode == "xb":
            raise OSError("Simulated full disk")
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError):
        backup_rpcs3(sources[1], library, emulator_closed=True)
    with pytest.raises(OSError):
        restore_rpcs3(snapshot, library, tmp_path / "failed")
    assert list((library / "snapshots").iterdir()) == [snapshot]
    assert not list(tmp_path.glob(".memcard-restore-*"))
    verify_snapshot(snapshot)


def test_rpc3_moved_library_without_original_source(ps3, tmp_path):
    sources, library = ps3
    snapshot = backup_rpcs3(sources[0], library, emulator_closed=True)
    sources[0].rename(sources[0].with_name("old savedata"))
    moved = tmp_path / "moved"
    library.rename(moved)
    target = tmp_path / "recovered"
    restore_rpcs3(moved / "snapshots" / snapshot.name, moved, target)
    assert (target / "BLUS12345-SAVE" / "PARAM.SFO").read_bytes() == b"SFO00000001"


def test_rpc3_cli_backup_restore(ps3, tmp_path):
    sources, library = ps3
    runner = Path(__file__).parent / "cli_runner.py"
    result = subprocess.run([sys.executable, str(runner), "backup-rpcs3", "--source", str(sources[1]),
                             "--library", str(library), "--emulator-closed", "--yes"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    snapshot = next((library / "snapshots").iterdir())
    target = tmp_path / "cli restore"
    result = subprocess.run([sys.executable, str(runner), "restore-rpcs3", str(snapshot), "--library", str(library),
                             "--target", str(target), "--source", str(sources[1]), "--yes"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert_same_tree(sources[1], target)
