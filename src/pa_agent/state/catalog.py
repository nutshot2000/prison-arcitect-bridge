"""Everything the player can build, read from their own copy of the game.

Floors, walls and objects are defined in ``data/materials.txt`` and ``data/materials_dlc.txt`` inside
``main.dat`` (``BEGIN Material`` / ``BEGIN Object`` blocks); the names the toolbar shows come from
``data/language/base-language.txt`` (``material_concretefloor  Concrete Floor``, lower-case keys) and
``data/language/d11.txt`` (DLC items, mixed-case keys). The bridge passes any name straight to the game, so the
agent can build anything once it knows the internal name: on 10 Oct 2026 the bridge knew 42 of the game's 147
materials and the sizes of 41 objects, and "Dark Wood Floor" (DarkWoodFloor) was out of reach.

Game data is not distributed with this project (AGENTS.md): ``extract()`` reads the installed game and caches
only the parsed fields in ``runs/catalog.json`` (git-ignored).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .room_rules import _main_dat, _unrar

CACHE = Path(__file__).resolve().parents[3] / "runs" / "catalog.json"
SOURCES = ("data\\materials.txt", "data\\materials_dlc.txt")
LANGUAGE = ("data\\language\\base-language.txt", "data\\language\\d11.txt")

# toolbar tools and engine-only materials: not something to build
INTERNAL_MATERIALS = {"None", "Building", "BuildingConcrete", "Demolish", "DemolishWalls", "RemoveTunnels",
                      "ClearIndoorArea", "CancelJobs", "Roof", "BuildingFrame", "IslandGenerator", "SellMaterial",
                      "SellFlooring", "RebarReinforcement"}
INTERNAL_PREFIXES = ("Burnt", "Collapsed")


def parse_items(text: str) -> dict[str, dict[str, Any]]:
    """Every ``BEGIN Material`` / ``BEGIN Object`` block: kind, size, cost, research, DLC, properties."""
    items: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    depth = 0
    for raw in text.splitlines():
        s = raw.strip()
        if cur is None:
            m = re.match(r"BEGIN (Material|Object)\b", s)
            if m and not s.endswith("END"):
                cur = {"block": m.group(1), "props": []}
                depth = 0
            continue
        if s.startswith("BEGIN"):
            if not s.endswith("END"):
                depth += 1
            continue
        if s == "END":
            if depth:
                depth -= 1
                continue
            name = cur.pop("name", None)
            if name:
                items[name] = _classify(name, cur)
            cur = None
            continue
        words = s.split()
        if len(words) < 2 or depth:
            continue
        key, val = words[0], words[1]
        if key == "Name":
            cur["name"] = val
        elif key in ("Width", "Height", "Price", "Upkeep"):
            try:
                cur[key.lower()] = int(float(val))
            except ValueError:
                pass
        elif key in ("Research", "DLC", "Filter", "Group"):
            cur[key.lower()] = val
        elif key == "BlockMovement":
            cur["blocks"] = val.lower() == "true"
        elif key == "Properties":
            cur["props"].append(val)
    return items


def _classify(name: str, b: dict[str, Any]) -> dict[str, Any]:
    props = set(b.get("props", []))
    if b["block"] == "Material":
        if name in INTERNAL_MATERIALS or name.startswith(INTERNAL_PREFIXES) or "Overlay" in name:
            kind = "internal"
        elif b.get("blocks") or name.endswith(("Wall", "Fence")) or "Fence" in name:
            kind = "wall"
        else:
            kind = "floor"
    elif props & {"Entity", "Staff"}:
        kind = "character"
    elif "Vehicle" in props:
        kind = "vehicle"
    elif props & {"StaticObject", "Door", "BuiltOnWall", "Window"}:
        kind = "object"
    else:
        kind = "item"  # carried things: food, tools, contraband, deliveries
    out: dict[str, Any] = {"kind": kind}
    if kind == "object":
        out["size"] = [b.get("width", 1), b.get("height", 1)]
    price = b.get("price")
    if price:
        out["cost"] = -price if price < 0 else price
    for k in ("research", "dlc", "filter"):
        if b.get(k):
            out[k] = b[k]
    if props & {"Electrical", "Wired"}:
        out["power"] = True
    if "WaterUtility" in props:
        out["water"] = True
    if "BuiltOnWall" in props:
        out["on_wall"] = True
    return out


def parse_names(text: str) -> dict[str, str]:
    """``material_x`` / ``object_x`` display names, keyed by the lower-case internal name."""
    names: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"(material|object)_(\w+)\s+(\S.*?)\s*$", line)
        if m:
            names.setdefault(m.group(2).lower(), m.group(3))
    return names


def extract(cache: Path = CACHE, files: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Read the installed game (or ``files``: archive path -> text, for tests) and cache the catalogue."""
    if files is None:
        dat, tool = _main_dat(), _unrar()
        if dat is None:
            raise RuntimeError("could not find the game's main.dat (Steam install of Prison Architect)")
        if tool is None:
            raise RuntimeError("main.dat is a RAR archive: install WinRAR/UnRAR")
        files = {}
        with tempfile.TemporaryDirectory() as tmp:
            for path in SOURCES + LANGUAGE:
                subprocess.run([tool, "e", "-y", "-inul", str(dat), path, tmp + os.sep], timeout=120)
                f = Path(tmp) / path.rsplit("\\", 1)[1]
                if f.is_file():
                    files[path] = f.read_text(encoding="latin-1")
                    f.unlink()
    items: dict[str, dict[str, Any]] = {}
    for path in SOURCES:
        items.update(parse_items(files.get(path, "")))
    names: dict[str, str] = {}
    for path in LANGUAGE:
        for k, v in parse_names(files.get(path, "")).items():
            names.setdefault(k, v)
    if not items:
        raise RuntimeError("no materials or objects found in the game data")
    for name, it in items.items():
        if name.lower() in names:
            it["display"] = names[name.lower()]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(items, indent=1, sort_keys=True), encoding="utf-8")
    return items


def load(cache: Path = CACHE, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Cached catalogue, extracting it from the game the first time. Empty when the game data is unavailable."""
    if cache.is_file() and not refresh:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    try:
        return extract(cache=cache)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return {}


BUILDABLE = ("floor", "wall", "object")


def search(items: dict[str, dict[str, Any]], words: list[str], kinds: tuple[str, ...] = BUILDABLE
           ) -> list[tuple[str, dict[str, Any]]]:
    """Items whose internal or display name contains every word (case-insensitive), best matches first."""
    ws = [w.lower() for w in words if w]
    hits = []
    for name, it in items.items():
        if it["kind"] not in kinds:
            continue
        hay = (name + " " + it.get("display", "") + " " + it.get("filter", "")).lower()
        if all(w in hay for w in ws):
            exact = any(w in (name.lower(), it.get("display", "").lower()) for w in [" ".join(ws)])
            hits.append((0 if exact else 1, len(name), name, it))
    hits.sort(key=lambda h: (h[0], h[1], h[2]))
    return [(n, it) for _, _, n, it in hits]


def describe(name: str, it: dict[str, Any]) -> str:
    bits = [it["kind"] + (f" {it['size'][0]}x{it['size'][1]}" if it.get("size") else "")]
    if it.get("cost"):
        bits.append(f"${it['cost']:,}")
    if it.get("research"):
        bits.append(f"research {it['research']}")
    if it.get("power"):
        bits.append("needs power")
    if it.get("water"):
        bits.append("needs water")
    if it.get("on_wall"):
        bits.append("goes on a wall")
    if it.get("dlc"):
        bits.append(f"DLC {it['dlc']}")
    shown = it.get("display")
    return f"{name}" + (f" \"{shown}\"" if shown and shown.replace(" ", "").lower() != name.lower() else "") + \
        " - " + ", ".join(bits)
