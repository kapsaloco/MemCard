"""Resource paths work from both source and a PyInstaller bundle."""

from pathlib import Path


ASSET_DIRECTORY = Path(__file__).resolve().parent / "assets"
APP_LOGO = ASSET_DIRECTORY / "MemCardLogo.png"
