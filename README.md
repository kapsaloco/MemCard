# MemCard

A Windows desktop app for backing up and restoring **PCSX2** and **RPCS3** game saves.

MemCard copies complete save folders, verifies their contents, and keeps dated backups you can browse in Windows Explorer. It supports light/dark themes and remembers your folders.

## Using the app

If you have a Windows build, extract the entire folder and run **MemCard.exe**. Keep the accompanying files and `_internal` folder together.

1. Choose **PCSX2 (PlayStation 2)** or **RPCS3 (PlayStation 3)**.
2. Choose **Back up saves** or **Restore saves**.
3. Follow the folder selection and confirmation steps.

### Back up

- Close the emulator before starting.
- PCSX2 can find the default memory-card folder in Windows Documents. Use **Change folders / show details** for custom or portable installations.
- For RPCS3, select `rpcs3.exe`, then choose the user whose saves you want to back up. You can also select the `savedata` folder manually.
- Choose a backup destination and click **Back up now**. MemCard verifies the copied files before publishing the backup.

### Restore

Select a backup and choose either:

- **A new folder:** recover a copy without replacing existing files.
- **The current emulator save folder:** confirm the current installation/user and accept the replacement warning. The previous folder is retained beside it with a `.before-MemCard-…` name.

The backup and recovered files are checked automatically. Completion buttons let you open the resulting folder or return to the main menu.

Backups contain memory-card/save data, not games, firmware, trophies, licences, or a complete emulator installation. RPCS3 users are backed up separately.

## Run from source

The tested development baseline is **Python 3.15.2, Windows x64**. From the project folder in PowerShell:

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Using the virtual environment's Python directly does not require PowerShell activation.

## Development

Install the test/build tools and run the tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Build the Windows folder distribution:

```powershell
.\.venv\Scripts\python.exe tools/build_icon.py
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm MemCard.spec
```

The executable is written to `dist\MemCard\MemCard.exe`, with `ABOUT.txt` beside it. Distribute the entire `dist\MemCard` folder.

See [developer documentation](Documentation.md) for the storage format, architecture, and CLI. Project attribution and repository links are in [ABOUT.txt](ABOUT.txt).

## Local data

Settings and logs stay in `%LOCALAPPDATA%\MemCard`. Backups stay in the folder you select and include the original source path in their manifest. Saves are not uploaded. Keep backups, logs, credentials, and local settings out of source control; `.gitignore` covers the standard locations and file types.
