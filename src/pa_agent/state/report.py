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
NEED_FIX = {"Hygiene": "showers (need WATER)", "Bladder": "toilets (need WATER)", "Bowels": "toilets (need WATER)",
            "Food": "kitchen + canteen + cooks (cookers need POWER)", "Sleep": "cells with beds",
            "Exercise": "a yard with weights", "Recreation": "a yard / TV / phone", "Freedom": "free time in the regime",
            "Safety": "more guards", "Clothing": "a laundry", "Family": "visitation", "Comfort": "better cells"}


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
        "worst_needs": [(k, round(v)) for v, k in worst[:5]],
        "staff": dict(staff), "staff_hurt": dict(hurt), "staff_down": dict(down),
        "power_stations": stations, "pumps": pumps, "unpowered": dict(unpowered),
        "today": today, "total": total, "misconduct": dict(mis.most_common(8)),
        "rooms_failing": failing,
        "balance": root.num("Balance"),
    }


def situation_text(s: dict[str, Any]) -> str:
    def fmt(d):
        return ", ".join(f"{k} {int(v) if isinstance(v, float) else v}" for k, v in d.items()) or "none"

    lines = [f"PRISONERS {s['prisoners']}: where {fmt(s['prisoners_where'])}; without a cell {s['prisoners_without_cell']}"]
    if s["complaining_about"]:
        lines.append(f"  complaining about: {fmt(s['complaining_about'])}")
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
    for need, _ in s["worst_needs"][:2]:
        if need in NEED_FIX:
            advice.append(f"{need} is the worst need: {NEED_FIX[need]}.")
    if advice:
        lines.append("DO NEXT: " + " ".join(advice))
    return "\n".join(lines)


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
    water_users = {"Toilet", "ShowerHead", "Sink", "Drain", "LaundryMachine"}
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
