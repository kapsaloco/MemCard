# Windows folder distribution, including the supplied application logo.
from pathlib import Path
import sys

project = Path(SPECPATH)
assets = project / "memcard" / "assets"
sys.path.insert(0, str(project))
from memcard.about import about_text

# Generate from the same metadata as the About dialog on every build.
(project / "ABOUT.txt").write_text(about_text(), encoding="utf-8")

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(assets), "memcard/assets")],
    # Also support installations using only PySide6 Essentials.
    hiddenimports=["PySide6.support.deprecated"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MemCard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(assets / "MemCard.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MemCard")
(Path(DISTPATH) / "MemCard" / "ABOUT.txt").write_text(about_text(), encoding="utf-8")
