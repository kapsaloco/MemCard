"""Conservative Windows path checks shared by backup and verification."""

import os
from pathlib import Path
import re
import stat


class BackupError(ValueError):
    """An operation cannot safely continue."""


def checked_path(path: str | Path) -> Path:
    """Reject links and reparse points, including in ancestor directories."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BackupError(f"Links and reparse points are unsupported: {part}")
    return path


def relative_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise BackupError("Invalid empty payload path")
    for part in name.split("/"):
        if (not part or part in {".", ".."} or part.endswith((".", " "))
                or re.search(r'[<>:"\\|?*\x00-\x1f]', part)
                or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", part.split(".")[0])):
            raise BackupError(f"Invalid Windows payload path: {name!r}")
    return name


def reject_overlap(source: Path, library: Path) -> None:
    if source == library or source in library.parents or library in source.parents:
        raise BackupError(f"Source and library overlap: {source} / {library}")


def inventory(root: Path) -> tuple[list[str], dict[str, tuple[int, int, int, int]]]:
    """Record all entries; scandir errors propagate rather than hiding files."""
    root = checked_path(root)
    if not root.is_dir():
        raise BackupError(f"Expected a directory: {root}")
    directories, files, seen = [], {}, set()

    def walk(folder: Path) -> None:
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = checked_path(entry.path)
                name = relative_name(path.relative_to(root).as_posix())
                key = name.casefold()
                if key in seen:
                    raise BackupError(f"Case-insensitive path collision: {name}")
                seen.add(key)
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    directories.append(name)
                    walk(path)
                elif stat.S_ISREG(info.st_mode):
                    files[name] = (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino)
                else:
                    raise BackupError(f"Unsupported file type: {path}")

    walk(root)
    return sorted(directories), files
