"""Small, atomic preferences file; snapshots never depend on these settings."""

import json
import os
from pathlib import Path
from uuid import uuid4


def settings_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MemCard" / "settings.json"


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object")
    result = {key: value for key, value in data.items()
              if key in {"source", "library", "pcsx2_source", "rpcs3_source", "mode", "theme", "rpcs3_executable"}
              and isinstance(value, str)}
    if result.get("mode") not in {"pcsx2", "rpcs3"}:
        result.pop("mode", None)
    if result.get("theme") not in {"light", "dark"}:
        result.pop("theme", None)
    if type(data.get("debug_expanded")) is bool:
        result["debug_expanded"] = data["debug_expanded"]
    return result


def save_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".settings-{uuid4()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
