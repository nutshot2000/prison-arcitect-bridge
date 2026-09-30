"""Situation report and utility maps from a parsed .prison save.

Everything here reads the save tree only (no game access), so it is testable
offline. The bridge writes a fresh save on demand (Easy.snapshot) and passes the
root Section here.

Save facts used (measured on build r11056, 29 Sep 2026):
- Cells: section "x y" with Mat, Ind (indoors), Room.i.
- Objects: Type, Pos.x/y, Damage (staff/prisoner injury, ~1 = down), Powered, On,
  Demand/Capacity (PowerStation), Cell.i (prisoner's assigned room id),
  Needs/Needs/[i] with Type + Charge (0..100, 100 = desperate), Needs.ComplainNeedId.
- Electricity: sections "x y level" = a cable (or electrical object) on that cell.
- Water: sections "x y" with PipeType 1 (large) / 2 (small).
- StatsTracker/Today and /Persistent: EscapedPrisoners, EntityDeath, NumIncidents...
- Misconduct/MisconductReports/.../MisconductEntries: Type (Murder, SeriousInjury...).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .prison_save import Section

STAFF = {"Workman", "Guard", "ArmedGuard", "DogHandler", "Cook", "Doctor", "Janitor", "Gardener", "Psychologist",
         "Accountant", "Chief", "Foreman", "Warden", "Lawyer", "Teacher", "Chaplain", "Sniper"}
# needs that point at a missing thing
NEED_FIX = {"Hygiene": "showers (need WATER): `room shower`", "Bladder": "toilets (need WATER): `hookup water`",
            "Bowels": "toilets (need WATER): `hookup water`",
            "Food": "kitchen + canteen + cooks (cookers need POWER)", "Sleep": "cells with beds",
            "Exercise": "a yard with weights", "Recreation": "`room commonroom` (TV, pool, phone) and FreeTime",
            "Freedom": "FreeTime/Yard hours in the `regime`", "Safety": "more guards",
            "Clothing": "a laundry (`unlock laundry`)", "Family": "`room visitation`", "Comfort": "better cells",
            "Spirituality": "`room chapel` (10x10 with walls)", "Literacy": "a library (`unlock library`)",
            "Environment": "Janitors to clean (`unlock janitor`)", "Privacy": "single cells instead of dormitories",
            "Alcohol": "nothing legal supplies it: cut smuggling (`unlock metaldetector`) and wait it out",
            "Drugs": "nothing legal supplies it: cut smuggling (`unlock metaldetector`); Psychologist later",
            "Luxuries": "a shop (`unlock shop`)"}


def _true(v: Any) -> bool:
    """Save values are text: 'true' / 'false' (the parser's get() does not convert them)."""
    return v is True or str(v).strip().lower() == "true"


def _station_on(o: Section) -> bool:
    # the player's switch is saved only when off ("Switch false"); On mirrors it while powered
    return not (str(o.get("Switch", "true")).strip().lower() == "false")


def _cells(root: Section) -> dict[tuple[int, int], dict]:
    out = {}
    sec = root.section("Cells")
    for c in sec.sections() if sec else []:
        try:
            x, y = (int(v) for v in c.name.split()[:2])
        except ValueError:
            continue
        out[(x, y)] = c.to_dict()
    return out


def _room_types(root: Section) -> dict[int, str]:
    sec = root.section("Rooms")
    types = {}
    for r in sec.items_indexed() if sec else []:
        try:
            types[int(r.get("Id.i"))] = str(r.get("RoomType"))
        except (TypeError, ValueError):
            pass
    return types


def _objects(root: Section) -> list[Section]:
    sec = root.section("Objects")
    return sec.items_indexed() if sec else []


def _pos(o: Section) -> tuple[int, int] | None:
    x, y = o.num("Pos.x"), o.num("Pos.y")
    if x is None or y is None:
        return None
    return int(x), int(y)


def situation(root: Section) -> dict[str, Any]:
    cells = _cells(root)
    rtypes = _room_types(root)
    objs = _objects(root)

    def where(p):
        if p is None:
            return "unknown"
        c = cells.get(p, {})
        rid = c.get("Room.i")
        if isinstance(rid, (int, float)) and rid >= 0:
            return rtypes.get(int(rid), "room")
        return "indoors" if _true(c.get("Ind")) else "outside"

    prisoners = [o for o in objs if o.get("Type") == "Prisoner"]
    pris_where = Counter(where(_pos(o)) for o in prisoners)
    no_cell = sum(1 for o in prisoners if (o.num("Cell.i", -1) or -1) < 0)
    complain = Counter()
    need_sum: dict[str, list[float]] = defaultdict(list)
    for o in prisoners:
        needs = o.section("Needs")
        inner = needs.section("Needs") if needs else None
        ids = {}
        for n in inner.sections() if inner else []:
            t = n.get("Type")
            ch = n.num("Charge")
            if isinstance(t, str) and ch is not None:
                need_sum[t].append(ch)
            ids[n.get("id.i")] = t
        if needs and needs.get("ComplainNeedId.i") is not None:
            complain[ids.get(needs.get("ComplainNeedId.i"), "?")] += 1
    worst = sorted(((sum(v) / len(v), k) for k, v in need_sum.items() if v), reverse=True)
    hungry = sum(1 for v in need_sum.get("Food", []) if v >= 80)
    tired_staff = sum(1 for o in objs if o.get("Type") in STAFF and o.num("Energy") is not None and o.num("Energy") < 15)

    staff = Counter()
    hurt, down = Counter(), Counter()
    for o in objs:
        t = o.get("Type")
        if t in STAFF:
            staff[t] += 1
            dmg = o.num("Damage", 0.0) or 0.0
            if dmg >= 0.95:
                down[t] += 1
            elif dmg >= 0.4:
                hurt[t] += 1

    stations = [{"at": _pos(o), "on": _station_on(o), "overloaded": o.num("Overloaded", 0), "demand": o.num("Demand", 0), "capacity": o.num("Capacity", 0)}
                for o in objs if o.get("Type") == "PowerStation"]
    pumps = [{"at": _pos(o), "powered": _true(o.get("Powered"))} for o in objs if o.get("Type") == "WaterPumpStation"]
    unpowered = Counter(o.get("Type") for o in objs
                        if o.get("Type") in ("Cooker", "Fridge", "Light", "Tv", "WaterPumpStation", "Capacitor")
                        and not _true(o.get("Powered")) and not _true(o.get("ExternalPower")))

    stats = root.section("StatsTracker")
    today = stats.section("Today").to_dict() if stats and stats.section("Today") else {}
    total = stats.section("Persistent").to_dict() if stats and stats.section("Persistent") else {}
    mis = Counter()
    msec = root.section("Misconduct")
    reports = msec.section("MisconductReports") if msec else None
    for rep in reports.sections() if reports else []:
        entries = rep.section("MisconductEntries")
        for e in entries.sections() if entries else []:
            mis[str(e.get("Type"))] += 1

    rooms = root.section("Rooms")
    failing = [str(r.get("RoomType")) for r in rooms.items_indexed()
               if str(r.get("RequirementsFailed")).lower() == "true"] if rooms else []

    return {
        "prisoners": len(prisoners), "prisoners_where": dict(pris_where), "prisoners_without_cell": no_cell,
        "complaining_about": dict(complain.most_common(6)),
        "hungry": hungry,
        "tired_staff": tired_staff,
        "worst_needs": [(k, round(v)) for v, k in worst[:5]],
        "staff": dict(staff), "staff_hurt": dict(hurt), "staff_down": dict(down),
        "power_stations": stations, "pumps": pumps, "unpowered": dict(unpowered),
        "today": today, "total": total, "misconduct": dict(mis.most_common(8)),
        "rooms_failing": failing,
        "balance": root.num("Balance"),
        "temperature": (root.section("Thermometer").num("Temperature") if root.section("Thermometer") else None),
        "todo": todo(root),
        "room_problems": room_problems(root),
        "money": money(root),
        "pending": pending_work(root),
    }


def situation_text(s: dict[str, Any]) -> str:
    def fmt(d):
        return ", ".join(f"{k} {int(v) if isinstance(v, float) else v}" for k, v in d.items()) or "none"

    lines = [f"PRISONERS {s['prisoners']}: where {fmt(s['prisoners_where'])}; without a cell {s['prisoners_without_cell']}"]
    if s["complaining_about"]:
        lines.append(f"  complaining about: {fmt(s['complaining_about'])}")
    if s.get("hungry"):
        lines.append(f"  hungry (Food need 80+): {s['hungry']} of {s['prisoners']}")
    if s["worst_needs"]:
        lines.append("  worst needs (avg 0-100, high = bad): " + ", ".join(f"{k} {v}" for k, v in s["worst_needs"]))
    lines.append(f"STAFF {fmt(s['staff'])}")
    if s["staff_hurt"] or s["staff_down"]:
        lines.append(f"  injured: {fmt(s['staff_hurt'])}; DOWN (unconscious/dying): {fmt(s['staff_down'])}")
    st = s["power_stations"]
    lines.append("POWER " + ("; ".join(f"station {p['at']} {'ON' if p['on'] else 'OFF'} {p['demand']:g}/{p['capacity']:g}"
                                       for p in st) or "no station"))
    lines.append("WATER " + ("; ".join(f"pump {p['at']} {'powered' if p['powered'] else 'NO POWER -> no water'}"
                                       for p in s["pumps"]) or "no pump"))
    if s["unpowered"]:
        lines.append(f"  without power: {fmt(s['unpowered'])}")
    t, tot = s["today"], s["total"]
    lines.append(f"TODAY escaped {int(t.get('EscapedPrisoners', 0))}, deaths {int(t.get('EntityDeath', 0))}, "
                 f"incidents {int(t.get('NumIncidents', 0))}, profit ${int(t.get('Profit', 0)):,}")
    lines.append(f"TOTAL escaped {int(tot.get('TotalEscapedPrisoners', 0))}, deaths {int(tot.get('TotalDeaths', 0))}, "
                 f"incidents {int(tot.get('TotalIncidents', 0))}")
    if s["misconduct"]:
        lines.append(f"MISCONDUCT {fmt(s['misconduct'])}")
    if s["rooms_failing"]:
        lines.append(f"ROOMS MISSING SOMETHING: {', '.join(s['rooms_failing'])}")
    if s.get("todo"):
        lines.append("GAME TO-DO: " + " | ".join(s["todo"]))
    if s.get("money"):
        lines.append("MONEY " + s["money"])
    for prob in (s.get("room_problems") or [])[:6]:
        lines.append("ROOM PROBLEM: " + prob)
    pend = s.get("pending") or {}
    if pend.get("construction_jobs") or pend.get("work_queue"):
        wq = ", ".join(f"{k} {v}" for k, v in (pend.get("work_queue") or {}).items())
        lines.append(f"WORK WAITING: {pend.get('construction_jobs', 0)} construction jobs; {wq or 'no other jobs'}")
    # plain-language diagnosis
    advice = []
    if any(not p["powered"] for p in s["pumps"]) or not s["pumps"]:
        advice.append("No water: fix power to the pump first (`power`, `utilmap`).")
    if any(not p["on"] for p in st):
        advice.append("A power station is OFF (tripped): max 50 per station, stations must not touch; split "
                      "grids with a PowerSwitch, then `power on`.")
    if s["prisoners_where"].get("outside", 0) > max(3, s["prisoners"] // 4):
        advice.append("Many prisoners are outside rooms: build a perimeter `fence`, more cells, more guards.")
    if s["staff_down"]:
        advice.append("Staff are down: hire more guards and a Doctor (Health research) before more intake.")
    temp = s.get("temperature")
    if temp is not None and temp >= 80:
        advice.append(f"Prison temperature {temp:.0f}/100 = riot risk: more guards, fix the worst needs, "
                      "a Solitary room for the punishment queue.")
    for need, _ in s["worst_needs"][:2]:
        if need in NEED_FIX:
            advice.append(f"{need} is the worst need: {NEED_FIX[need]}.")
    if advice:
        lines.append("DO NEXT: " + " ".join(advice))
    return "\n".join(lines)


INTAKE_MODES = {0: "none", 1: "fill to capacity (beds)", 2: "up to a maximum total", 3: "a number per day",
                4: "all available"}

# Room requirements as the game defines them (materials.txt "BEGIN Room" blocks): minimum size,
# indoor/enclosed, and the objects that must be inside (any one of each group).
ROOM_REQS: dict[str, dict] = {
    "Cell": {"min": (2, 3), "indoor": True, "objects": [("Bed", "Mattress", "ComfyBed", "BunkBed"), ("Toilet",)]},
    "HoldingCell": {"min": (5, 5), "indoor": True, "objects": [("Toilet",), ("Bench", "SmallBench")]},
    "Dormitory": {"min": (2, 3), "indoor": True, "objects": [("Bed", "BunkBed", "Mattress", "ComfyBed"), ("Toilet",)]},
    "Kitchen": {"objects": [("Cooker",), ("Fridge", "TallFridge"), ("Sink",)]},
    "Shower": {"objects": [("ShowerHead",)]},
    "Yard": {"min": (5, 5), "secure": True},   # "Secure (behind at least one door)" in the game's tooltip
    "Deliveries": {"min": (1, 3)},
    "Garbage": {"min": (1, 3)},
    "Office": {"min": (4, 4), "indoor": True,
               "objects": [("OfficeDesk", "FancyDesk"), ("Chair", "OfficeChair", "SwivelChair"), ("FilingCabinet",)]},
    "Security": {"min": (4, 4), "objects": [("OfficeDesk", "FancyDesk"), ("Chair", "OfficeChair"), ("FilingCabinet",)]},
    "MedicalWard": {"indoor": True, "objects": [("MedicalBed",)]},
    "Visitation": {"indoor": True, "objects": [("VisitorTable", "VisitorTableSecure")]},
    "Staffroom": {"min": (4, 4), "indoor": True,
                  "objects": [("SofaChairDouble", "SofaChairSingle", "WoodenStool", "MetalStool"), ("DrinkMachine",)]},
    "Laundry": {"indoor": True, "objects": [("LaundryMachine",), ("LaundryBasket",), ("IroningBoard",)]},
    "Workshop": {"min": (5, 5), "objects": [("WorkshopSaw",), ("WorkshopPress",), ("Table",)]},
    "CleaningCupboard": {"min": (3, 3), "indoor": True},
    "Library": {"min": (5, 5), "indoor": True, "objects": [("LibraryBookshelf",), ("SortingTable",)]},
    "Classroom": {"min": (5, 5), "objects": [("SchoolDesk",), ("OfficeDesk",)]},
    "Chapel": {"min": (6, 6), "indoor": True, "objects": [("Altar",), ("Pews",), ("PrayerMat",)]},
    "ParoleRoom": {"min": (5, 5), "indoor": True, "objects": [("VisitorTable",)]},
    "CommonRoom": {"indoor": True},
}


# The game's To-do items -> the easy verb that clears them (checked against the live panel).
def todo_action(item: str, rooms: dict[str, int]) -> str:
    low = item.lower()
    if low.startswith("prisoner intake"):
        return "`intake beds` keeps arrivals to free beds" if "beds" not in low else ""
    if "parole" in low:
        return ("parole hearings need a Parole room: `room parole x1 y1 x2 y2` (7x7 with walls)"
                if not rooms.get("ParoleRoom") else "hearings run in the parole room; nothing to do")
    if "exhausted" in low:
        return "`room staffroom x1 y1 x2 y2` (8x7) (sofa + DrinkMachine), or another if one exists"
    if "visitors" in low or "families" in low:
        return "`room visitation x1 y1 x2 y2` (more tables = more visits)"
    if "solitary" in low:
        return "`solitary x y 6`"
    if "lockdown" in low:
        return "resolves itself once a lockdown/solitary slot is free"
    if "injured" in low or "medical" in low:
        return ("`hire Doctor 2`" if rooms.get("MedicalWard") else "`unlock doctor`, then `room infirmary x1 y1 x2 y2`")
    if "temperature" in low:
        return "" if "calm" in low else "more guards (`auto`), fix the worst needs in `report`, `solitary` for the queue"
    if "waste" in low:
        return "Bins: `place Bin x y` in busy rooms"
    if "fire" in low:
        return "`place Sprinkler x y` in kitchens/canteens, then `hookup water`"
    return ""


DOOR_TYPES = {"Door", "JailDoor", "JailDoorLarge", "StaffDoor", "SolitaryDoor", "RemoteDoor", "RoadGate",
              "DoorTimer"}


def _blockers(root: Section) -> tuple[dict, set, int, int]:
    """Cells that stop walking: walls/fences, and cells holding a door (RoadGate covers 7)."""
    cells = _cells(root)
    doors: set[tuple[int, int]] = set()
    for o in _objects(root):
        t = str(o.get("Type"))
        if t in DOOR_TYPES:
            x, y = o.num("Pos.x"), o.num("Pos.y")
            if x is None or y is None:
                continue
            if t == "RoadGate":
                for dx in range(-3, 4):
                    doors.add((int(x - 0.5) + dx, int(y)))
            else:
                doors.add((int(x), int(y)))
    w = int(root.num("NumCellsX", 0) or 0) or (max(p[0] for p in cells) + 1 if cells else 0)
    h = int(root.num("NumCellsY", 0) or 0) or (max(p[1] for p in cells) + 1 if cells else 0)
    return cells, doors, w, h


def escape_route(root: Section, start: list[tuple[int, int]], cache: dict | None = None):
    """Walk from `start` without crossing walls, fences or doors. Returns the first map-edge cell reached
    (the area is NOT secure; that cell shows where the gap leads out), or None if it is secure."""
    cells, doors, w, h = cache["b"] if cache and "b" in cache else _blockers(root)
    if cache is not None:
        cache["b"] = (cells, doors, w, h)

    def blocked(p):
        m = str(cells.get(p, {}).get("Mat", ""))
        return "Wall" in m or m == "Fence" or p in doors

    seen = set(start)
    todo = list(start)
    while todo:
        x, y = todo.pop()
        if x <= 0 or y <= 0 or x >= w - 1 or y >= h - 1:
            return (x, y)
        for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if q not in seen and not blocked(q):
                seen.add(q)
                todo.append(q)
    return None


def room_problems(root: Section) -> list[str]:
    """Check every room against ROOM_REQS using the save: size, indoor cells and required objects."""
    cells = _cells(root)
    rtypes = _room_types(root)
    members: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for p, c in cells.items():
        rid = c.get("Room.i")
        if isinstance(rid, (int, float)) and rid >= 0:
            members[int(rid)].append(p)
    by_cell: dict[tuple[int, int], set[str]] = defaultdict(set)
    for o in _objects(root):
        p = _pos(o)
        if p:
            by_cell[p].add(str(o.get("Type")))
    out = []
    cache: dict = {}
    for rid, pts in sorted(members.items()):
        rtype = rtypes.get(rid, "?")
        req = ROOM_REQS.get(rtype)
        if not req:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        where = f"{rtype} at {min(xs)},{min(ys)}-{max(xs)},{max(ys)}"
        issues = []
        if "min" in req:
            mw, mh = req["min"]
            if not ((w >= mw and h >= mh) or (w >= mh and h >= mw)):
                issues.append(f"too small ({w}x{h}, needs {mw}x{mh})")
        if req.get("indoor") and not all(_true(cells[p].get("Ind")) for p in pts):
            issues.append("not indoors (needs walls all round; `room` marks rooms indoor)")
        if req.get("secure"):
            exit_cell = escape_route(root, pts, cache)
            if exit_cell:
                issues.append(f"not secure: prisoners can walk out to the map edge near {exit_cell[0]},{exit_cell[1]} "
                              "without passing a door (close the gap with fence/wall, or fence the yard with a door)")
        inside = set().union(*(by_cell.get(p, set()) for p in pts)) if pts else set()
        for group in req.get("objects", []):
            if not inside.intersection(group):
                issues.append(f"missing {group[0]}")
        if issues:
            out.append(f"{where}: " + "; ".join(issues))
    return out


def pending_work(root: Section) -> dict[str, Any]:
    """What workmen still have to do, from the save's work queue (survives reloads, unlike script memory)."""
    jobs: Counter = Counter()
    cons = root.section("Construction")
    cj = cons.section("Jobs") if cons else None
    construction = len(list(cj.sections())) if cj else 0
    wq = root.section("WorkQ")
    items = wq.section("Items") if wq else None
    for it in items.sections() if items else []:
        t = str(it.get("Type"))
        what = it.get("ObjType") or it.get("MatType")
        jobs[f"{t} {what}" if what not in (None, "") else t] += 1
    construct = [(int(it.num("CellX")), int(it.num("CellY"))) for it in (items.sections() if items else [])
                 if str(it.get("Type")) == "Construct" and it.num("CellX") is not None and it.num("CellY") is not None]
    return {"construction_jobs": construction + len(construct), "work_queue": dict(jobs.most_common(12)),
            "unreachable": unreachable_jobs(root, construct)}


def _areas(points: list[tuple[int, int]]) -> list[dict]:
    """Group cells into touching areas (8-neighbour) with a bounding box, biggest first."""
    left, out = set(points), []
    while left:
        seed = left.pop()
        group, todo = [seed], [seed]
        while todo:
            x, y = todo.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in left:
                        left.remove(q); group.append(q); todo.append(q)
        xs, ys = [g[0] for g in group], [g[1] for g in group]
        out.append({"cells": len(group), "x1": min(xs), "y1": min(ys), "x2": max(xs), "y2": max(ys)})
    return sorted(out, key=lambda a: -a["cells"])


def unreachable_jobs(root: Section, jobs: list[tuple[int, int]]) -> list[dict]:
    """Construction jobs no Workman can walk to (live: rooms ordered outside the old fence line sat unbuilt).
    Staff open doors, so only walls and fences block them."""
    if not jobs:
        return []
    cells = _cells(root)
    w = int(root.num("NumCellsX", 0) or 0) or (max(p[0] for p in cells) + 1 if cells else 0)
    h = int(root.num("NumCellsY", 0) or 0) or (max(p[1] for p in cells) + 1 if cells else 0)
    start = [p for p in (_pos(o) for o in _objects(root) if o.get("Type") == "Workman") if p]
    if not start or not w or not h:
        return []

    def blocked(p):
        m = str(cells.get(p, {}).get("Mat", ""))
        return "Wall" in m or m == "Fence"

    seen, todo = set(start), list(start)
    while todo:
        x, y = todo.pop()
        for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if q not in seen and 0 <= q[0] < w and 0 <= q[1] < h and not blocked(q):
                seen.add(q); todo.append(q)
    bad = [j for j in jobs if not any(q in seen for q in (j, (j[0] + 1, j[1]), (j[0] - 1, j[1]),
                                                           (j[0], j[1] + 1), (j[0], j[1] - 1)))]
    return _areas(bad)


def verify_orders(root: Section, ordered: list[dict], now: float) -> dict[str, Any]:
    """Ordered objects (from the script) vs what exists in the save.

    installed: an object of that type within 2 cells of the order; queued: an install job for it is in the
    work queue; failed: neither, and ordered more than 6 game hours ago (the game drops blocked orders silently).
    """
    have: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for o in _objects(root):
        x, y = o.num("Pos.x"), o.num("Pos.y")
        if x is not None and y is not None:
            have[str(o.get("Type"))].append((x, y))
    wq = root.section("WorkQ")
    items = wq.section("Items") if wq else None
    queued_types = Counter(str(it.get("ObjType")) for it in (items.sections() if items else []) if it.get("ObjType"))
    result = {"installed": 0, "waiting": 0, "failed": []}
    for od in ordered:
        t, x, y = od["type"], od["x"], od["y"]
        # an object ordered at x covers x..x+w-1 (Pos = its centre), height-2 objects cover y-1..y:
        # match only an object whose centre lies on that footprint, not a neighbour of the same type
        near = any(-0.1 <= px - x <= 3.1 and -1.1 <= py - y <= 1.1 for px, py in have.get(t, []))
        if near:
            result["installed"] += 1
        elif queued_types.get(t) or now - od.get("t", now) < 360:
            result["waiting"] += 1
        else:
            result["failed"].append(f"{t}@{x},{y}")
    return result


def money(root: Section) -> str:
    stats = root.section("StatsTracker")
    today = stats.section("Today") if stats else None
    hist = stats.section("History") if stats else None
    funds = hist.section("Funds") if hist else None
    days = [(int(d.num("Day", 0) or 0), d.num("Value", 0) or 0) for d in (funds.sections() if funds else [])]
    parts = [f"balance ${int(root.num('Balance') or 0):,}"]
    if today is not None and today.num("Profit") is not None:
        parts.append(f"profit today ${int(today.num('Profit')):,}")
    if len(days) >= 2:
        (d1, v1), (d2, v2) = days[-2], days[-1]
        parts.append(f"day {d1} -> day {d2}: ${int(v2 - v1):+,}")
    return ", ".join(parts)


def todo(root: Section) -> list[str]:
    """The game's To-do panel, rebuilt from the save (the panel itself is not readable by scripts)."""
    out: list[str] = []
    intake = root.section("Intake")
    if intake:
        t = int(intake.num("IntakeType", -1) or -1)
        out.append(f"Prisoner intake: {INTAKE_MODES.get(t, t)}")
    objs = _objects(root)
    rooms = Counter(_room_types(root).values())

    def hint(room: str, missing: str, present: str) -> str:
        return present.format(n=rooms[room]) if rooms.get(room) else missing
    # calibrated against the game's panel (29 Sep 2026): up for parole = served past the parole point
    frac = {"Quarter": 0.25, "Half": 0.5, "ThreeQuarters": 0.75}
    parole = 0
    for o in objs:
        bio = o.section("Bio") if o.get("Type") == "Prisoner" else None
        if bio and str(bio.get("NextParole", "")) in frac:
            if (bio.num("Served", 0) or 0) >= frac[str(bio.get("NextParole"))] * (bio.num("SentenceF", 0) or 0):
                parole += 1
    if parole:
        out.append(f"Prisoners up for parole: {parole}")
    tired = sum(1 for o in objs if o.get("Type") in STAFF and o.num("Energy") is not None and o.num("Energy") < 15)
    if tired:
        out.append(f"Staff exhausted: {tired} " + hint("Staffroom", "(build a Staffroom so they can rest)",
                                                      "(resting in the staff room; it needs a sofa AND a DrinkMachine)"))
    vis = root.section("Visitation")
    if vis and (vis.num("Waiting", 0) or 0) > 0:
        out.append(f"Visitors: {int(vis.num('Waiting'))} families waiting to visit " +
                   hint("Visitation", "(build `room visitation`)", "({n} visitation room(s); more tables = more visits)"))
    solitary = lockdown = 0
    msec = root.section("Misconduct")
    reports = msec.section("MisconductReports") if msec else None
    for rep in reports.sections() if reports else []:
        cur = int(rep.num("CurrentPunishment", 0) or 0)
        if (rep.num("Punishment_Solitary", 0) or 0) > 0 and cur == 0:
            solitary += 1
        if (rep.num("Punishment_Lockdown", 0) or 0) > 0 and cur == 0:
            lockdown += 1
    if solitary:
        out.append(f"Incidents: {solitary} awaiting Solitary Confinement " +
                   hint("Solitary", "(build `solitary x y 6`)", "({n} solitary cells; add more if the queue stays long)"))
    if lockdown:
        out.append(f"Incidents: {lockdown} awaiting Lockdown")
    medical = sum(1 for o in objs if (o.num("Damage", 0) or 0) >= 0.1)  # matches the panel
    if medical:
        out.append(f"Medical: {medical} people injured (Doctors + infirmary treat them)")
    th = root.section("Thermometer")
    if th:
        temp = th.num("Temperature", 0) or 0
        level = "RIOT RISK" if temp >= 80 else "tense" if temp >= 50 else "calm"
        out.append(f"Prison temperature {temp:.0f}/100 ({level}): {int(th.num('UnhappyPrisoners', 0) or 0)} unhappy, "
                   f"{int(th.num('LockedUpPrisoners', 0) or 0)} locked up")
    return out


def utility_map(root: Section, x1: int, y1: int, x2: int, y2: int, kind: str = "both") -> str:
    """ASCII map: walls/floors faint, stations and utilities on top.

    power: P station (on) p station (OFF), C capacitor, - cable, * powered object, ! unpowered object
    water: W pump (powered) w pump (no power), L large pipe, s small pipe, T fixture on a pipe, t fixture not on a pipe
    """
    cells = _cells(root)
    elec: set[tuple[int, int]] = set()
    esec = root.section("Electricity")
    for c in esec.sections() if esec else []:
        try:
            x, y = (int(v) for v in c.name.split()[:2])
            elec.add((x, y))
        except ValueError:
            pass
    pipes: dict[tuple[int, int], int] = {}
    wsec = root.section("Water")
    for c in wsec.sections() if wsec else []:
        try:
            x, y = (int(v) for v in c.name.split()[:2])
        except ValueError:
            continue
        pt = c.num("PipeType")  # get() returns the save's text ("1"); num() converts
        if pt is not None:
            pipes[(x, y)] = int(pt)
    grid: dict[tuple[int, int], str] = {}
    for (x, y), c in cells.items():
        m = str(c.get("Mat", ""))
        if "Wall" in m or m == "Fence":
            grid[(x, y)] = "#"
        elif _true(c.get("Ind")):
            grid[(x, y)] = ":"
    if kind in ("power", "both"):
        for p in elec:
            grid[p] = "-"
    if kind in ("water", "both"):
        for p, t in pipes.items():
            grid[p] = "L" if t == 1 else "s"
    power_users = {"Cooker", "Fridge", "Tv", "Light", "CctvMonitor", "LaundryMachine"}
    water_users = {"Toilet", "ShowerHead", "Sink", "Drain", "LaundryMachine", "Sprinkler"}
    for o in _objects(root):
        t, p = o.get("Type"), _pos(o)
        if p is None:
            continue
        if t in ("PowerStation", "WaterPumpStation"):
            on = _station_on(o) if t == "PowerStation" else _true(o.get("Powered"))
            ch = ("P" if on else "p") if t == "PowerStation" else ("W" if on else "w")
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    grid[(p[0] + dx, p[1] + dy)] = ch
        elif t == "Capacitor" and kind in ("power", "both"):
            grid[p] = "C"
        elif t in power_users and kind in ("power", "both") and t != "Light":
            grid[p] = "*" if _true(o.get("Powered")) else "!"
        elif t in water_users and kind in ("water", "both"):
            grid[p] = "T" if p in pipes else "t"
    ruler = "".join(str(x % 10) for x in range(x1, x2 + 1))
    rows = [f"     {ruler}"] + [f"{y:4} " + "".join(grid.get((x, y), ".") for x in range(x1, x2 + 1))
                                  for y in range(y1, y2 + 1)]
    legend = ("P/p power station on/OFF, C capacitor, - cable, * powered, ! NOT powered; "
              "W/w pump powered/NO POWER, L large pipe, s small pipe, T fixture on pipe, t fixture NOT on pipe; "
              "# wall/fence, : indoor floor")
    return "\n".join([f"utilities x {x1}..{x2}, y {y1}..{y2}", *rows, legend])


def built_area(root: Section, margin: int = 2) -> tuple[int, int, int, int]:
    """Bounding box of walls, utilities and stations (the part of the map worth drawing)."""
    pts = [p for p, c in _cells(root).items() if "Wall" in str(c.get("Mat", "")) or _true(c.get("Ind"))]
    for name in ("Electricity", "Water"):
        sec = root.section(name)
        for c in sec.sections() if sec else []:
            try:
                pts.append(tuple(int(v) for v in c.name.split()[:2]))
            except ValueError:
                pass
    if not pts:
        return 0, 0, 40, 30
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(0, min(xs) - margin), max(0, min(ys) - margin), max(xs) + margin, max(ys) + margin
