"""Emulator folder backups and recovery, published after full verification."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from . import __version__
from .manifest import validate, verify_payload, verify_snapshot
from .paths import BackupError, checked_path, inventory, reject_overlap, relative_name


class Cancelled(BackupError):
    """A job was cancelled before publication."""


def _backup_folder(source: str | Path, library: str | Path, *, emulator_closed: bool,
                 kind: str, emulator: str,
                 label: str = "PCSX2 memory cards", preset_id: str | None = None,
                 progress: Callable[[int, int, str], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> Path:
    """Copy the entire confirmed save folder; never modify source files.

    Library must already exist. Progress receives completed files, total files,
    and the payload-relative name. Callbacks run on the calling thread.
    """
    if emulator_closed is not True:
        raise BackupError(f"Close {emulator} and confirm before backing up")
    source, library = checked_path(source), checked_path(library)
    reject_overlap(source, library)
    if not library.is_dir():
        raise BackupError(f"Library must be an existing directory: {library}")
    before = inventory(source)
    directories, files = before
    if not files:
        raise BackupError(f"Source has no files: {source}")
    if shutil.disk_usage(library).free < sum(info[0] for info in files.values()) + 1024 * 1024:
        raise BackupError("Library has insufficient free space")
    snapshot_id = str(uuid4())
    now = datetime.now(timezone.utc)
    data = {"schema_version": 1, "snapshot_id": snapshot_id,
            "created_at_utc": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "app_version": __version__, "preset": {"id": preset_id or str(uuid4()),
            "kind": kind, "label": label}, "source_path": str(source),
            "directories": directories, "files": []}
    # Validate metadata before creating staging files.
    validate({**data, "files": [{"path": name, "size_bytes": info[0], "sha256": "0" * 64}
                                for name, info in files.items()]})
    snapshots = library / "snapshots"
    snapshots.mkdir(exist_ok=True)
    checked_path(snapshots)
    staging = snapshots / f".staging-{snapshot_id}"
    final = snapshots / f"{now:%Y%m%dT%H%M%SZ}_{snapshot_id}"

    def check_cancel():
        if cancelled and cancelled():
            raise Cancelled("Backup cancelled; no snapshot published")

    check_cancel()
    staging.mkdir()
    try:
        payload = staging / "payload"
        payload.mkdir()
        for name in directories:
            (payload / name).mkdir()
        for index, (name, info) in enumerate(files.items(), 1):
            check_cancel()
            origin = checked_path(source / name)
            digest = hashlib.sha256()
            with origin.open("rb") as reader, (payload / name).open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            data["files"].append({"path": name, "size_bytes": info[0], "sha256": digest.hexdigest()})
            if progress:
                progress(index, len(files), name)
        if inventory(source) != before:
            raise BackupError(f"Source changed during backup; close {emulator} and retry")
        with (staging / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(validate(data), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        verify_snapshot(staging)
        check_cancel()
        if inventory(source) != before:
            raise BackupError("Source changed before publication")
        staging.rename(final)
        return final
    except BaseException as error:
        try:
            shutil.rmtree(staging)
        except OSError as cleanup_error:
            error.add_note(f"Staging cleanup failed at {staging}: {cleanup_error}")
        raise


def _restore_folder(snapshot: str | Path, library: str | Path, target: str | Path, *,
                  kind: str, emulator: str,
                  configured_sources: tuple[Path, ...] = (),
                  progress: Callable[[int, int, str], None] | None = None,
                  cancelled: Callable[[], bool] | None = None) -> Path:
    """Restore into a new folder under an existing parent; never replace files.

    The original source path in the manifest is reference information only.
    Pass any currently configured save directories to protect them as well.
    Publication uses Windows rename, which fails if the target already exists.
    """
    if os.name != "nt":
        raise BackupError("Restore publication currently requires Windows")
    snapshot, library = checked_path(snapshot), checked_path(library)
    snapshots = checked_path(library / "snapshots")
    if snapshot.parent != snapshots or snapshot.name.startswith(".staging-"):
        raise BackupError(f"Select a finalized snapshot directly inside {snapshots}: {snapshot}")
    target = Path(target)
    relative_name(target.name)
    target = Path(os.path.abspath(target))

    def check_target():
        parent = checked_path(target.parent)
        if not parent.is_dir():
            raise BackupError(f"Restore parent must be an existing directory: {parent}")
        if os.path.lexists(target):
            raise BackupError(f"Restore target already exists: {target}")
        reject_overlap(target, library)
        for source in configured_sources:
            source = Path(os.path.abspath(source))
            reject_overlap(target, source)

    def check_cancel():
        if cancelled and cancelled():
            raise Cancelled("Restore cancelled; no target published")

    check_target()
    check_cancel()
    data = verify_snapshot(snapshot)
    if data["preset"]["kind"] != kind:
        raise BackupError(f"Select a {emulator} snapshot")
    if shutil.disk_usage(target.parent).free < sum(item["size_bytes"] for item in data["files"]) + 1024 * 1024:
        raise BackupError("Restore destination has insufficient free space")
    staging = target.parent / f".memcard-restore-{uuid4()}"
    check_cancel()
    staging.mkdir()
    try:
        # Sort by depth so even externally created manifests with unordered
        # directory entries can be recovered.
        for name in sorted(data["directories"], key=lambda name: (name.count("/"), name)):
            (staging / name).mkdir()
        for index, entry in enumerate(data["files"], 1):
            check_cancel()
            name = entry["path"]
            origin = checked_path(snapshot / "payload" / name)
            with origin.open("rb") as reader, (staging / name).open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            if progress:
                progress(index, len(data["files"]), name)
        verify_payload(staging, data)
        check_cancel()
        check_target()
        staging.rename(target)
        return target
    except BaseException as error:
        try:
            shutil.rmtree(staging)
        except OSError as cleanup_error:
            error.add_note(f"Restore staging cleanup failed at {staging}: {cleanup_error}")
        raise


def backup_pcsx2(source: str | Path, library: str | Path, *, emulator_closed: bool,
                 label: str = "PCSX2 memory cards", **kwargs) -> Path:
    """Back up an entire confirmed PCSX2 memory-card directory."""
    return _backup_folder(source, library, emulator_closed=emulator_closed,
                          kind="pcsx2_memory_cards", emulator="PCSX2", label=label, **kwargs)


def rpcs3_label(source: str | Path) -> str:
    user = Path(source).parent.name
    if len(user) == 8 and user.isascii() and user.isdigit():
        return f"RPCS3 user {user}"
    return "RPCS3 saved data"


def backup_rpcs3(source: str | Path, library: str | Path, *, emulator_closed: bool,
                 label: str | None = None, **kwargs) -> Path:
    """Back up one confirmed RPCS3 user's complete savedata tree."""
    return _backup_folder(source, library, emulator_closed=emulator_closed,
                          kind="rpcs3_savedata", emulator="RPCS3",
                          label=label if label is not None else rpcs3_label(source), **kwargs)


def restore_pcsx2(snapshot: str | Path, library: str | Path, target: str | Path, **kwargs) -> Path:
    """Recover PCSX2 cards into a new folder, without replacing live saves."""
    return _restore_folder(snapshot, library, target, kind="pcsx2_memory_cards", emulator="PCSX2", **kwargs)


def restore_rpcs3(snapshot: str | Path, library: str | Path, target: str | Path, **kwargs) -> Path:
    """Recover one RPCS3 user's savedata into a new folder."""
    return _restore_folder(snapshot, library, target, kind="rpcs3_savedata", emulator="RPCS3", **kwargs)


@dataclass(frozen=True)
class EmulatorRestoreResult:
    target: Path
    previous: Path | None


def _restore_current(snapshot, library, target, *, kind, emulator, emulator_closed,
                     configured_sources=(), progress=None, cancelled=None):
    """Prepare recovery first, then swap folders while retaining the old saves.

    Only the explicitly selected target may be replaced. A failed publication
    rolls the old directory back when possible; no previous saves are deleted.
    """
    if os.name != "nt":
        raise BackupError("Restore publication currently requires Windows")
    if emulator_closed is not True:
        raise BackupError(f"Close {emulator} and confirm the current save folder before restoring")
    target = Path(os.path.abspath(target))
    relative_name(target.name)
    parent = checked_path(target.parent)
    parent_info = parent.stat()
    library = checked_path(library)
    reject_overlap(target, library)
    protected = tuple(Path(os.path.abspath(source)) for source in configured_sources
                      if Path(os.path.abspath(source)) != target)
    for source in protected:
        reject_overlap(target, source)

    def target_state():
        checked_path(target.parent)
        info = target.parent.stat()
        if (info.st_dev, info.st_ino) != (parent_info.st_dev, parent_info.st_ino):
            raise BackupError(f"Restore parent changed: {parent}")
        if not os.path.lexists(target):
            return None
        path = checked_path(target)
        if not path.is_dir():
            raise BackupError(f"Current save target must be a directory: {target}")
        info = path.stat()
        return (info.st_dev, info.st_ino, inventory(path))

    before = target_state()
    identifier = uuid4()
    ready = parent / f".memcard-ready-{identifier}"
    previous = parent / f"{target.name}.before-MemCard-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{identifier}"
    moved_previous = False
    preserve_ready = False
    ready_created = False
    try:
        _restore_folder(snapshot, library, ready, kind=kind, emulator=emulator,
                        configured_sources=protected, progress=progress, cancelled=cancelled)
        ready_created = True
        if cancelled and cancelled():
            raise Cancelled("Restore cancelled before replacing the save folder")
        if target_state() != before:
            raise BackupError(f"Current saves changed during recovery; close {emulator} and retry: {target}")
        if before is not None:
            target.rename(previous)
            moved_previous = True
        try:
            ready.rename(target)
        except OSError as error:
            if moved_previous:
                try:
                    if os.path.lexists(target):
                        raise BackupError(f"Another process created the target: {target}")
                    previous.rename(target)
                    moved_previous = False
                except (OSError, BackupError) as rollback_error:
                    preserve_ready = True
                    error.add_note(f"Previous saves remain at {previous}. Verified recovery remains at {ready}. Rollback failed: {rollback_error}")
            raise
        return EmulatorRestoreResult(target, previous if moved_previous else None)
    except BaseException as error:
        if ready_created and os.path.lexists(ready) and not preserve_ready:
            try:
                shutil.rmtree(ready)
            except OSError as cleanup_error:
                error.add_note(f"Recovery staging remains at {ready}: {cleanup_error}")
        raise


def restore_pcsx2_current(snapshot, library, target, *, emulator_closed, **kwargs):
    return _restore_current(snapshot, library, target, kind="pcsx2_memory_cards", emulator="PCSX2",
                            emulator_closed=emulator_closed, **kwargs)


def restore_rpcs3_current(snapshot, library, target, *, emulator_closed, **kwargs):
    return _restore_current(snapshot, library, target, kind="rpcs3_savedata", emulator="RPCS3",
                            emulator_closed=emulator_closed, **kwargs)
