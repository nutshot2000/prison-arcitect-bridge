import math
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import BridgeError


@dataclass(frozen=True)
class Config:
    executable: Path | None = None
    output_directory: Path = Path("runs")
    dry_run: bool = True
    max_drag_seconds: float = 5.0

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        data = tomllib.loads(path.read_text(encoding="utf-8")) if path else {}
        unknown = set(data) - {"executable", "output_directory", "dry_run", "max_drag_seconds"}
        if unknown:
            raise BridgeError(f"Unknown configuration fields: {sorted(unknown)}")
        if type(data.get("dry_run", True)) is not bool:
            raise BridgeError("dry_run must be a TOML boolean.")
        for name in ("executable", "output_directory"):
            if name in data and (not isinstance(data[name], str) or not data[name].strip()):
                raise BridgeError(f"{name} must be a nonempty path string.")
        duration = data.get("max_drag_seconds", 5.0)
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0.05 <= duration <= 10:
            raise BridgeError("max_drag_seconds must be finite and between 0.05 and 10.")
        base = path.resolve().parent if path else Path.cwd()
        executable = (base / data["executable"]).resolve() if data.get("executable") else None
        return cls(executable, (base / data.get("output_directory", "runs")).resolve(),
                   data.get("dry_run", True), float(duration))


def user_data_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Introversion/Prison Architect"


def stop_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "PA-Agent/STOP"
