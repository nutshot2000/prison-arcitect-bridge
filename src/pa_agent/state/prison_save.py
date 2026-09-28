"""Parser for Prison Architect ``.prison`` save files.

The format is whitespace-separated tokens. ``BEGIN <name> ... END`` opens a
section (possibly on one line); inside, tokens alternate key / value. Names and
values may be double-quoted and contain spaces. Keys can repeat.

The parser keeps hierarchy, order and repeated keys, and leaves values as
strings; use :func:`typed` or :meth:`Section.num` for conversion. Unknown
content is preserved, never dropped.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Union

_TOKEN = re.compile(r'"([^"]*)"|(\S+)')

Value = Union[str, "Section"]


class SaveFormatError(ValueError):
    pass


@dataclass
class Section:
    name: str
    entries: list[tuple[str, Value]] = field(default_factory=list)

    # ---- access -------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.entries:
            if k == key:
                return v
        return default

    def get_all(self, key: str) -> list[Value]:
        return [v for k, v in self.entries if k == key]

    def section(self, key: str) -> "Section | None":
        v = self.get(key)
        return v if isinstance(v, Section) else None

    def sections(self) -> Iterator["Section"]:
        for _, v in self.entries:
            if isinstance(v, Section):
                yield v

    def items_indexed(self) -> list["Section"]:
        """Children named ``[i N]`` (the game's array encoding), in order."""
        return [v for k, v in self.entries if isinstance(v, Section) and k.startswith("[i ")]

    def num(self, key: str, default: float | None = None) -> float | None:
        v = self.get(key)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return default
        return default

    def __contains__(self, key: str) -> bool:
        return any(k == key for k, _ in self.entries)

    # ---- export -------------------------------------------------------
    def to_dict(self, convert: bool = True) -> dict:
        """Nested dict. Repeated keys become lists; values typed if ``convert``."""
        out: dict[str, Any] = {}
        for k, v in self.entries:
            val = v.to_dict(convert) if isinstance(v, Section) else (typed(v) if convert else v)
            if k in out:
                if not isinstance(out[k], list) or not getattr(out[k], "_multi", False):
                    lst = _Multi([out[k]])
                    out[k] = lst
                out[k].append(val)
            else:
                out[k] = val
        return out


class _Multi(list):
    _multi = True


def typed(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _tokens(text: str) -> Iterator[str]:
    for m in _TOKEN.finditer(text):
        yield m.group(1) if m.group(1) is not None else m.group(2)


def parse_prison(text: str) -> Section:
    root = Section("<root>")
    stack = [root]
    it = _tokens(text)
    for tok in it:
        if tok == "BEGIN":
            name = next(it, None)
            if name is None:
                raise SaveFormatError("BEGIN without a name at end of file")
            sec = Section(name)
            stack[-1].entries.append((name, sec))
            stack.append(sec)
        elif tok == "END":
            if len(stack) == 1:
                raise SaveFormatError("unbalanced END")
            stack.pop()
        else:
            val = next(it, None)
            if val is None:
                raise SaveFormatError(f"key {tok!r} has no value at end of file")
            if val in ("BEGIN", "END"):
                raise SaveFormatError(f"key {tok!r} in section {stack[-1].name!r} is followed by {val}")
            stack[-1].entries.append((tok, val))
    if len(stack) != 1:
        raise SaveFormatError(f"unterminated section {stack[-1].name!r}")
    return root


@dataclass
class LoadedSave:
    path: Path
    root: Section
    size: int
    mtime: float
    sha256: str


def load_prison(path: str | Path) -> LoadedSave:
    p = Path(path)
    data = p.read_bytes()
    st = p.stat()
    # Saves are mostly ASCII but can contain stray non-UTF-8 bytes (names).
    text = data.decode("utf-8", errors="replace")
    return LoadedSave(p, parse_prison(text), len(data), st.st_mtime, hashlib.sha256(data).hexdigest())


STAFF_TYPES = {"Guard", "ArmedGuard", "DogHandler", "Workman", "Cook", "Doctor", "Janitor", "Gardener",
               "Psychologist", "Accountant", "Chief", "Foreman", "Warden", "Lawyer", "Teacher",
               "Chaplain", "Sniper", "Paramedic", "Fireman", "RiotGuard", "Soldier", "SpiritualLeader",
               "Security", "Clerk"}


def summarize(root: Section) -> dict:
    """Compact, agent-friendly overview. Everything else stays in the full tree."""
    objects = root.section("Objects")
    counts: Counter[str] = Counter()
    prisoners = []
    if objects:
        for o in objects.items_indexed():
            t = o.get("Type")
            if isinstance(t, str):
                counts[t] += 1
            if t == "Prisoner":
                bio = o.section("Bio")
                prisoners.append({
                    "id": typed(o.get("Id.u", "")) if o.get("Id.u") else None,
                    "name": " ".join(x for x in (bio.get("Forname"), bio.get("Surname")) if isinstance(x, str)) if bio else None,
                    "category": o.get("Category"),
                    "x": o.num("Pos.x"), "y": o.num("Pos.y"),
                })
    rooms = root.section("Rooms")
    room_types = Counter(r.get("RoomType") for r in rooms.items_indexed()) if rooms else Counter()
    finance = root.section("Finance")
    research = root.section("Research")
    researched = []
    in_progress = {}
    if research:
        for s in research.sections():
            prog = s.num("Progress", 0.0) or 0.0
            if prog >= 1.0:
                researched.append(s.name)
            elif prog > 0:
                in_progress[s.name] = prog
    return {
        "version": root.get("Version"),
        "map": {"w": typed(root.get("NumCellsX", "0")), "h": typed(root.get("NumCellsY", "0"))},
        "time_index": root.num("TimeIndex"),
        "seconds_played": root.num("SecondsPlayed"),
        "balance": root.num("Balance"),
        "finance": {k: typed(v) for k, v in finance.entries if isinstance(v, str) and not k.startswith("PrisonerWageRate")} if finance else None,
        "prisoner_count": counts.get("Prisoner", 0),
        "staff": {t: n for t, n in counts.items() if t in STAFF_TYPES},
        "rooms": dict(room_types),
        "research_done": researched,
        "research_in_progress": in_progress,
        "object_counts": dict(counts.most_common()),
        "prisoners_sample": prisoners[:10],
        "top_level_sections": [s.name for s in root.sections()],
    }
