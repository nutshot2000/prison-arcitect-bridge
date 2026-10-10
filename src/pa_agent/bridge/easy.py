"""Easy front end: one verb per call, short plain-text answers, hints on errors.

Used by `pa-agent play <verb>`, `prison.ps1 <verb>` and the pa_* MCP tools, so a
small model only has to read a few lines per step. Everything here goes through
the api.* helpers in the mod's world.lua.
"""
from __future__ import annotations

import re
from collections import Counter
import time
from pathlib import Path
from typing import Any, Callable

from .client import BridgeClient, BridgeError

SNAPSHOT = "pa_agent_snapshot"
RUNS = Path(__file__).resolve().parents[3] / "runs"

# error text -> what to do about it
HINTS: list[tuple[str, str]] = [
    (r"outside the map", "Coordinates are cells: x 0..width-1, y 0..height-1. Run `status` for the map size."),
    (r"needs bridge DLL 0\.3|DLL 0\.3", "Install native/bin/GLU32.dll (scripts/install_bridge.ps1) and restart the game."),
    (r"needs the (\w+) research", "Start it with `research <name>`; it needs a Warden with an Office."),
    (r"is researched by the (\w+)", "Hire that person first (`hire <type>`), build them an `room office`, then retry."),
    (r"costs \$", "Not enough money. `wait` for the daily income, or pick something cheaper."),
    (r"only have one", "That staff type is unique. You already have one."),
    (r"unknown room type|unknown room kind", "Run `help room` for the kinds, or `roomtypes` for every zone type."),
    (r"timed out.*runtime has not connected", "Load a prison with the 'AI Bridge' mod enabled (Extras > Mods)."),
    (r"timed out", "The game did not answer: it may be loading, in the main menu, or closed."),
    (r"Cannot reach the bridge", "Start Prison Architect (with GLU32.dll installed) and load a prison."),
    (r"no free .* area", "Try a smaller size, or `look` for empty ground and give coordinates yourself."),
]


class EasyError(RuntimeError):
    pass


def explain(verb: str, err: str) -> str:
    msg = f"{verb} failed: {err}"
    for pattern, hint in HINTS:
        if re.search(pattern, err, re.IGNORECASE):
            return f"{msg}\n  HINT: {hint}"
    return msg


def _n(v: Any) -> str:
    return f"{int(v):,}" if isinstance(v, (int, float)) else str(v)


def _counts(d: dict | None) -> str:
    if not d:
        return "none"
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items()))


# grant parts (objective name after the grant's) -> what to run; keys are the part's first word, lower case
GRANT_PART_HINT = {"accountant": "`unlock accountant`", "psychologist": "`unlock psychologist`",
                   "offices": "`room office x1 y1 x2 y2` (6x6)", "warden": "`hire Warden`",
                   "doctors": "`unlock doctor`", "ward": "`room infirmary x1 y1 x2 y2`",
                   "foreman": "`unlock foreman`", "chief": "`unlock chief`"}

# Deployment zone values (the save's Zone field; "CanEnterCell: Can't enter Zone<X>" in the game)
DEPLOY_ZONE_MEANING = {"MinSecOnly": "min-sec prisoners only", "MedSecOnly": "normal (med-sec) prisoners only",
                       "MaxSecOnly": "max-sec prisoners only", "ProtectedOnly": "protected prisoners only",
                       "SuperMaxOnly": "supermax prisoners only", "StaffOnly": "no prisoners",
                       "Unlocked": "doors unlocked", "VisitorOnly": "visitors only"}
DEPLOY_ZONE_ONE_CATEGORY = {"MinSecOnly", "MedSecOnly", "MaxSecOnly", "ProtectedOnly", "SuperMaxOnly", "StaffOnly",
                            "VisitorOnly"}
SHARED_ROOMS = {"Yard", "Canteen", "Shower", "CommonRoom", "Library", "Chapel", "Visitation", "MedicalWard",
                "Classroom", "Workshop", "Laundry", "Kitchen"}

READ_ONLY_VERBS = {"help", "status", "next", "report", "look", "space", "rooms", "roomtypes", "todo", "utilmap",
                   "power", "progress", "problems", "money", "screenshot", "unlock", "rules", "patrols", "catalog", "deployment", "logistics"}

# `room` kinds -> the game's room type (keep in step with KIND_ROOM in world.lua)
KIND_ROOM = {"kitchen": "Kitchen", "canteen": "Canteen", "shower": "Shower", "yard": "Yard", "holding": "HoldingCell",
             "cell": "Cell", "office": "Office", "staffroom": "Staffroom", "infirmary": "MedicalWard",
             "deliveries": "Deliveries", "garbage": "Garbage", "storage": "Storage", "dormitory": "Dormitory",
             "visitation": "Visitation", "chapel": "Chapel", "commonroom": "CommonRoom", "parole": "ParoleRoom",
             "laundry": "Laundry", "classroom": "Classroom", "workshop": "Workshop", "library": "Library",
             "cleaning": "CleaningCupboard", "morgue": "Morgue", "kennel": "Kennel", "armoury": "Armoury",
             "security": "Security"}
OUTDOOR_KINDS = {"yard", "deliveries", "garbage"}

# Research worth doing, in order (each line: research, why). Departments work in parallel: the Warden,
# the Foreman (Maintainance) and the Chief (Security) each research one thing at a time.
RESEARCH_LADDER = [
    ("Health", "Doctors treat the injured"),
    ("Maintainance", "a Foreman, who researches Cleaning and PrisonLabour"),
    ("Security", "a Chief, who researches patrols and contraband control"),
    ("Cleaning", "Janitors (clean + run the laundry)"),
    ("PrisonLabour", "laundry (Clothing need), workshop (money), library"),
    ("Contraband", "metal detectors / searches (Drugs, Alcohol, weapons)"),
    ("Patrols", "guard patrols"),
    ("Deployment", "guard deployment"),
    ("Education", "classes (reduce reoffending, grant money)"),
    ("Finance", "an Accountant: grants and bank loans"),
    ("MentalHealth", "a Psychologist"),
    ("AdvancedManagement", "food/laundry logistics"),
    ("Policy", "the policy tab"),
]
DEPARTMENT_HEAD = {"Maintainance": "Foreman", "Security": "Chief", "Finance": "Accountant", "Legal": "Lawyer",
                   "MentalHealth": "Psychologist"}

VERB_HELP = {
    "status": ("status", "Money, clock, paused?, prisoners, beds, staff, rooms you made, construction progress."),
    "look": ("look [x1 y1 x2 y2]",
             "No numbers: small picture of the whole map (1 char = 3x3 cells). With numbers: exact cells.\n"
             "  # wall  _ floor  . ground  = road  , paving  + ordered, not built yet"),
    "space": ("space <w> <h> [near_x near_y]", "Find empty ground for a w x h building (walls included)."),
    "room": ("room <kind> <x1> <y1> <x2> <y2> [door_side]",
             "Build a whole room: walls + floor + door + furniture + zone. The rectangle INCLUDES the walls.\n"
             "  kinds: holding kitchen canteen shower yard office staffroom infirmary dormitory visitation storage\n"
             "         deliveries garbage chapel commonroom parole laundry classroom workshop library cleaning morgue\n"
             "         kennel armoury security\n"
             "  (laundry/workshop/library need PrisonLabour, classroom Education, cleaning Cleaning, kennel Dogs,\n"
             "  armoury Armoury: `unlock <kind>`). The game's own requirements per room: `rules <kind>`.\n"
             "  door_side: north south east west (default south). Yards/deliveries/garbage have no walls.\n"
             "  Sizes that work: holding 9x8, kitchen 9x8, canteen 12x10, shower 7x6, yard 16x12, office 6x6,\n"
             "  chapel 8x8+, commonroom 10x8, parole 7x7, laundry 8x6, classroom 9x9, workshop 9x7, library 9x7."),
    "cells": ("cells <x> <y> <count>",
              "A row of 3x3 cells (bed, toilet, jail door, zoned as Cell) with a 2-cell corridor below.\n"
              "  Takes (count*4+1) x 7 cells starting at x,y."),
    "intake": ("intake [beds|none|max N|perday N|all]",
               "Prisoner intake. `intake beds` = only accept prisoners while there are free beds (use this).\n"
               "  No argument: show the current mode. The default sandbox mode `all` floods the prison."),
    "station": ("station <power|water> <x> <y>",
                "Order a PowerStation or WaterPumpStation (3x3, top-left at x,y). One power station feeds 50;\n"
                "  never place two power stations touching. The water pump needs power."),
    "place": ("place <Object> <x> <y>", "Order one object (PowerSwitch, Bed, Toilet, Light, JailDoor...) at a cell.\n"
                                        "  Any object in `catalog object <words>` (decor, DLC items too)."),
    "floor": ("floor <Material> <x1> <y1> <x2> <y2>",
              "Lay a floor over a rectangle: any floor from `catalog floor <words>` (DarkWoodFloor, MarbleTiles,\n"
              "  RunningTrack...). It replaces the floor that is there."),
    "wall": ("wall <Material> <x1> <y1> <x2> <y2>",
             "A straight line of wall/fence, or the outline of a rectangle: any from `catalog wall <words>`\n"
             "  (BrickWall, GlassWall, BambooFence...). For a whole room use `room`."),
    "fence": ("fence <x1> <y1> <x2> <y2>",
              "Perimeter fence around the whole prison (include deliveries, garbage, power, water).\n"
              "  Where it crosses the road it puts a RoadGate. Without a fence prisoners walk away."),
    "hookup": ("hookup [power|water|both]",
               "Lay cable/pipes from every cooker, fridge, light, pump (power) and toilet, shower, sink (water)\n"
               "  to the nearest station or line. Needs a PowerStation and a WaterPumpStation first."),
    "power": ("power [on]",
              "Power stations (on/off, demand vs capacity 50 each) and whether water pumps have power.\n"
              "  `power on` resets tripped stations. Each station feeds up to 50 on its own grid; stations must not touch."),
    "solitary": ("solitary <x> <y> <count>",
                 "A row of 1x1 solitary cells (SolitaryDoor, zoned Solitary) with a corridor below; (count*2+1) x 5 cells.\n"
                 "  Without them punishments pile up and the prison temperature (riot risk) climbs."),
    "zone": ("zone <RoomType> <x1> <y1> <x2> <y2>", "Zone a rectangle (use the INSIDE of a room). `roomtypes` lists types."),
    "unzone": ("unzone <x1> <y1> <x2> <y2>", "Remove zoning."),
    "roomtypes": ("roomtypes", "Every room type the game knows."),
    "rooms": ("rooms", "Every room in the prison with its type and whether the game says it is missing something."),
    "rules": ("rules [room|refresh]",
              "The game's own requirements for each room type (minimum size, enclosed/indoor, required objects,\n"
              "  research), read from your installed game. `rules kennel` for one; `refresh` re-reads the game."),
    "catalog": ("catalog <words> | catalog floor|wall|object <words> | catalog refresh",
                "Everything you can build (base game + DLC), read from your installed game: the exact name\n"
                "  to use with `place` / `floor` / `wall`, size, cost, research, power/water. `catalog wood floor`,\n"
                "  `catalog object plant`. DLC items only work if you own that DLC."),
    "hire": ("hire <type> [count]",
             "Hire staff. Guard Cook Workman Warden are always available; Doctor Janitor Gardener Foreman Chief\n"
             "  Accountant Psychologist Lawyer DogHandler ArmedGuard need research first."),
    "research": ("research [name]", "No name: list research. With a name: start it (needs a Warden with an Office)."),
    "pause": ("pause", "Pause the game. You can still plan, order building, zone and hire while paused."),
    "resume": ("resume [speed]", "Unpause. speed 1 = normal, 2-5 = faster."),
    "wait": ("wait [seconds] [speed]", "Let the game run (default 60 s at speed 3), then report what got built."),
    "progress": ("progress", "What you ordered that is built vs still waiting."),
    "save": ("save [name]", "Save the prison (saves/<name>.prison)."),
    "report": ("report",
               "What is going on inside: where prisoners are, what they complain about, injured/down staff,\n"
               "  power stations and pump, escapes/deaths/fights today, and what to fix first."),
    "todo": ("todo", "The game's To-do panel as text (intake, parole, visitors, solitary queue, injured, prison\n"
                     "  temperature) with the command that clears each item, plus the worst prisoner needs."),
    "utilmap": ("utilmap [power|water|both] [x1 y1 x2 y2]",
                "Map of cables, pipes, stations and which objects have power/water (like the game's utilities view)."),
    "switch": ("switch <x> <y> <on|off>", "Turn a PowerSwitch on or off (it splits the power grid)."),
    "screenshot": ("screenshot [scale]", "Picture of what the game shows now, saved as a PNG (scale 2 = half size)."),
    "next": ("next", "What the prison needs next, in order. Start every session with `status` then `next`."),
    "problems": ("problems", "Everything wrong in one list: rooms missing furniture/size, power, water, orders the\n"
                             "  game silently dropped, riot risk."),
    "auto": ("auto", "Safe automatic fixes: intake to beds, unpause, hire guards/cooks to the ratios, hookup, reset\n"
                     "  a tripped power station. Run it every few turns."),
    "money": ("money", "Balance, profit today and the change since yesterday."),
    "regime": ("regime [balanced|work] | regime <from> <to> <activity>",
               "The daily schedule. `regime balanced` sets one that covers every need; or set hours to Sleep, Eat,\n"
               "  Shower, Yard, FreeTime, Work or Lockup (e.g. `regime 13 16 FreeTime`). Low Freedom = more FreeTime."),
    "view": ("view <x1> <y1> <x2> <y2> [scale]", "Move the player's camera to that rectangle and take a screenshot."),
    "remove": ("remove <Object> <x> <y> | remove cable|pipe|wall <x1> <y1> <x2> <y2>",
               "Dismantle an object, delete cable/pipe cells at once, or knock walls down (they become floor)."),
    "unlock": ("unlock <thing>",
               "How to get something that is locked: the steps still to do, in order (research, hire the department\n"
               "  head, give them an Office, then build/hire). Things: janitor laundry workshop library classroom\n"
               "  doctor foreman chief accountant psychologist cctv patrols metaldetector grants logistics, or a\n"
               "  research name. `unlock` alone lists them."),
    "letter": ("letter", "Mark the CEO's letter as read (clears 'Read the CEO's letter' on the game's To-do list)."),
    "grants": ("grants", "Every grant (government contract): money now + money on completion, and whether it is\n"
                         "  available, locked (prerequisites), accepted or completed."),
    "grant": ("grant <name>", "Accept a grant, e.g. `grant bootstraps`. The advance is paid at once; the rest when its\n"
                              "  objectives (on the game's To-do list) are met. Start with bootstraps and Administration."),
    "deployment": ("deployment [all]",
                   "Deployment per sector (room): security zone (Shared, MaxSecOnly, StaffOnly...), staff posts\n"
                   "  (guards, dog handlers, cooks... and how many are manned) and priority. Read-only for now."),
    "logistics": ("logistics", "Food distribution: which canteens each kitchen supplies, canteens with no kitchen,\n"
                  "  and the cell blocks / dorms whose canteen was set by hand. Read-only for now."),
    "patrols": ("patrols", "Guard patrol routes (blue/magenta lines, priority 0-2) and who is assigned to them."),
    "patrol": ("patrol route <blue|magenta> <x1> <y1> <x2> <y2> | patrol assign <guard|dog> <x> <y> |\n"
               "  patrol priority <up|down> <x> <y> | patrol clear <x1> <y1> <x2> <y2>",
               "Deployment > Patrols. Draw a straight route line, then assign a guard or dog handler to a cell on\n"
               "  it (one assignment per cell; each one takes a guard off other duties). priority moves the whole\n"
               "  connected route one level (max 2). Needs the Patrols research (Dogs for dog handlers)."),
    "emergency": ("emergency <shakedown|tunnelsearch|drugbust|stop|bangup|lockdown|status>",
                  "The game's Emergencies buttons. tunnelsearch finds and fills escape tunnels, shakedown finds\n"
                  "  contraband, drugbust finds narcotics (one search at a time; `stop` ends it). bangup/lockdown\n"
                  "  toggle: run the same command again to lift it."),
    "tunnels": ("tunnels [fill]",
                "Escape tunnels from the save (cells, whether they reach outside the fence, found or not).\n"
                "  `tunnels fill` orders workmen to fill every dug cell. Found tunnels do NOT fill themselves."),
    "search": ("search <x> <y> [radius]",
               "Guards search the furniture around a cell (default radius 2): finds contraband and tunnel entrances\n"
               "  (`report` lists TUNNEL entrances). A discovered tunnel is filled by workmen."),
    "lua": ("lua <code>", "Experts: run Lua in the game (`return` a value)."),
}


class Easy:
    def __init__(self, bridge: BridgeClient | None = None):
        self.bridge = bridge or BridgeClient(timeout=20)
        self._snap = None             # (time, parsed save) shared by report/next/rooms/todo in one turn
        self._screen = (1920, 1080)   # game window size, learned from the last screenshot

    # ---- plumbing ---------------------------------------------------------
    def call(self, fn: str, *args: Any, timeout: float | None = None) -> Any:
        return self.bridge.call(fn, *args, timeout=timeout)

    def run(self, verb: str, args: list[str]) -> str:
        verb = verb.lower()
        if verb == "help":
            return self.v_help(args[0] if args else None)
        fn: Callable[..., str] | None = getattr(self, f"v_{verb}", None)
        if fn is None:
            return f"Unknown verb '{verb}'.\n" + self.v_help()
        try:
            out = fn(*args)
            if verb not in READ_ONLY_VERBS:
                self._snap = None  # the prison changed: the next report needs a fresh save
            return out
        except TypeError as exc:
            usage = VERB_HELP.get(verb, (verb, ""))[0]
            raise EasyError(f"{verb}: wrong arguments ({exc}). Usage: {usage}") from None
        except BridgeError as exc:
            raise EasyError(explain(verb, str(exc))) from None

    @staticmethod
    def _ints(*vals: Any) -> list[int]:
        try:
            return [int(float(v)) for v in vals]
        except (TypeError, ValueError):
            raise EasyError(f"expected whole numbers, got {list(vals)}") from None

    # ---- verbs ------------------------------------------------------------
    def v_help(self, verb: str | None = None) -> str:
        if verb and verb in VERB_HELP:
            usage, text = VERB_HELP[verb]
            return f"{usage}\n  {text}"
        lines = ["Prison Architect - easy verbs (coordinates are map cells, x right, y down):"]
        lines += [f"  {VERB_HELP[v][0]:<44} {VERB_HELP[v][1].splitlines()[0]}" for v in VERB_HELP]
        lines.append("Start with: status, next, look. `help <verb>` for details.")
        return "\n".join(lines)

    def v_status(self) -> str:
        s = self.call("state")
        p = self.call("progress")
        speed = s.get("speed")
        run = "PAUSED" if s.get("paused") else f"running x{speed:g}" if isinstance(speed, (int, float)) else "running"
        lines = [
            f"{s.get('clock')}  ({run})  money ${_n(s.get('money'))}  map {s['map']['w']}x{s['map']['h']}",
            f"prisoners {s.get('prisoners_total', 0)} ({_counts(s.get('prisoners'))})  "
            f"cell beds {s.get('cell_capacity_total', 0)}",
            f"staff: {_counts(s.get('staff'))}",
        ]
        zones = s.get("zones_made") or []
        if zones:
            lines.append("zones you made: " + "; ".join(zones))
        c = p.get("construction", {})
        objs = p.get("objects", {})
        waiting = {k: f"{v['installed']}/{v['ordered']}" for k, v in objs.items() if v["installed"] < v["ordered"]}
        lines.append(f"construction: {c.get('still_pending', 0)} cells waiting"
                     + (f"; objects installed/ordered: {_counts(waiting)}" if waiting else ""))
        u = s.get("utilities") or {}
        if u:
            pumps = u.get("pumps") or []
            lines.append(f"power: {len(u.get('power_stations') or [])} station(s), demand {u.get('demand', 0):g}/"
                         f"{u.get('capacity', 0):g}; water pumps powered: "
                         f"{sum(1 for p in pumps if p.get('powered'))}/{len(pumps)}")
            for prob in u.get("problems") or []:
                lines.append("PROBLEM: " + prob)
        if not s.get("native"):
            lines.append("NOTE: bridge DLL 0.3 not active: no zoning/save/pause/research. Update GLU32.dll.")
        if s.get("paused"):
            lines.append("NOTE: paused - nothing gets built until `resume`.")
        return "\n".join(lines)

    def v_look(self, *xy: str) -> str:
        if xy:
            if len(xy) != 4:
                raise EasyError("look takes no numbers (whole map) or 4 numbers: x1 y1 x2 y2")
            m = self.call("map", *self._ints(*xy))
            head = f"cells x {m['origin']['x']}..{m['origin']['x'] + m['size']['w'] - 1}, " \
                   f"y {m['origin']['y']}..{m['origin']['y'] + m['size']['h'] - 1}"
            width = len(str(m["origin"]["y"] + m["size"]["h"]))
            body = [f"{'':>{width}} {m['x_ruler']}"]
            body += [f"{m['origin']['y'] + i:>{width}} {row}" for i, row in enumerate(m["rows"])]
            legend = "; ".join(f"{k} {v}" for k, v in sorted(m["legend"].items()))
            return "\n".join([head, *body, "legend: " + legend])
        o = self.call("overview")
        b = o["block"]
        ruler = "".join(str((i * b // 10) % 10) if (i * b) % 10 < b else " " for i in range(len(o["rows"][0])))
        body = [f"     {ruler}   (x/10)"]
        body += [f"{i * b:>4} {row}" for i, row in enumerate(o["rows"])]
        return "\n".join([f"whole map, 1 char = {b}x{b} cells; left numbers are y. "
                          "# wall _ floor . ground = road , paving + ordered", *body])

    def v_space(self, w: str, h: str, near_x: str | None = None, near_y: str | None = None) -> str:
        args = self._ints(w, h) + (self._ints(near_x, near_y) if near_x is not None and near_y is not None else [])
        r = self.call("find_space", *args)
        return f"free: x {r['x1']}..{r['x2']}, y {r['y1']}..{r['y2']}  -> e.g. room <kind> {r['x1']} {r['y1']} {r['x2']} {r['y2']}"

    def v_room(self, kind: str, x1: str, y1: str, x2: str, y2: str, door_side: str = "south") -> str:
        from ..state.room_rules import describe, load
        bx1, by1, bx2, by2 = self._ints(x1, y1, x2, y2)
        room_type = KIND_ROOM.get(kind.lower())
        rule = load().get(room_type or "", {})
        if rule.get("min"):
            # the rectangle includes the walls, except for outdoor kinds
            pad = 0 if kind.lower() in OUTDOOR_KINDS else 2
            w, h = abs(bx2 - bx1) + 1 - pad, abs(by2 - by1) + 1 - pad
            mw, mh = rule["min"]
            if not ((w >= mw and h >= mh) or (w >= mh and h >= mw)):
                raise EasyError(f"a {kind} needs at least {mw}x{mh} inside; that rectangle gives {w}x{h} "
                                f"(walls included: at least {mw + pad}x{mh + pad}). Game rule: {describe(room_type, rule)}")
        r = self.call("room", kind, bx1, by1, bx2, by2, door_side)
        i = r["inside"]
        furn = ", ".join(r["furniture"]) if r["furniture"] else "none needed"
        z = f"zoned {r['room']}" if r["zoned"] else "NOT zoned"
        need = f"\ngame requires: {describe(r['room'], rule).split(': ', 1)[1]}" if rule else ""
        return (f"{r['room']}: {r['built']}; inside x {i['x1']}..{i['x2']}, y {i['y1']}..{i['y2']}; {z}\n"
                f"furniture: {furn}{need}\n{r['note']}\nNext: `wait` so workmen build it, then `progress`.")

    def v_catalog(self, *words: str) -> str:
        """Floors, walls and objects the game can build (read from the installed game, cached in runs/)."""
        from ..state.catalog import BUILDABLE, describe, load, search
        ws = [w for w in words if w]
        items = load(refresh=bool(ws) and ws[0].lower() == "refresh")
        if not items:
            return "Could not read the game's item list (needs the Steam install and WinRAR/UnRAR for main.dat)."
        if ws and ws[0].lower() == "refresh":
            ws = ws[1:]
        kinds = BUILDABLE
        if ws and ws[0].lower() in BUILDABLE + ("floors", "walls", "objects"):
            kinds = (ws.pop(0).lower().rstrip("s"),)
        if not ws:
            counts = {k: sum(1 for i in items.values() if i["kind"] == k) for k in BUILDABLE}
            return (f"{counts['floor']} floors, {counts['wall']} walls/fences, {counts['object']} objects. "
                    "Search: `catalog <words>`, e.g. `catalog wood floor`, `catalog object plant`.")
        hits = search(items, ws, kinds)
        if not hits:
            return f"nothing called '{' '.join(ws)}'. Try fewer or shorter words."
        lines = [describe(n, it) for n, it in hits[:30]]
        if len(hits) > 30:
            lines.append(f"... {len(hits) - 30} more: add a word to narrow it down.")
        return "\n".join(lines)

    def v_rules(self, *name: str) -> str:
        """The game's own room requirements (read from the installed game's data, cached in runs/)."""
        from ..state.room_rules import describe, load
        want = " ".join(name).strip()
        rules = load(refresh=want.lower() == "refresh")
        if not rules:
            return ("Could not read the room rules from the game (needs the Steam install and WinRAR/UnRAR for "
                    "main.dat). `rooms`/`problems` fall back to the bridge's own list.")
        if want and want.lower() != "refresh":
            key = KIND_ROOM.get(want.lower()) or next((k for k in rules if k.lower() == want.lower()), None)
            if not key or key not in rules:
                return f"no room '{want}'. Rooms: " + ", ".join(sorted(rules))
            return describe(key, rules[key])
        return "\n".join(describe(k, rules[k]) for k in sorted(rules))

    def v_cells(self, x: str, y: str, count: str = "4") -> str:
        r = self.call("cell_block", *self._ints(x, y, count))
        c = r["corridor"]
        return (f"{len(r['cells'])} cells ordered (bed, toilet, jail door each){', zoned as Cell' if r['zoned'] else ''}.\n"
                f"corridor x {c['x1']}..{c['x2']}, y {c['y1']}..{c['y2']} - keep it clear.\n{r['next']}")

    def v_fence(self, x1: str, y1: str, x2: str, y2: str) -> str:
        r = self.call("perimeter", *self._ints(x1, y1, x2, y2))
        gates = ", ".join(r["road_gates"]) or "none"
        return f"fence ordered: {r['fence_cells']} cells, road gates at {gates} (~${_n(r['cost_estimate'])}).\n{r['note']}"

    def existing_utilities(self) -> dict[str, list[str]]:
        """Cells that already have cable / pipe, read from a fresh save."""
        root = self.snapshot()
        out: dict[str, list[str]] = {"power": [], "water": []}
        for name, key in (("Electricity", "power"), ("Water", "water")):
            sec = root.section(name)
            for c in sec.sections() if sec else []:
                parts = c.name.split()
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    if key == "water" and c.get("PipeType") is None:
                        continue
                    out[key].append(f"{parts[0]},{parts[1]}")
        return out

    def v_intake(self, mode: str = "", n: str = "") -> str:
        args = [mode] + ([int(float(n))] if n else []) if mode else []
        r = self.call("intake", *args)
        extra = {"max": f" (max {r.get('max_total')})", "perday": f" ({r.get('per_day')} a day)"}.get(r["mode"], "")
        out = f"intake: {r['mode']}{extra} - {r.get('meaning')}"
        return out + (f"\n{r['advice']}" if r.get("advice") else "")

    def _catalog_name(self, name: str, kinds: tuple[str, ...]) -> tuple[str, dict]:
        """The game's exact name for a floor/wall/object (any case, or its toolbar name); unknown names are
        refused with the closest matches. Without the catalogue (no game data) the name passes through."""
        from ..state.catalog import describe, load, search
        items = load()
        if not items:
            return name, {}
        key = name.replace(" ", "").lower()
        for n, it in items.items():
            if it["kind"] in kinds and key in (n.lower(), it.get("display", "").replace(" ", "").lower()):
                return n, it
        hits = search(items, [w for w in re.split(r"[\s_]+|(?<=[a-z])(?=[A-Z])", name) if w], kinds)[:6]
        what = "/".join(kinds)
        raise EasyError(f"no {what} called '{name}'." + (" Did you mean: " + "; ".join(describe(n, i) for n, i in hits)
                        if hits else f" `catalog {kinds[0]} <words>` searches them."))

    def v_place(self, obj: str, x: str, y: str) -> str:
        obj, info = self._catalog_name(obj, ("object", "item"))  # items: movable (LaundryBasket)
        r = self.call("place_object", obj, *self._ints(x, y))
        extra = ""
        if info.get("size") and info["size"] != [1, 1]:
            extra = f", {info['size'][0]}x{info['size'][1]}"
        if info.get("cost"):
            extra += f", ${info['cost']:,}"
        if info.get("research"):
            extra += f"; needs the {info['research']} research"
        return f"ordered {r['object']} at {r['x']},{r['y']}{extra} (workmen install it)"

    def v_floor(self, material: str, *rect: str) -> str:
        if len(rect) != 4:
            raise EasyError("usage: " + VERB_HELP["floor"][0])
        mat, info = self._catalog_name(material, ("floor",))
        r = self.call("build_area", mat, *self._ints(*rect))
        cost = f" (about ${info['cost'] * r['queued']:,})" if info.get("cost") else ""
        return f"ordered {r['queued']} cells of {mat}{cost}; workmen lay it over time."

    def v_wall(self, material: str, *rect: str) -> str:
        if len(rect) != 4:
            raise EasyError("usage: " + VERB_HELP["wall"][0])
        mat, _ = self._catalog_name(material, ("wall",))
        x1, y1, x2, y2 = self._ints(*rect)
        straight = x1 == x2 or y1 == y2
        r = self.call("build_line" if straight else "build_wall_rect", mat, x1, y1, x2, y2)
        return (f"ordered {r['queued']} cells of {mat} as a {'line' if straight else 'rectangle outline'}. "
                + (r.get("note") or "Leave a gap for a door (`place Door x y`)."))

    def v_station(self, kind: str, x: str, y: str) -> str:
        names = {"power": "PowerStation", "water": "WaterPumpStation"}
        if kind.lower() not in names:
            raise EasyError("station power <x> <y>  or  station water <x> <y>")
        obj = names[kind.lower()]
        r = self.call("place_object", obj, *self._ints(x, y))
        return (f"ordered {obj} (3x3, $5000) covering x {r['x']}..{r['x'] + 2}, y {r['y']}..{r['y'] + 2}. "
                "Keep a gap to other power stations (touching stations trip). Then `hookup`.")

    def v_hookup(self, kind: str = "both") -> str:
        known = self.existing_utilities()
        kind = kind.lower()
        arg = known if kind in ("both", "all", "") else known.get(kind, [])
        r = self.call("hookup", kind, arg)
        parts = [r] if "kind" in r else [r["power"], r["water"]]
        lines = [f"{p['kind']}: {p['objects_needing_it']} objects need it, {p['newly_connected']} newly connected, "
                 f"{p['pieces_ordered']} pieces ordered" for p in parts]
        return "\n".join(lines + ["Workmen lay them over time. Run hookup again after adding rooms."])

    def v_power(self, action: str = "") -> str:
        u = self.call("utilities", action.lower() == "on")
        lines = [f"station at {p['x']},{p['y']}: {'ON' if p['on'] is True else p['on'] if p['on'] else 'OFF'}, "
                 f"demand {p['demand']:g}/{p['capacity']:g}" for p in u["power_stations"]]
        lines += [f"water pump at {p['x']},{p['y']}: {'powered' if p['powered'] else 'NO POWER (no water!)'}"
                  for p in u["pumps"]]
        lines += ["PROBLEM: " + p for p in u["problems"]]
        lines += self._tripped_detail([p for p in u["power_stations"] if p["on"] is False])
        return "\n".join(lines) or "no stations"

    def _tripped_detail(self, tripped: list[dict]) -> list[str]:
        """Why each tripped station tripped: a tripped station reports demand 0, so estimate its grid's
        load from the save (cables flood-filled from the station, objects on them)."""
        if not tripped:
            return []
        from ..state.report import grid_loads
        try:
            grids = grid_loads(self.snapshot())
        except (BridgeError, EasyError):
            return []
        out = []
        for g in grids:
            if g["on"] or g["at"] is None:
                continue
            what = _counts(g["objects"]) or "nothing"
            line = (f"TRIPPED {g['at'][0]},{g['at'][1]}: about {g['estimated_load']} wired to a "
                    f"{g['capacity']:g} station ({what})")
            if g["shared_with"]:
                line += ("; its grid also reaches the station(s) at " +
                         ", ".join(f"{a[0]},{a[1]}" for a in g["shared_with"] if a) +
                         " - cut the cable between them (`remove cable`) so each has its own grid")
            elif g["estimated_load"] > g["capacity"]:
                line += (f" - move about {g['estimated_load'] - g['capacity']:g} of it to a new `station power` "
                         "(cut the cable to that part with `remove cable`)")
            out.append(line)
        return out

    def v_report(self) -> str:
        from ..state.report import situation, situation_text
        return situation_text(situation(self.snapshot()))

    def v_todo(self) -> str:
        from ..state.report import NEED_FIX, situation, todo, todo_action
        root = self.snapshot()
        items = todo(root)
        have: dict[str, int] = {}
        for r in self._rooms_from(root):
            have[r["type"]] = have.get(r["type"], 0) + 1
        live = self._todo_live()
        if live:
            # the panel's own counts replace the save-based estimate (Energy < 15 overcounted: 6 vs the panel's 3)
            items = [i for i in items if not i.startswith("Staff exhausted")]
            if live["exhausted"] > 0:
                items.append(f"Staff exhausted: {live['exhausted']} ({live['resting']} resting)")
        lines = []
        for i in items:
            act = todo_action(i, have)
            if live and i.startswith("Prisoner intake"):
                i += {"closed": ": CLOSED to new inmates (see the game's Intake Report)",
                      "strike": ": closed by a guard strike", "riot": ": closed by a riot"}.get(
                    live["intake"], f": {live['arrivals']} arriving at {live['arrival_hour']:02d}:00")
            lines.append(f"- {i}" + (f"\n    do: {act}" if act else ""))
        lines += self._todo_grants()
        sit = situation(root)
        needs = [(k, v) for k, v in sit.get("worst_needs", []) if v >= 50 and k in NEED_FIX]
        if needs:
            lines.append("Prisoner needs (0-100, high = bad):")
            lines += [f"- {k} {v}\n    do: {NEED_FIX[k]}" for k, v in needs]
        return "\n".join(lines) if lines else "nothing on the game's to-do list"

    def _todo_live(self) -> dict | None:
        """The To-do panel's own figures (DLL 0.6.1); None with an older DLL."""
        try:
            return self.call("todo_state")
        except BridgeError:
            return None

    def _todo_grants(self) -> list[str]:
        """Accepted grants as the panel lists them: each part crossed off or still to do (DLL 0.6.1)."""
        try:
            objs = self.call("objectives")["objectives"]
        except BridgeError:
            return []
        if not objs or "advance" not in objs[0]:
            return []
        out = []
        for g in objs:
            if g.get("parent") or not g["name"].startswith("Grant_"):
                continue
            parts = [p for p in objs if p.get("parent") == g["name"]]
            todo_n = sum(1 for p in parts if not p.get("done"))
            out.append(f"- Grant {g['name'].removeprefix('Grant_')}: ${_n(g.get('completion') or 0)} on completion"
                       + (" (DONE)" if g.get("done") else f", {todo_n} of {len(parts)} parts to do"))
            for p in parts:
                label = p["name"].removeprefix(g["name"] + "_").replace("_", " ")
                hint = ""
                key = label.split()[0].lower()
                if not p.get("done") and key in GRANT_PART_HINT:
                    hint = f"  -> {GRANT_PART_HINT[key]}"
                out.append(f"    [{'x' if p.get('done') else ' '}] {label}{hint}")
        return out

    def v_unlock(self, *target: str) -> str:
        r = self.call("unlock", "".join(target)) if target else self.call("unlock")
        if "targets" in r:
            return "unlock <thing>, things: " + " ".join(r["targets"]) + " (or a research name)"
        if r["done"]:
            steps = [st["step"] for st in r["steps"]]
            return f"{r['target']}: already unlocked." + (f" Next: `{steps[-1]}`." if steps else "")
        staff = self.call("state").get("staff") or {}
        heads = sum(staff.get(h, 0) for h in ("Warden", "Foreman", "Chief", "Accountant", "Lawyer", "Psychologist"))
        offices = sum(1 for x in self.rooms() if x["type"] == "Office")
        lines = [f"{r['target']} needs: " + " -> ".join(r["research"])]
        n = 0
        for st in r["steps"]:
            n += 1
            cmd = st["step"]
            text = cmd if cmd == "wait" else f"`{cmd}`"
            lines.append(f"{n}. {text}" + (f" ({st['why']})" if st.get("why") else "") +
                         (f" - after {st['after']}" if st.get("after") else ""))
            if cmd.startswith("hire ") and cmd.split()[1] in DEPARTMENT_HEAD.values():
                n += 1
                lines.append(f"{n}. `room office x1 y1 x2 y2` (6x6) for the {cmd.split()[1]}")
        if offices < heads:
            lines.append(f"WARNING: {heads} department heads but {offices} offices: build `room office` (6x6) first.")
        lines.append(r["note"])
        return "\n".join(lines)

    def v_utilmap(self, kind: str = "both", *xy: str) -> str:
        from ..state.report import built_area, utility_map
        if kind.lstrip("-").isdigit():  # numbers without a kind
            xy, kind = (kind, *xy), "both"
        root = self.snapshot()
        if xy:
            if len(xy) != 4:
                raise EasyError("utilmap takes [power|water|both] and optionally x1 y1 x2 y2")
            x1, y1, x2, y2 = self._ints(*xy)
        else:
            x1, y1, x2, y2 = built_area(root)
            if x2 - x1 > 110:
                x2 = x1 + 110
        return utility_map(root, x1, y1, x2, y2, kind.lower())

    def screenshot(self, scale: int = 2, timeout: float = 10.0) -> Path:
        """Ask the DLL for the next rendered frame; return a PNG under runs/screenshots."""
        from .image import downscale, read_bmp, write_png
        self.call("screenshot")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.call("screenshot_result")
            if r.get("done"):
                if not r.get("ok"):
                    raise EasyError(f"screenshot failed: {r.get('error')}")
                w, h, rows = read_bmp(Path(r["path"]))
                self._screen = (w, h)
                w, h, rows = downscale(w, h, rows, max(1, int(scale)))
                out = RUNS / "screenshots" / time.strftime("pa-%Y%m%d-%H%M%S.png")
                return write_png(out, w, h, rows)
            time.sleep(0.2)
        raise EasyError("no frame was drawn in time: is the game minimised? (it only draws while visible or in "
                        "the taskbar preview)")

    def v_screenshot(self, scale: str = "2") -> str:
        p = self.screenshot(int(scale))
        return f"saved {p} (what the game shows right now; open it to look)"

    def v_switch(self, x: str, y: str, state: str) -> str:
        r = self.call("switch", *self._ints(x, y), state.lower() in ("on", "true", "1"))
        return f"switch at {r['switch']} is now {'ON' if r['on'] else 'OFF'}"

    def v_solitary(self, x: str, y: str, count: str = "6") -> str:
        r = self.call("solitary_block", *self._ints(x, y, count))
        c = r["corridor"]
        return (f"{len(r['cells'])} solitary cells ordered (SolitaryDoor each){', zoned Solitary' if r['zoned'] else ''}.\n"
                f"corridor x {c['x1']}..{c['x2']}, y {c['y1']}..{c['y2']} - keep it clear. Punished prisoners go here.")

    def v_zone(self, room_type: str, x1: str, y1: str, x2: str, y2: str) -> str:
        r = self.call("zone", room_type, *self._ints(x1, y1, x2, y2))
        return f"{r['zoned']}: {r['cells']} cells, {r['cells_in_a_room_now']} now in a room. {r['note']}"

    def v_unzone(self, x1: str, y1: str, x2: str, y2: str) -> str:
        r = self.call("unzone", *self._ints(x1, y1, x2, y2))
        return f"zone removed from {r['cells']} cells"

    def v_roomtypes(self) -> str:
        return ", ".join(self.call("room_types"))

    def v_hire(self, kind: str, count: str = "1") -> str:
        r = self.call("hire", kind, *self._ints(count))
        return (f"hired {r['hired']} {r['type']} for ${_n(r['cost'])}; money left ${_n(r['money_left'])}. "
                f"They walk in from the road at {r['arrives_at']['x']},{r['arrives_at']['y']}.")

    def v_research(self, name: str | None = None) -> str:
        if name:
            r = self.call("research", name)
            if r.get("status") == "started":
                return f"started {r['research']} (${_n(r['cost'])}); the {r['researched_by']} works on it. {r['note']}" + self.autosave()
            return f"{r['research']}: {r['status']}"
        r = self.call("research")
        groups: dict[str, list[str]] = {}
        for item in r["research"]:
            st = item["status"].split(" (")[0]
            st = "in progress" if st.startswith("in progress") else st
            label = f"{item['name']} ${_n(item['cost'])}" + (f" -> {item['unlocks']}" if item.get("unlocks") else "")
            if item["status"].startswith("in progress"):
                label += f" ({item['status'][12:]})"
            groups.setdefault(st, []).append(label)
        lines = [f"Warden hired: {'yes' if r['warden_hired'] else 'NO - hire a Warden and build an office first'}"]
        for st in ("in progress", "available", "done", "locked"):
            if groups.get(st):
                lines.append(f"{st}: " + "; ".join(groups[st] if st != "locked" else [g.split(' $')[0] for g in groups[st]]))
        lines.append(r["how"])
        return "\n".join(lines)

    def v_pause(self) -> str:
        return self.call("pause")["note"]

    def v_resume(self, speed: str = "1") -> str:
        r = self.call("resume", float(speed))
        return f"running at speed {r['speed']:g}"

    def v_wait(self, seconds: str = "60", speed: str = "3") -> str:
        secs = max(5, min(600, int(float(seconds))))
        before = self.call("state")
        self.call("resume", float(speed))
        time.sleep(secs)
        after = self.call("state")
        p = self.call("progress")
        c = p.get("construction", {})
        objs = p.get("objects", {})
        done = {k: f"{v['installed']}/{v['ordered']}" for k, v in objs.items()}
        return (f"waited {secs}s at speed {float(speed):g}: {before.get('clock')} -> {after.get('clock')}; "
                f"money ${_n(before.get('money'))} -> ${_n(after.get('money'))}\n"
                f"cells finished since last check {c.get('finished_since_last_check', 0)}, still waiting {c.get('still_pending', 0)}\n"
                f"objects installed/ordered: {_counts(done)}\n"
                f"prisoners {after.get('prisoners_total', 0)}, cell beds {after.get('cell_capacity_total', 0)}")

    def v_progress(self) -> str:
        """Pending work from the save (survives reloads) + every ordered object checked against the map."""
        from ..state.report import pending_work, verify_orders
        root = self.snapshot()
        pend = pending_work(root)
        lines = [f"construction jobs waiting: {pend['construction_jobs']}"]
        if pend["work_queue"]:
            lines.append("work queue: " + _counts(pend["work_queue"]))
        for a in pend.get("unreachable", [])[:3]:
            lines.append(f"UNREACHABLE: {a['cells']} construction jobs at x {a['x1']}..{a['x2']}, y {a['y1']}..{a['y2']}: "
                         "no workman can walk there (walls or a fence in the way). They also STALL the workmen, who "
                         "carry materials there and give up. Open a way in (`remove fence x1 y1 x2 y2` on the fence "
                         "between) - if even that does not get built, ask the human to cancel these jobs in the game.")
        try:
            planned = self.call("planned")
        except BridgeError:
            planned = {"objects": [], "now": 0}
        v = verify_orders(root, planned.get("objects") or [], planned.get("now") or 0)
        if planned.get("objects"):
            lines.append(f"ordered objects: {v['installed']} installed, {v['waiting']} still coming, "
                         f"{len(v['failed'])} never appeared")
            if v["failed"]:
                lines.append("  NOT BUILT (probably blocked - wall, other object or outside the room): " +
                             ", ".join(v["failed"][:12]) + " - order them again somewhere free.")
        lines.append("Nothing moving? The game must be running (`resume`), and building needs money and delivered materials.")
        return "\n".join(lines)

    def v_problems(self) -> str:
        """Everything that is wrong, in one list: rooms missing things, power/water, dropped orders, game to-do."""
        from ..state.report import room_problems, situation, verify_orders
        root = self.snapshot()
        sit = situation(root)
        out = [f"ROOM: {p}" for p in room_problems(root)]
        from ..state.report import grid_loads
        for g in grid_loads(root):
            if not g["on"]:
                why = (f"its grid also reaches the station at {', '.join(str(a) for a in g['shared_with'])}"
                       if g["shared_with"] else f"about {g['estimated_load']} wired to {g['capacity']:g} "
                       f"({_counts(g['objects']) or 'nothing'})")
                out.append(f"POWER: station at {g['at']} is OFF: {why} (`power` says how to fix it)")
        for p in sit["pumps"]:
            if not p["powered"]:
                out.append(f"WATER: pump at {p['at']} has no power, so there is no water")
        if sit["unpowered"]:
            out.append("POWER: without power: " + _counts(sit["unpowered"]) + " (`hookup power`)")
        try:
            planned = self.call("planned")
            v = verify_orders(root, planned.get("objects") or [], planned.get("now") or 0)
            if v["failed"]:
                out.append("ORDERS never built: " + ", ".join(v["failed"][:10]))
        except BridgeError:
            pass
        from ..state.report import pending_work
        for a in pending_work(root).get("unreachable", [])[:3]:
            out.append(f"UNREACHABLE: {a['cells']} construction jobs at x {a['x1']}..{a['x2']}, y {a['y1']}..{a['y2']} "
                       "(walls/fence in the way; `progress` says how to open a way in)")
        t = sit.get("temperature")
        if t is not None and t >= 60:
            out.append(f"RIOT RISK: prison temperature {t:.0f}/100 (`todo`, `report`)")
        return "\n".join(out) if out else "No problems found: rooms meet their requirements, power and water are on."

    def v_auto(self) -> str:
        """Safe automatic fixes a small model can run every turn. Never builds rooms or spends big money."""
        done: list[str] = []
        s = self.call("state")
        staff = s.get("staff") or {}
        money_now = s.get("money") or 0
        pris = s.get("prisoners_total", 0)
        if s.get("intake") == "all":
            self.call("intake", "beds"); done.append("intake set to 'beds' (only prisoners you can house)")
        if s.get("paused"):
            self.call("resume", 1); done.append("unpaused (nothing is built while paused)")
        want_guards = max(3, pris // 6 + 2)
        # guards lying unconscious do not count (live riot: 14 hired, 13 down, nothing asked for more)
        from ..state.report import situation
        down = situation(self.snapshot()).get("staff_down") or {}
        g = staff.get("Guard", 0) - down.get("Guard", 0)
        if g < want_guards and money_now > 5000:
            n = min(want_guards - g, 12 if down.get("Guard") else 4, int((money_now - 3000) // 500))
            if n > 0:
                self.call("hire", "Guard", n); done.append(f"hired {n} Guard ({g} -> {g + n}, want {want_guards})")
        rooms = self.rooms()
        have = {r["type"] for r in rooms}
        if "Kitchen" in have and staff.get("Cook", 0) < 2 and money_now > 3000:
            self.call("hire", "Cook", 2 - staff.get("Cook", 0)); done.append("hired Cooks for the kitchen")
        try:
            h = self.v_hookup("both")
            if "newly connected" in h and not all(" 0 newly" in line for line in h.splitlines()[:2]):
                done.append("hookup: " + " / ".join(h.splitlines()[:2]))
        except (EasyError, BridgeError) as exc:
            done.append(f"hookup skipped: {exc}")
        try:
            from ..state.report import tunnel_cells
            dug = tunnel_cells(self.snapshot())
            if dug:
                r = self.call("fill_tunnels", [f"{x},{y}" for x, y in dug])
                done.append(f"ordered {r['ordered']} tunnel cells filled (escape tunnels)")
        except (EasyError, BridgeError) as exc:
            done.append(f"tunnel fill skipped: {exc}")
        util = s.get("utilities") or {}
        for st in util.get("power_stations") or []:
            if st.get("on") is False and st.get("overloaded", 0) == 1 and st.get("demand", 0) <= st.get("capacity", 50):
                self.call("utilities", True); done.append(f"reset tripped station at {st['x']},{st['y']}")
                break
        return "\n".join(["auto:"] + [f"- {d}" for d in done]) if done else "auto: nothing to fix automatically."

    def v_money(self) -> str:
        from ..state.report import money
        return money(self.snapshot())

    def v_regime(self, *args: str) -> str:
        """regime | regime balanced|work | regime <from> <to> <activity>"""
        if not args:
            r = self.call("regime")
        elif len(args) == 1:
            r = self.call("regime_preset", args[0])
        elif len(args) >= 3:
            r = self.call("set_regime", *self._ints(args[0], args[1]), " ".join(args[2:]))
        else:
            raise EasyError("regime  |  regime balanced  |  regime <from_hour> <to_hour> <activity>")
        tot = ", ".join(f"{k} {v}" for k, v in sorted(r["totals"].items()))
        hours = "  ".join(r["hours"])
        return f"daily schedule (category {r['category']}): {tot}\n{hours}\n{r['note']}"

    def v_view(self, x1: str, y1: str, x2: str, y2: str, scale: str = "2") -> str:
        """Move the player's view to a rectangle and take a screenshot of it."""
        self.call("look_at", *self._ints(x1, y1, x2, y2), self._screen[0], self._screen[1])
        time.sleep(0.3)  # let the game draw a frame at the new position
        return f"view moved; {self.v_screenshot(scale)}"

    def v_remove(self, what: str, *args: str) -> str:
        """remove <Object> <x> <y> | remove cable|pipe|wall <x1> <y1> <x2> <y2>"""
        kind = what.lower()
        if kind in ("cable", "pipe", "wall", "walls", "fence"):
            if len(args) != 4:
                raise EasyError(f"remove {kind} <x1> <y1> <x2> <y2>")
            fn = {"cable": "remove_cable", "pipe": "remove_pipe"}.get(kind, "demolish")
            r = self.call(fn, *self._ints(*args))
            n = r.get("removed_cells", r.get("walls_replaced"))
            return f"{kind}: {n} cells. {r['note']}"
        if len(args) != 2:
            raise EasyError("remove <Object> <x> <y>   or   remove cable|pipe|wall <x1> <y1> <x2> <y2>")
        r = self.call("remove", what, *self._ints(*args))
        return f"dismantling the {what} at {r['at']['x']},{r['at']['y']}. {r['note']}"

    def save(self, name: str, timeout: float = 20.0) -> str:
        self.call("save", name)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.call("save_result")
            if r.get("done"):
                if r.get("ok"):
                    return r["path"]
                raise EasyError(f"save failed: {r.get('error')}")
            time.sleep(0.3)
        raise EasyError("save did not finish in time; is the game window minimised or loading?")

    def v_save(self, name: str = "agent") -> str:
        return f"saved {self.save(name)}"

    def snapshot(self, max_age: float = 3.0):
        """A parsed save of the running prison, reused for `max_age` seconds so one turn saves once."""
        from ..state import load_prison
        now = time.monotonic()
        if self._snap is not None and now - self._snap[0] < max_age:
            return self._snap[1]
        root = load_prison(self.save(SNAPSHOT)).root
        self._snap = (time.monotonic(), root)
        return root

    def rooms(self) -> list[dict]:
        return self._rooms_from(self.snapshot())

    def _rooms_from(self, root) -> list[dict]:
        sec = root.section("Rooms")
        info = {}
        for r in sec.items_indexed() if sec else []:
            rid = r.get("Id.i")
            info[str(rid)] = {"type": r.get("RoomType"), "failed": str(r.get("RequirementsFailed")).lower() == "true"}
        boxes = self.call("room_boxes") or {}
        out = []
        for rid, b in sorted(boxes.items(), key=lambda kv: int(kv[0])):
            i = info.get(str(rid), {})
            out.append({"id": int(rid), "type": i.get("type", "?"), "missing_something": i.get("failed", False), **b})
        return out

    def v_rooms(self) -> str:
        rooms = self.rooms()
        if not rooms:
            return "No rooms yet. Build one with `room <kind> x1 y1 x2 y2`."
        lines = []
        for r in rooms:
            flag = "  <- the game says something is MISSING (check its furniture/size, and power/water)" \
                if r["missing_something"] else ""
            lines.append(f"{r['type']:<12} x {r['x1']}..{r['x2']}, y {r['y1']}..{r['y2']} ({r['cells']} cells){flag}")
        return "\n".join(lines)

    def v_next(self) -> str:
        """What to do next, in the order that worked live: utilities, fence, guards, beds, food, hygiene, admin."""
        from ..state.report import situation
        s = self.call("state")
        staff = s.get("staff") or {}
        root = self.snapshot()
        sit = situation(root)
        rooms = self._rooms_from(root)
        have: dict[str, int] = {}
        for r in rooms:
            have[r["type"]] = have.get(r["type"], 0) + 1
        cells = root.section("Cells")
        fence = sum(1 for c in cells.sections() if c.get("Mat") == "Fence") if cells else 0
        pris = s.get("prisoners_total", 0)
        beds = s.get("cell_capacity_total", 0)
        stations = sit["power_stations"]
        todo: list[str] = []
        later: list[str] = []
        for prob in (s.get("utilities") or {}).get("problems") or []:
            if "No PowerStation" in prob or "No WaterPumpStation" in prob:
                continue
            text = prob.replace("api.utilities(true)", "`power on`").replace('api.hookup("power")', "`hookup power`")
            # a full station is a warning, not an emergency (one kitchen draws exactly 50 by design)
            (later if "nearly full" in text else todo).append(text)
        if not stations:
            todo.append("Power: `station power x y` (3x3, $5000) near where the kitchen will be. One station feeds 50.")
        if not sit["pumps"]:
            todo.append("Water: `station water x y` (3x3, $5000); it needs power, so `hookup` after it is built.")
        if fence < 20:
            todo.append("Perimeter: `fence x1 y1 x2 y2` round everything incl. Deliveries/Garbage BEFORE prisoners arrive.")
        if s.get("intake") in ("all", "perday") and beds < pris + 4:
            todo.insert(0, f"Intake is '{s.get('intake')}' with beds {beds} < prisoners {pris}: `intake beds` NOW so "
                           "only prisoners you can house arrive.")
        want_guards = max(3, pris // 6 + 2)
        down = sit.get("staff_down") or {}
        up = staff.get("Guard", 0) - down.get("Guard", 0)
        if up < want_guards:
            extra = f" ({down['Guard']} are DOWN - riot or fights; replace them now)" if down.get("Guard") else ""
            todo.insert(0 if down.get("Guard", 0) * 2 >= staff.get("Guard", 1) else len(todo),
                        f"Guards on their feet: {up}, want {want_guards}{extra}: `hire Guard {want_guards - up}`.")
        if not have.get("HoldingCell") and not have.get("Cell") and not have.get("Dormitory"):
            todo.append("A HoldingCell so arriving prisoners have somewhere to go: `room holding x1 y1 x2 y2` (about 9x8).")
        try:
            bed_orders = self.call("progress").get("objects", {}).get("Bed", {})
            coming = max(0, bed_orders.get("ordered", 0) - bed_orders.get("installed", 0))
        except (BridgeError, AttributeError):
            coming = 0
        if beds + coming < pris + 4:
            todo.append(f"Beds {beds} (+{coming} being built) < prisoners {pris}: `room dormitory x1 y1 x2 y2` "
                        "(15x15 = ~24 beds) or `cells x y 8`. Keep `intake beds` until they catch up.")
        if not have.get("Kitchen"):
            todo.append("A Kitchen: `room kitchen x1 y1 x2 y2` (9x8), then `hookup`.")
        if not have.get("Canteen"):
            todo.append("A Canteen next to the kitchen: `room canteen ...` (12x10).")
        if sit.get("hungry", 0) > max(3, pris // 6):
            todo.append(f"FOOD: {sit['hungry']} of {pris} prisoners are hungry. Build another `room kitchen` (9x8) "
                        "with its own `station power` (a kitchen uses a whole station), `hire Cook 3`, and keep 3 Eat "
                        "hours in the `regime`.")
        if sit.get("tired_staff", 0) >= 3:
            todo.append(f"{sit['tired_staff']} staff exhausted: another `room staffroom x1 y1 x2 y2` (8x7) helps.")
        # food scale (measured live: 2 cookers left 71 prisoners at ~1% meals): ~1 cooker and 1 cook per 10
        objs = Counter(str(o.get("Type")) for o in (root.section("Objects").items_indexed()
                                                    if root.section("Objects") else []))
        want_cookers = max(2, (pris + 9) // 10)
        if have.get("Kitchen") and objs.get("Cooker", 0) < want_cookers:
            todo.append(f"Food: {objs.get('Cooker', 0)} cookers for {pris} prisoners, want {want_cookers} "
                        "(`place Cooker x y` inside the kitchen, then `hookup power`; watch the station's 50 limit).")
        if have.get("Kitchen") and staff.get("Cook", 0) < max(2, min(want_cookers, objs.get("Cooker", 0))):
            todo.append(f"Cooks: have {staff.get('Cook', 0)}, want one per cooker: `hire Cook ...`.")
        benches = objs.get("Bench", 0)
        if have.get("Canteen") and benches * 4 < pris // 2:
            todo.append(f"Canteen seats: ~{benches * 4} seats for {pris} prisoners; build another `room canteen ...` "
                        "(12x10) or a bigger one.")
        if not have.get("Staffroom") and sum(staff.values()) >= 10:
            todo.append("Staff get exhausted without rest (slow building): `room staffroom x1 y1 x2 y2` (8x7).")
        if sit["unpowered"] or any(n in ("Hygiene", "Bladder", "Bowels") for n in sit["complaining_about"]):
            todo.append("Objects without power/water or prisoners needing toilets/showers: `hookup`, then `utilmap`.")
        if not have.get("Shower"):
            todo.append("A Shower room (needs water): `room shower ...` (7x6).")
        if not have.get("Yard"):
            todo.append("A Yard: `room yard ...` (16x12, outdoors).")
        if sit["staff_hurt"] or sit["staff_down"] or sit["prisoners"] > 20:
            try:
                research = {r["name"]: r["status"] for r in self.call("research")["research"]}
            except (BridgeError, KeyError, TypeError):
                research = {}
            health = research.get("Health", "")
            if health == "done":
                if not staff.get("Doctor"):
                    todo.append("Health research is done: `hire Doctor 2` and build `room infirmary x1 y1 x2 y2` (10x8).")
                elif not have.get("MedicalWard"):
                    todo.append("Doctors need an infirmary: `room infirmary x1 y1 x2 y2` (10x8).")
            elif health.startswith("in progress"):
                pass  # the Warden is on it
            elif staff.get("Warden") and have.get("Office"):
                todo.append("Injured people pile up: `research Health` (unlocks Doctors).")
        if not staff.get("Warden"):
            todo.append("A Warden unlocks research: `hire Warden`, then `room office ...` (6x6).")
        elif not have.get("Office"):
            todo.append("An Office for the Warden: `room office x1 y1 x2 y2` (6x6).")
        for tn in (sit.get("tunnels") or [])[:2]:
            if tn["entrances"]:
                ex, ey = tn["entrances"][0]
                todo.insert(0 if tn["outside_fence"] else len(todo),
                            f"TUNNEL from {ex},{ey}" + (" to OUTSIDE the fence (prisoners escape through it)"
                                                        if tn["outside_fence"] else "") +
                            f": `emergency tunnelsearch` (whole prison) or `search {ex} {ey}`.")
        for r in [r for r in rooms if r["missing_something"]][:2]:
            todo.append(f"{r['type']} at {r['x1']},{r['y1']} is missing something (furniture not built yet? power? water?).")
        todo += self._needs_steps(sit, have, pris)
        if staff.get("Warden") and have.get("Office") and pris >= 20:
            todo += self._research_steps(staff, have, (s.get("money") or 0))
        todo += later
        if not todo:
            todo.append("The basics are in place. `wait 120`, then `report`. Consider research (`research`).")
        head = f"{s.get('clock')}, money ${_n(s.get('money'))}, prisoners {pris}, beds {beds}. Do these in order:"
        return "\n".join([head] + [f"{i}. {t}" for i, t in enumerate(todo[:9], 1)])

    def _needs_steps(self, sit: dict, have: dict[str, int], pris: int) -> list[str]:
        """Rooms that answer the worst prisoner needs (measured: Spirituality 72, Recreation 64 at day 24)."""
        out = []
        needs = dict(sit.get("worst_needs") or [])
        complain = sit.get("complaining_about") or {}
        if needs.get("Spirituality", 0) >= 50 and not have.get("Chapel") and pris >= 30:
            out.append(f"Spirituality {needs['Spirituality']}/100: `room chapel x1 y1 x2 y2` (10x10 with walls).")
        if needs.get("Recreation", 0) >= 50 and not have.get("CommonRoom") and pris >= 30:
            out.append(f"Recreation {needs['Recreation']}/100: `room commonroom x1 y1 x2 y2` (10x8), then "
                       "`hookup power` for the TV.")
        if complain.get("Clothing", 0) >= max(5, pris // 10) and not have.get("Laundry"):
            out.append(f"{complain['Clothing']} complain about Clothing: a laundry. `unlock laundry` lists the steps.")
        return out

    def _research_steps(self, staff: dict, have: dict[str, int], money: float) -> list[str]:
        """The next research per free department head, from RESEARCH_LADDER."""
        try:
            items = {r["name"]: r for r in self.call("research")["research"]}
        except (BridgeError, KeyError, TypeError):
            return []
        busy = {r.get("by") for r in items.values() if str(r.get("status", "")).startswith("in progress")}
        heads = 1 + sum(staff.get(h, 0) for h in DEPARTMENT_HEAD.values())
        out: list[str] = []
        for name, why in RESEARCH_LADDER:
            r = items.get(name)
            if not r or r["status"] == "done" or str(r["status"]).startswith("in progress"):
                continue
            by = r.get("by") or "Warden"
            if by in busy or r["status"] != "available":
                continue
            busy.add(by)
            if by != "Warden" and not staff.get(by):
                out.append(f"Research {name} ({why}) is done by the {by}: `hire {by}` and `room office x1 y1 x2 y2` "
                           "(6x6, every department head needs their own).")
            elif have.get("Office", 0) < heads:
                out.append(f"{heads} department heads share {have.get('Office', 0)} office(s): `room office ...` (6x6) "
                           "so each can research.")
                break
            elif money >= r["cost"] + 5000:
                out.append(f"`research {name}` (${_n(r['cost'])}, the {by}): {why}.")
            if len(out) >= 2:
                break
        return out

    def v_grants(self) -> str:
        r = self.call("grants")
        groups: dict[str, list[str]] = {}
        for g in r["grants"]:
            groups.setdefault(g["status"], []).append(
                f"{g['name'].removeprefix('Grant_')} (${_n(g['advance'])} now + ${_n(g['completion'])} on completion)")
        lines = [f"{st}: " + "; ".join(groups[st]) for st in ("accepted", "available", "completed", "locked")
                 if groups.get(st)]
        lines.append("`grant <name>` accepts an available one (the advance is paid at once).")
        return "\n".join(lines)

    def autosave(self) -> str:
        """Save to agent_auto after money/progress actions: live, the game was once closed without saving
        and the grants, research and CEO letter done since the last save were lost."""
        try:
            self.save("agent_auto")
            return " (saved as agent_auto)"
        except (BridgeError, EasyError):
            return ""

    def v_grant(self, name: str) -> str:
        r = self.call("grant", name)
        return f"accepted {r['accepted']}. {r['note']}" + self.autosave()

    def v_letter(self) -> str:
        r = self.call("read_letter")
        return r["note"] + self.autosave()

    def v_emergency(self, action: str = "status") -> str:
        r = self.call("emergency", action)
        on = [k for k, v in r["state"].items() if v]
        return f"{r['note']} Active now: {', '.join(on) if on else 'nothing'}."

    def v_patrols(self) -> str:
        r = self.call("patrols")
        if not r["cells"]:
            return "No patrol routes. `patrol route blue <x1> <y1> <x2> <y2>` draws one."
        runs: dict[tuple, list[tuple[int, int]]] = {}
        for c in r["cells"]:
            runs.setdefault((c["colour"], c["priority"]), []).append((c["x"], c["y"]))
        lines = [f"{col} route, priority {pr}: {len(cells)} cells, x {min(x for x, _ in cells)}..{max(x for x, _ in cells)}"
                 f" y {min(y for _, y in cells)}..{max(y for _, y in cells)}" for (col, pr), cells in sorted(runs.items())]
        for s in r["stations"]:
            lines.append(f"{s['who']} assigned at {s['x']},{s['y']} ({s['colour']}, priority {s['priority']})")
        return "\n".join(lines)

    def v_patrol(self, action: str = "", *args: str) -> str:
        if action == "route" and len(args) == 5:
            r = self.call("patrol", "route", args[0], *self._ints(*args[1:]))
            return f"{r['route']} route: {r['cells_added']} new cells. Next: `patrol assign guard <x> <y>` on it."
        if action == "clear" and len(args) == 4:
            r = self.call("patrol", "clear", *self._ints(*args))
            return f"cleared {r['cells_cleared']} route cells (and their assignments)."
        if action == "assign" and len(args) == 3:
            self.call("patrol", "assign", args[0], *self._ints(*args[1:]))
            return f"{args[0]} assigned at {args[1]},{args[2]}: one will walk the route when on duty."
        if action == "priority" and len(args) == 3:
            r = self.call("patrol", "priority", args[0], *self._ints(*args[1:]))
            return f"route priority now {r['priority']} ({r['route_cells']} connected cells)."
        raise EasyError("usage: " + VERB_HELP["patrol"][0])

    def v_deployment(self, which: str = "") -> str:
        """Deployment per sector from a fresh save (read-only: the bridge cannot change deployment yet)."""
        from ..state.report import deployment
        sectors = deployment(self.snapshot(max_age=0))
        if not sectors:
            return "No sectors in the save."
        show_all = which.lower() == "all"
        lines = []
        for s in sorted(sectors, key=lambda s: (s["room"] or "~", s["id"])):
            set_up = s["zone"] != "Shared" or s["posts"] or s["priority"] or s["custom"]
            if not (show_all or set_up):
                continue
            name = s["room"] or ("outdoors" if s["outside"] else "area")
            bits = []
            if s["zone"] != "Shared":
                meaning = DEPLOY_ZONE_MEANING.get(s["zone"], "")
                warn = ""
                if s["zone"] in DEPLOY_ZONE_ONE_CATEGORY and s["room"] in SHARED_ROOMS:
                    warn = f" - WARNING: other prisoners can no longer use this {s['room']}"
                bits.append(f"zone {s['zone']}" + (f" ({meaning})" if meaning else "") + warn)
            for who, (taken, total) in s["posts"].items():
                bits.append(f"{total} {who} post{'s' if total > 1 else ''} ({taken} manned)")
            if s["priority"]:
                bits.append(f"priority {s['priority']}")
            if s["custom"]:
                bits.append("custom zones " + ",".join(map(str, s["custom"])))
            lines.append(f"{name} (sector {s['id']}, x {s['x1']}..{s['x2']} y {s['y1']}..{s['y2']}): "
                         + ("; ".join(bits) if bits else "Shared, no posts"))
        if not lines:
            lines.append(f"Nothing set up: all {len(sectors)} sectors are Shared with no staff posts.")
        elif not show_all:
            lines.append(f"({len(sectors)} sectors in total; `deployment all` lists every one.)")
        lines.append("Read-only: change it in the game's Deployment tab (the bridge cannot write deployment yet).")
        return "\n".join(lines)

    def v_logistics(self) -> str:
        """Food distribution from a fresh save: kitchens -> canteens, and the eating areas set by hand
        (read-only: change it in the game's Logistics > Food Distribution)."""
        from ..state.report import deployment
        secs = {s["id"]: s for s in deployment(self.snapshot(max_age=0))}

        def name(sid: int) -> str:
            s = secs.get(sid)
            return f"{s['room'] or 'area'} {sid} (x {s['x1']}..{s['x2']} y {s['y1']}..{s['y2']})" if s else f"sector {sid}"

        kitchens = [s for s in secs.values() if s["room"] == "Kitchen"]
        canteens = [s for s in secs.values() if s["room"] == "Canteen"]
        if not kitchens and not canteens:
            return "No kitchens or canteens yet."
        lines = ["Food:"]
        supplied = set()
        for k in sorted(kitchens, key=lambda s: s["id"]):
            supplied.update(k["targets"])
            to = ", ".join(name(t) for t in k["targets"]) or "NO canteen"
            lines.append(f"- {name(k['id'])} supplies {to}" + (" [set by hand]" if k["manual"] else ""))
        for c in canteens:
            if c["id"] not in supplied:
                lines.append(f"- WARNING: {name(c['id'])} gets food from no kitchen")
        eaters = [s for s in secs.values() if s["room"] not in ("Kitchen", "Canteen") and s["manual"] and s["targets"]]
        for s in sorted(eaters, key=lambda s: s["id"]):
            lines.append(f"- {name(s['id'])} eats at {', '.join(name(t) for t in s['targets'])} [set by hand]")
        lines.append("Cell blocks and dorms not listed eat at a canteen the game picks for them (not saved).")
        if not any(s["room"] == "Laundry" for s in secs.values()):
            lines.append("Laundry: none built (`room laundry`), so Laundry Distribution has nothing to route.")
        lines.append("Read-only: change routes in the game's Logistics > Food / Laundry Distribution.")
        return "\n".join(lines)

    def v_tunnels(self, action: str = "") -> str:
        """Escape tunnels from a fresh save; `tunnels fill` orders workmen to fill every dug cell."""
        from ..state.report import tunnel_cells, tunnels
        root = self.snapshot(max_age=0)
        found = tunnels(root)
        lines = [f"{t['cells']} cells x {t['x1']}..{t['x2']} y {t['y1']}..{t['y2']}"
                 + (", REACHES OUTSIDE THE FENCE" if t["outside_fence"] else "")
                 + ("" if t["discovered"] else ", not found by the guards yet") for t in found]
        if action.lower() != "fill":
            return ("\n".join(lines) + "\n`tunnels fill` has workmen fill them all.") if lines else "no tunnels"
        cells = tunnel_cells(root)
        if not cells:
            return "no tunnels to fill"
        r = self.call("fill_tunnels", [f"{x},{y}" for x, y in cells])
        return (f"ordered {r['ordered']} tunnel cells filled ({len(found)} tunnels). {r['note']} "
                "Prisoners dig again from cell toilets: keep dogs on patrol and run `emergency tunnelsearch`.")

    def v_search(self, x: str, y: str, radius: str = "2") -> str:
        r = self.call("search", *self._ints(x, y, radius))
        return ("searching: " + ", ".join(r["searching"]) + ". " if r["searching"] else "") + r["note"]

    def v_lua(self, *code: str) -> str:
        import json
        return json.dumps(self.bridge.exec(" ".join(code)), indent=1, default=str)
