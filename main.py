"""Launch the desktop alpha, or run the existing command-line tools."""

import argparse
import os
from pathlib import Path
import sys

from memcard.manifest import verify_snapshot
from memcard.discovery import find_pcsx2_memcards
from memcard.instance import single_instance
from memcard.paths import BackupError, checked_path, inventory, reject_overlap
from memcard.snapshots import backup_pcsx2, backup_rpcs3, restore_pcsx2, restore_rpcs3


def select_source(explicit: Path | None, *, noninteractive: bool = False) -> Path:
    if explicit is not None:
        return explicit
    candidate = find_pcsx2_memcards()
    if candidate is not None:
        print(f"Found PCSX2 memory-card folder: {candidate}")
        print("Confirm this is the folder used by PCSX2; override with --source if needed.")
        return candidate
    if noninteractive:
        raise BackupError("PCSX2 memory-card folder not found in Documents. Provide --source with its actual path.")
    print("PCSX2 memory-card folder not found in Documents.")
    print("Find it in PCSX2: Settings > Memory Cards > Browse.")
    entered = input("Memory-card directory (blank to cancel): ").strip().strip('"')
    if not entered:
        raise BackupError("No memory-card directory selected; no backup created")
    return Path(entered)


def main() -> int:
    if len(sys.argv) == 1 or sys.argv[1:] == ["gui"]:
        from memcard.ui import launch
        return launch()
    parser = argparse.ArgumentParser(description="MemCard: verified PCSX2 and RPCS3 save backups")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup-pcsx2", help="Back up a confirmed memory-card folder")
    backup.add_argument("--source", type=Path, help="Memory-card folder; otherwise try Windows Documents, then ask")
    backup.add_argument("--library", type=Path, required=True, help="Existing backup library folder")
    backup.add_argument("--label", default="PCSX2 memory cards")
    backup.add_argument("--emulator-closed", action="store_true", required=True)
    backup.add_argument("--yes", action="store_true", help="Confirm the displayed paths without prompting")
    ps3_backup = commands.add_parser("backup-rpcs3", help="Back up one RPCS3 user's savedata folder")
    ps3_backup.add_argument("--source", type=Path, required=True, help="Confirmed savedata folder for one RPCS3 user")
    ps3_backup.add_argument("--library", type=Path, required=True)
    ps3_backup.add_argument("--label", default=None)
    ps3_backup.add_argument("--emulator-closed", action="store_true", required=True)
    ps3_backup.add_argument("--yes", action="store_true")
    restore = commands.add_parser("restore-pcsx2", help="Restore a verified PCSX2 snapshot into a new folder")
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--library", type=Path, required=True)
    restore.add_argument("--target", type=Path, required=True, help="New folder path; its parent must exist")
    restore.add_argument("--source", type=Path, action="append", default=[], help="Protect a current save directory; repeat if needed")
    restore.add_argument("--yes", action="store_true", help="Confirm restore without prompting")
    ps3_restore = commands.add_parser("restore-rpcs3", help="Restore RPCS3 savedata into a new folder")
    ps3_restore.add_argument("snapshot", type=Path)
    ps3_restore.add_argument("--library", type=Path, required=True)
    ps3_restore.add_argument("--target", type=Path, required=True)
    ps3_restore.add_argument("--source", type=Path, action="append", default=[], help="Protect a current save directory; repeat if needed")
    ps3_restore.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        with single_instance():
            if args.command in {"restore-pcsx2", "restore-rpcs3"}:
                emulator = "RPCS3" if args.command == "restore-rpcs3" else "PCSX2"
                data = verify_snapshot(args.snapshot)
                print(f"Snapshot: {args.snapshot.absolute()}\nDate: {data['created_at_utc']}")
                print(f"Preset: {data['preset']['label']}; files: {len(data['files'])}")
                print(f"New target: {args.target.absolute()}")
                if not args.yes and input("Restore into this new folder? [y/N] ").strip().lower() != "y":
                    print("Cancelled; no restore created.")
                    return 0
                sources = list(args.source)
                detected = find_pcsx2_memcards()
                if detected is not None:
                    sources.append(detected)
                restore_operation = restore_rpcs3 if emulator == "RPCS3" else restore_pcsx2
                result = restore_operation(args.snapshot, args.library, args.target,
                                        configured_sources=tuple(sources),
                                        progress=lambda done, total, name: print(f"[{done}/{total}] {name}"))
                print(f"Verified folder restored: {result}")
            else:
                source = checked_path(select_source(args.source, noninteractive=args.yes))
                library = checked_path(args.library)
                reject_overlap(source, library)
                _, files = inventory(source)
                print(f"Source: {source}\nLibrary: {library}")
                print(f"Files: {len(files)}; bytes: {sum(info[0] for info in files.values())}")
                if library.drive.casefold() == os.environ.get("SystemDrive", "C:").casefold():
                    print("Warning: the library is on the Windows system volume.")
                if not args.yes and input("Create this backup? [y/N] ").strip().lower() != "y":
                    print("Cancelled; no backup created.")
                    return 0
                backup_operation = backup_rpcs3 if args.command == "backup-rpcs3" else backup_pcsx2
                result = backup_operation(source, library, emulator_closed=args.emulator_closed,
                                      label=args.label,
                                      progress=lambda done, total, name: print(f"[{done}/{total}] {name}"))
                print(f"Verified snapshot created: {result}")
        return 0
    except (BackupError, OSError, EOFError) as error:
        print(f"MemCard: {error}", file=sys.stderr)
        for note in getattr(error, "__notes__", []):
            print(note, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
