# MemCard developer documentation

For application instructions, setup, tests, and building, see [README.md](README.md).

## Architecture

The filesystem engine is independent of Qt. The desktop runs discovery, scans, backup, and recovery on background threads. Conflicting controls and navigation are disabled during jobs. A Windows mutex prevents concurrent app/CLI operations in the same session.

| Module | Responsibility |
| --- | --- |
| `main.py` | Desktop launch and CLI |
| `snapshots.py` | Verified backup and recovery operations |
| `manifest.py` | Manifest validation and payload verification |
| `paths.py` | Windows path checks and file-tree inventory |
| `discovery.py` | PCSX2 Documents and RPCS3 configuration discovery |
| `ui.py`, `views.py` | Guided screens, jobs, confirmations, results |
| `themes.py`, `assets.py` | Appearance and application resources |
| `settings.py`, `instance.py` | Local preferences and single-instance guard |
| `about.py` | Public attribution and shared About content |

All modules except the entry point live under `memcard/`. The version comes from `memcard/__init__.py`. Tests create disposable save fixtures. `tools/build_icon.py` generates the Windows icon, and `MemCard.spec` packages the app and generates `ABOUT.txt` from shared metadata.

## Dependencies

`requirements.txt` contains Qt Essentials, matching Shiboken bindings, and PyYAML. MemCard uses Qt Core, GUI, Widgets, and test helpers; PDF, WebEngine, and Qt Addons are not required. `requirements-dev.txt` adds pinned test/build tooling. The packaging specification explicitly includes Qt's deprecated-enum support module for installations without the umbrella PySide6 distribution.

## Discovery

PCSX2's default candidate is `<Windows Documents>\PCSX2\memcards`. Windows Known Folders handles redirected Documents locations; custom/portable folders can be selected manually.

RPCS3 discovery inspects the selected executable without running it. It reads the current data root, optional `portable` directory, available `RPCS3_CONFIG_DIR` override, and `config\vfs.yml` (with a legacy root-level fallback). It resolves `$(EmulatorDir)` and `/dev_hdd0/` settings, then enumerates `home\<8-digit user ID>\savedata` directories. Ambiguous relative paths, malformed configuration, and reparse points do not silently fall back to guessed defaults. Launcher-specific environment settings unavailable to MemCard cannot be inferred.

## Snapshot storage

```text
<library>/snapshots/
  <UTC timestamp>_<UUID>/
    manifest.json
    payload/
  .staging-<UUID>/
```

Backups copy one entire confirmed directory, including hidden files and empty directories. Emulator data is treated as opaque bytes. Source inventory is checked before and after copying. Every staged copy is independently verified with SHA-256 before publication. Failed/cancelled jobs leave earlier snapshots intact; staging directories are ignored by history.

### Manifest v1

The UTF-8 JSON manifest requires `schema_version` (integer `1`), UUID `snapshot_id`, UTC `created_at_utc` with a `Z` suffix, `app_version`, `preset` (UUID `id`, `kind`, `label`), original `source_path`, `directories`, and `files`.

Each file records `path`, nonnegative integer `size_bytes`, and lowercase hexadecimal `sha256`. Relative paths use forward slashes. Counts and byte totals derive from file entries. Validation rejects unsupported versions, invalid types, duplicate entries/JSON keys, Windows case collisions, file/directory conflicts, undeclared parents, path traversal, drive/UNC paths, reserved devices, alternate streams, and invalid Windows characters. Verification detects missing, unexpected, and changed files/directories.

The schema accepts PCSX2 memory-card/save-state, RPCS3 saved-data, and custom kinds. The current UI exposes PCSX2 memory cards and RPCS3 saved data. The original source path is reference information; recovery never automatically trusts it as a destination on another computer.

## Recovery

Both modes re-verify the backup, stage the recovered tree beside the destination, and verify it before publication.

- **New folder:** the parent must exist and the target must not. Reject library/source overlap and reparse points. Publish with a Windows rename that fails if a competing target exists.
- **Current save folder:** require the emulator-closed/path checkbox and explicit replacement confirmation. Prepare the complete verified recovery first. Recheck the current directory's identity/inventory, rename it to a unique sibling `.before-MemCard` folder, then publish the recovery. Never merge or delete previous saves. Attempt rollback on publication failure. If rollback cannot finish, preserve both copies and report their locations. Cancellation is checked before the final swap, not between its renames.

Contents and directory structure are the preservation contract. ACLs, alternate streams, and filesystem-specific metadata are outside it. Closing the emulator is necessary: inventory checks cannot create an atomic snapshot of files another process is writing. Explorer can recover files directly from a snapshot's ordinary `payload` directory.

## CLI

Run `main.py` without arguments (or with `gui`) for the desktop. CLI commands:

```text
backup-pcsx2 --library <folder> --emulator-closed [--source <memcards>]
backup-rpcs3 --library <folder> --source <savedata> --emulator-closed
restore-pcsx2 <snapshot> --library <folder> --target <new-folder>
restore-rpcs3 <snapshot> --library <folder> --target <new-folder>
```

Use `--help` for options. `--yes` deliberately skips confirmation. Restore supports repeated `--source` paths to protect save directories. CLI recovery creates new folders; replacement is a desktop flow. Verification is automatic, with no standalone manual verify command.

## Local data and privacy

Settings and rotating logs live under `%LOCALAPPDATA%\MemCard`. Settings writes use a temporary file and atomic replacement. Logs include paths and operation errors, not save contents. Snapshot manifests include the original source path. Keep these local files and real saves out of commits and review them before sharing.

Public attribution is confined to the About metadata and generated `ABOUT.txt`. Documentation uses placeholders and tests use temporary folders. Git ignores generated output, previews, caches, environments, local credentials/settings, and standard save folders. Do not force-add ignored artifacts.

Before distributing a build, test launch, folder pickers, backup, and both recovery modes on Windows without Python. Keep the complete output folder together. Automated source tests do not replace that packaging check.
