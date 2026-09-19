import os
import re
from pathlib import Path

import psutil

from ..errors import BridgeError

EXECUTABLE_NAMES = {"prison architect.exe", "prison architect64.exe"}


def discover_executables() -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
    roots.append(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Steam")
    for root in list(roots):
        libraries = root / "steamapps/libraryfolders.vdf"
        if libraries.is_file():
            roots.extend(Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', libraries.read_text(encoding="utf-8")))
    found = set()
    for root in roots:
        manifest = root / "steamapps/appmanifest_233450.acf"
        if not manifest.is_file():
            continue
        match = re.search(r'"installdir"\s+"([^"]+)"', manifest.read_text(encoding="utf-8"))
        if match:
            for name in ("Prison Architect64.exe", "Prison Architect.exe"):
                path = root / "steamapps/common" / match[1] / name
                if path.is_file():
                    found.add(path.resolve())
    return sorted(found)


def expected_executables(explicit: Path | None) -> list[Path]:
    if explicit:
        if explicit.name.lower() not in EXECUTABLE_NAMES or not explicit.is_file():
            raise BridgeError("Configured executable must be an existing Prison Architect executable.")
        return [explicit.resolve()]
    return discover_executables()


def find_prison_architect_processes(paths: list[Path]) -> list[dict]:
    allowed = {str(p.resolve()).casefold() for p in paths}
    result = []
    for process in psutil.process_iter(["pid", "name", "exe", "create_time"]):
        info = process.info
        if (info["name"] or "").lower() in EXECUTABLE_NAMES and info["exe"]:
            if str(Path(info["exe"]).resolve()).casefold() in allowed:
                result.append(info)
    return result
