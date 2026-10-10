"""Room requirements, read from the player's own copy of the game.

The game defines every room in ``data/materials.txt`` inside ``main.dat`` (a RAR archive):
``BEGIN Room ... BEGIN Requirement Type MinimumSize x 5 y 5 END ... END``. These are the same checks the game
shows in a room's tooltip ("[FAILED] Minimum Size 5 x 5", "[FAILED] Dog Crate"). Live 2 Oct 2026 a kennel
built 5x4 inside without a crate never worked, and nothing in the bridge said why.

Game data is not distributed with this project (AGENTS.md): ``extract()`` reads the installed game and caches
only the parsed requirements in ``runs/room_rules.json`` (git-ignored).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

CACHE = Path(__file__).resolve().parents[3] / "runs" / "room_rules.json"
UNRAR_CANDIDATES = (r"C:\Program Files\WinRAR\UnRAR.exe", r"C:\Program Files (x86)\WinRAR\UnRAR.exe")


def parse_rooms(text: str) -> dict[str, dict[str, Any]]:
    """Requirements of every ``BEGIN Room`` block in materials.txt.

    Each room: research (or None), min [x, y] (either orientation passes in the game), enclosed / indoor /
    outdoor / secure flags, objects = [[id, alternative ids...], ...] (one of each group is required),
    adjacent = objects that must stand next to the room, qualification (prisoner job program).
    """
    rooms: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("BEGIN Room"):
            if s.endswith("END"):  # one-line block, e.g. "BEGIN Room Name None END"
                continue
            cur = {"research": None, "min": None, "enclosed": False, "indoor": False, "outdoor": False,
                   "secure": False, "objects": [], "adjacent": [], "qualification": None}
            continue
        if cur is None:
            continue
        if s == "END":
            if cur.get("name"):
                rooms[cur.pop("name")] = cur
            cur = None
            continue
        words = s.split()
        if not words:
            continue
        if words[0] == "Name" and len(words) > 1:
            cur["name"] = words[1]
        elif words[0] == "Research" and len(words) > 1:
            cur["research"] = words[1]
        elif words[0] == "Qualification" and len(words) > 1:
            cur["qualification"] = words[1]
        elif s.startswith("BEGIN Requirement"):
            body = dict(re.findall(r"(\w+)\s+(\S+)", s[len("BEGIN Requirement"):].rsplit("END", 1)[0]))
            kind = body.get("Type")
            if kind == "MinimumSize":
                cur["min"] = [int(body.get("x", 1)), int(body.get("y", 1))]
            elif kind in ("Enclosed", "Indoor", "Outdoor", "Secure"):
                cur[kind.lower()] = True
            elif kind in ("Object", "AdjacentObject") and body.get("Id"):
                group = [body["Id"]] + [a for a in body.get("Alt", "").split(",") if a]
                cur["objects" if kind == "Object" else "adjacent"].append(group)
    return rooms


def _main_dat() -> Path | None:
    from ..game.process import discover_executables
    for exe in discover_executables():
        p = exe.parent / "main.dat"
        if p.is_file():
            return p
    return None


def _unrar() -> str | None:
    for c in UNRAR_CANDIDATES:
        if os.path.isfile(c):
            return c
    return shutil.which("unrar") or shutil.which("UnRAR")


def extract(materials: Path | None = None, cache: Path = CACHE) -> dict[str, dict[str, Any]]:
    """Parse the room requirements from the installed game (or a given materials.txt) and cache them."""
    if materials is None:
        dat, tool = _main_dat(), _unrar()
        if dat is None:
            raise RuntimeError("could not find the game's main.dat (Steam install of Prison Architect)")
        if tool is None:
            raise RuntimeError("main.dat is a RAR archive: install WinRAR/UnRAR, or pass the path of an "
                               "extracted data/materials.txt")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([tool, "e", "-y", "-inul", str(dat), "data\\materials.txt", tmp + os.sep],
                           check=True, timeout=120)
            text = (Path(tmp) / "materials.txt").read_text(encoding="latin-1")
    else:
        text = Path(materials).read_text(encoding="latin-1")
    rules = parse_rooms(text)
    if not rules:
        raise RuntimeError("no room definitions found in materials.txt")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rules, indent=1, sort_keys=True), encoding="utf-8")
    return rules


def load(cache: Path = CACHE, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Cached rules, extracting them from the game the first time. Empty when the game data is unavailable."""
    if cache.is_file() and not refresh:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    try:
        return extract(cache=cache)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return {}


def cached(cache: Path = CACHE) -> dict[str, dict[str, Any]]:
    """Rules from the cache only (never runs the extractor; for the save report)."""
    try:
        return json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    except (OSError, ValueError):
        return {}


def as_report_reqs(rules: dict[str, dict[str, Any]]) -> dict[str, dict]:
    """The game's rules in report.ROOM_REQS form (min, indoor, secure, objects)."""
    out = {}
    for name, r in rules.items():
        req: dict[str, Any] = {}
        if r.get("min"):
            req["min"] = tuple(r["min"])
        if r.get("indoor") or r.get("enclosed"):
            req["indoor"] = True
        if r.get("secure"):
            req["secure"] = True
        if r.get("objects"):
            req["objects"] = [tuple(g) for g in r["objects"]]
        out[name] = req
    return out


def describe(name: str, r: dict[str, Any]) -> str:
    parts = []
    if r.get("min"):
        parts.append(f"at least {r['min'][0]}x{r['min'][1]} inside")
    for flag, text in (("enclosed", "enclosed (walls and doors all round)"), ("indoor", "indoors"),
                       ("outdoor", "outdoors"), ("secure", "secure (prisoners cannot walk out without a door)")):
        if r.get(flag):
            parts.append(text)
    for g in r.get("objects", []):
        parts.append(g[0] + (f" (or {', '.join(g[1:])})" if len(g) > 1 else ""))
    for g in r.get("adjacent", []):
        parts.append(f"a {g[0]} next to it")
    head = name + (f" [research {r['research']}]" if r.get("research") else "")
    tail = f"; workers need the {r['qualification']} program" if r.get("qualification") else ""
    return f"{head}: " + ("; ".join(parts) if parts else "no requirements") + tail
