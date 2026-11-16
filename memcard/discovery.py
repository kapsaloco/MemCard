"""Find PCSX2's usual save folder without scanning drives or guessing usernames."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path
from uuid import UUID

import yaml

from .paths import BackupError, checked_path


def documents_directory() -> Path:
    """Ask Windows for Documents, including a redirected Documents location."""
    if os.name != "nt":
        raise OSError("Automatic Documents discovery requires Windows")
    # FOLDERID_Documents, passed as a 16-byte GUID in Windows byte order.
    folder_id = (ctypes.c_ubyte * 16).from_buffer_copy(
        UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le
    )
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = (
        ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    )
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
    ole.CoTaskMemFree.restype = None
    result = ctypes.c_void_p()
    try:
        status = shell.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(result))
        if status < 0:
            raise OSError(f"Windows could not locate Documents (HRESULT {status & 0xffffffff:#x})")
        return Path(ctypes.wstring_at(result))
    finally:
        if result.value:
            ole.CoTaskMemFree(result)


def find_pcsx2_memcards() -> Path | None:
    """Return a safe existing Documents/PCSX2/memcards candidate, if available.

    A candidate still needs user confirmation: existence does not establish
    that the active emulator configuration uses this directory.
    """
    try:
        candidate = checked_path(documents_directory() / "PCSX2" / "memcards")
        return candidate if candidate.is_dir() else None
    except (OSError, BackupError):
        return None


@dataclass(frozen=True)
class Rpcs3Location:
    executable: Path
    config_root: Path
    hdd0: Path
    users: tuple[Path, ...]
    warnings: tuple[str, ...] = ()


def discover_rpcs3(executable: str | Path) -> Rpcs3Location:
    """Read RPCS3's Windows VFS settings; never execute the selected program.

    Ambiguous relative custom paths are rejected instead of guessing RPCS3's
    working directory. The user can still select savedata manually.
    """
    executable = checked_path(executable)
    if executable.name.casefold() != "rpcs3.exe" or not executable.is_file():
        raise BackupError(f"Select the RPCS3 executable named rpcs3.exe: {executable}")
    root = executable.parent
    portable = root / "portable"
    override = os.environ.get("RPCS3_CONFIG_DIR", "")
    def exists(path):
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            return False

    if exists(portable):
        root = checked_path(portable)
    elif override:
        # RPCS3's Windows implementation strips the last component after
        # reading this variable, so a directory override needs a trailing slash.
        root = Path(override) if override.endswith(("/", "\\")) else Path(override).parent
        if not root.is_absolute():
            raise BackupError("RPCS3_CONFIG_DIR is relative; select the savedata folder manually")
        root = checked_path(root)
    if not root.is_dir():
        raise BackupError(f"RPCS3 data root is not a directory: {root}")
    vfs = root / "config" / "vfs.yml"
    if not exists(vfs):
        # Older RPCS3 layouts kept vfs.yml directly in the data root.
        vfs = root / "vfs.yml"
    settings = {}
    if exists(vfs):
        try:
            settings = yaml.safe_load(checked_path(vfs).read_text(encoding="utf-8-sig"))
        except (yaml.YAMLError, UnicodeError) as error:
            raise BackupError(f"Cannot read RPCS3 paths in {vfs}; select savedata manually: {error}") from error
        if settings is None:
            settings = {}
        if not isinstance(settings, dict):
            raise BackupError(f"Expected a YAML mapping in {vfs}; select savedata manually")
    emulator_dir = settings.get("$(EmulatorDir)", "")
    hdd_path = settings.get("/dev_hdd0/", "")
    if not isinstance(emulator_dir, str) or not isinstance(hdd_path, str):
        raise BackupError(f"Invalid RPCS3 path settings in {vfs}; select savedata manually")
    base = Path(emulator_dir) if emulator_dir else root
    if not base.is_absolute() or "$(" in str(base):
        raise BackupError("RPCS3 emulator directory is ambiguous; select savedata manually")
    value = (hdd_path or "$(EmulatorDir)dev_hdd0/").replace("$(EmulatorDir)", str(base).rstrip("/\\") + "/")
    hdd0 = Path(value)
    if not hdd0.is_absolute() or "$(" in value:
        raise BackupError("RPCS3 HDD path is relative or unsupported; select savedata manually")
    hdd0 = checked_path(hdd0)
    home = checked_path(hdd0 / "home")
    users, warnings = [], []
    for user in sorted(home.iterdir()):
        if len(user.name) != 8 or not user.name.isascii() or not user.name.isdigit():
            continue
        try:
            checked_path(user)
            savedata = user / "savedata"
            if exists(savedata):
                savedata = checked_path(savedata)
                if savedata.is_dir():
                    users.append(savedata)
        except (OSError, BackupError) as error:
            warnings.append(f"Could not inspect RPCS3 user {user.name}: {error}")
    return Rpcs3Location(executable, root, hdd0, tuple(users), tuple(warnings))
