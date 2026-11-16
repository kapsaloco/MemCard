"""Snapshot manifest v1 validation and independent payload verification."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID

from .paths import BackupError, checked_path, inventory, relative_name


def file_hash(path: Path) -> str:
    path = checked_path(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate(data: dict) -> dict:
    if not isinstance(data, dict):
        raise BackupError("Manifest must be an object")
    required = {"schema_version", "snapshot_id", "created_at_utc", "app_version",
                "preset", "source_path", "directories", "files"}
    if not required <= data.keys():
        raise BackupError("Manifest is missing required fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise BackupError("Unsupported manifest schema")
    try:
        UUID(data["snapshot_id"])
        preset = data["preset"]
        UUID(preset["id"])
        if preset["kind"] not in {"pcsx2_memory_cards", "pcsx2_save_states", "rpcs3_savedata", "custom"}:
            raise ValueError("Invalid preset kind")
        if not isinstance(preset["label"], str) or not preset["label"].strip():
            raise ValueError("Invalid preset label")
        timestamp = data["created_at_utc"]
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ValueError("Timestamp must use UTC Z suffix")
        datetime.fromisoformat(timestamp)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise BackupError(f"Invalid manifest metadata: {error}") from error
    for field in ("app_version", "source_path"):
        if not isinstance(data[field], str) or not data[field]:
            raise BackupError(f"Invalid {field}")
    if not isinstance(data["directories"], list) or not isinstance(data["files"], list):
        raise BackupError("Files and directories must be lists")
    if not data["files"]:
        raise BackupError("Snapshot must contain at least one file")
    names = {}
    directories = set()
    for name in data["directories"]:
        relative_name(name)
        directories.add(name)
        key = name.casefold()
        if key in names:
            raise BackupError(f"Duplicate or conflicting path: {name}")
        names[key] = name
    for entry in data["files"]:
        if not isinstance(entry, dict) or not {"path", "size_bytes", "sha256"} <= entry.keys():
            raise BackupError("Invalid file entry")
        name = relative_name(entry["path"])
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0:
            raise BackupError(f"Invalid file size: {name}")
        if not isinstance(entry["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", entry["sha256"]):
            raise BackupError(f"Invalid hash: {name}")
        if name.casefold() in names:
            raise BackupError(f"Duplicate or conflicting path: {name}")
        names[name.casefold()] = name
    for name in names.values():
        parent = name.rpartition("/")[0]
        if parent and parent not in directories:
            raise BackupError(f"Undeclared parent directory: {name}")
    return data


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_manifest(snapshot: str | Path) -> dict:
    """Read metadata without claiming that payload contents are verified."""
    snapshot = checked_path(snapshot)
    manifest_path = checked_path(snapshot / "manifest.json")
    try:
        data = validate(json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackupError(f"Cannot read manifest: {error}") from error
    return data


def verify_snapshot(snapshot: str | Path) -> dict:
    snapshot = checked_path(snapshot)
    data = load_manifest(snapshot)
    payload = checked_path(snapshot / "payload")
    verify_payload(payload, data)
    return data


def verify_payload(payload: Path, data: dict) -> None:
    """Verify an ordinary folder against an already validated manifest."""
    directories, files = inventory(payload)
    expected = {entry["path"]: entry for entry in data["files"]}
    if set(directories) != set(data["directories"]) or files.keys() != expected.keys():
        raise BackupError("Payload has missing or unexpected files/directories")
    for name, entry in expected.items():
        if files[name][0] != entry["size_bytes"] or file_hash(payload / name) != entry["sha256"]:
            raise BackupError(f"File failed verification: {name}")
    if inventory(payload) != (directories, files):
        raise BackupError("Payload changed during verification")
