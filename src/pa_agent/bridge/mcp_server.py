"""Dependency-free MCP (stdio) server exposing Prison Architect to agents.

Run:  pa-agent mcp        (or: python -m pa_agent.bridge.mcp_server)

Register in an MCP client, e.g. Claude Code:
  claude mcp add prison-architect -- C:\\path\\to\\.venv\\Scripts\\pa-agent.exe mcp
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable

from .client import BridgeClient, BridgeError
from .easy import Easy, EasyError, explain

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "prison-architect-bridge", "version": "0.4.0"}

INSTRUCTIONS = """You are playing a live game of Prison Architect. Coordinates are map cells:
x to the right, y down, (0,0) top-left.
Loop: pa_status -> pa_next (what the prison needs, in order) -> do ONE thing ->
pa_wait (let workmen build) -> pa_status.
Build a whole room in one call with pa_room (walls + floor + door + furniture +
zone; the rectangle includes the walls). pa_cells builds a row of cells. Find
empty ground with pa_space; see the map with pa_look. After adding rooms, call
pa_hookup so cookers/fridges get power and toilets/showers/sinks get water
(needs a PowerStation and a WaterPumpStation, placed with pa_place_object).
Hire with pa_hire (Guard, Cook, Workman, Warden; others after pa_research).
pa_rooms says which rooms the game thinks are missing something.
Nothing is built while the game is paused: pa_resume. pa_save saves.
Every tool answers in a few lines; errors come with a HINT line.
Not available: camera, regime. pa_lua runs raw Lua for experts."""


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


INT = {"type": "integer"}
STR = {"type": "string"}
RECT = {"x1": INT, "y1": INT, "x2": INT, "y2": INT}


class Server:
    def __init__(self, bridge: BridgeClient | None = None):
        self.bridge = bridge or BridgeClient(timeout=20)
        self.easy = Easy(self.bridge)
        self.tools: dict[str, tuple[str, dict, Callable[[dict], Any]]] = {}
        self._register()

    # ---- tool definitions -------------------------------------------------
    def tool(self, name: str, description: str, schema: dict):
        def deco(fn):
            self.tools[name] = (description, schema, fn)
            return fn
        return deco

    def _call(self, fn: str, *args):
        return self.bridge.call(fn, *args)

    def _register(self):
        easy = self.easy

        def verb(name: str, verb_name: str, description: str, props: dict, required: list[str], order: list[str]):
            @self.tool(name, description, _schema(props, required))
            def _run(a, verb_name=verb_name, order=order):
                args = [str(a[k]) for k in order if k in a and a[k] is not None]
                return easy.run(verb_name, args)

        verb("pa_status", "status", "START HERE. Money, clock, paused?, prisoners, beds, staff, rooms you made, "
             "construction progress. A few lines of text.", {}, [], [])
        verb("pa_next", "next", "What the prison needs next, as a numbered list of concrete commands.", {}, [], [])
        verb("pa_look", "look", "Map. No arguments: small picture of the whole map (1 char = 3x3 cells). "
             "With x1,y1,x2,y2: exact cells. # wall, _ floor, . ground, = road, + ordered not built.",
             RECT, [], list(RECT))
        verb("pa_space", "space", "Find empty ground for a width x height room (walls included), optionally near a point.",
             {"width": INT, "height": INT, "near_x": INT, "near_y": INT}, ["width", "height"],
             ["width", "height", "near_x", "near_y"])
        verb("pa_room", "room", "Build a whole room in one call: walls + floor + door + furniture + zone. The rectangle "
             "INCLUDES the walls. kind: holding, cell, kitchen, canteen, shower, yard, office, staffroom, infirmary, "
             "dormitory, visitation, storage, deliveries, garbage, chapel, commonroom, parole, laundry, classroom, workshop, "
             "library, cleaning (the last five need research: pa_unlock). door_side: north/south/east/west. Good sizes: "
             "holding 9x8, kitchen 9x8, canteen 12x10, shower 7x6, yard 16x12 (outdoor), office 6x6, chapel 10x10, "
             "commonroom 10x8, parole 7x7, laundry 8x6.",
             {"kind": STR, **RECT, "door_side": STR}, ["kind", *RECT], ["kind", *RECT, "door_side"])
        verb("pa_cells", "cells", "A row of 3x3 prison cells (bed, toilet, jail door, zoned Cell) with a corridor below. "
             "Uses (count*4+1) x 7 cells from x,y.", {"x": INT, "y": INT, "count": INT}, ["x", "y", "count"],
             ["x", "y", "count"])
        verb("pa_hookup", "hookup", "Connect everything that needs power (cookers, fridges, lights, TVs) or water "
             "(toilets, showers, sinks) to the nearest cable/pipe or station. Run after adding rooms.",
             {"kind": {"type": "string", "enum": ["both", "power", "water"]}}, [], ["kind"])
        verb("pa_power", "power", "Power stations (on/off, demand vs capacity) and whether the water pump has power "
             "(no power = no water). action \"on\" switches tripped stations back on.",
             {"action": {"type": "string", "enum": ["", "on"]}}, [], ["action"])
        verb("pa_report", "report", "What is going on inside: prisoners (where, complaints, worst needs), injured staff, "
             "power/water status, escapes, deaths, fights, and what to fix first. Use when things go wrong.", {}, [], [])
        verb("pa_utilmap", "utilmap", "Map of cables, pipes, power stations and pumps, marking objects WITHOUT power or "
             "water. kind: power, water or both; optional x1,y1,x2,y2.",
             {"kind": {"type": "string", "enum": ["both", "power", "water"]}, **RECT}, [], ["kind", *RECT])
        verb("pa_switch", "switch", "Turn the PowerSwitch at x,y on or off.",
             {"x": INT, "y": INT, "state": {"type": "string", "enum": ["on", "off"]}}, ["x", "y", "state"], ["x", "y", "state"])
        verb("pa_fence", "fence", "Perimeter fence around the whole prison (include deliveries, garbage, stations). "
             "Road crossings get RoadGates. Build it BEFORE prisoners arrive.", RECT, list(RECT), list(RECT))
        verb("pa_station", "station", "Order a PowerStation (kind power) or WaterPumpStation (kind water), 3x3 with "
             "top-left at x,y. One power station feeds 50; power stations must not touch each other.",
             {"kind": {"type": "string", "enum": ["power", "water"]}, "x": INT, "y": INT}, ["kind", "x", "y"],
             ["kind", "x", "y"])
        verb("pa_intake", "intake", "Prisoner intake. mode beds = only accept prisoners while there are free beds "
             "(recommended; set it first). none, max (n = total), perday (n a day), all (floods the prison). "
             "No mode: show the current one.",
             {"mode": {"type": "string", "enum": ["beds", "none", "max", "perday", "all"]}, "n": INT}, [], ["mode", "n"])
        verb("pa_todo", "todo", "The game's To-do panel as text (intake mode, parole, visitors waiting, solitary queue, "
             "injured people, prison temperature) with a `do:` command for each item, plus the worst prisoner needs.",
             {}, [], [])
        verb("pa_unlock", "unlock", "How to unlock something locked (Janitor, laundry, workshop, Doctor, Chief, cctv, "
             "grants...): the research chain and the steps still to do in order (research, hire the department head, "
             "their Office, then build/hire). Empty target lists the things.", {"target": STR}, [], ["target"])
        verb("pa_emergency", "emergency", "The game's Emergencies buttons: shakedown (contraband), tunnelsearch (finds "
             "and fills escape tunnels), drugbust (narcotics), stop (ends the running search), bangup / lockdown "
             "(toggle; call again to lift), status.", {"action": STR}, [], ["action"])
        verb("pa_search", "search", "Guards search the furniture around a cell (default radius 2): finds contraband and "
             "tunnel entrances (pa_report lists TUNNEL entrances); discovered tunnels get filled.",
             {"x": INT, "y": INT, "radius": INT}, ["x", "y"], ["x", "y", "radius"])
        verb("pa_solitary", "solitary", "A row of 1x1 solitary cells (SolitaryDoor, zoned Solitary) with a corridor "
             "below, (count*2+1) x 5 cells. Needed for punishments; without it the riot risk climbs.",
             {"x": INT, "y": INT, "count": INT}, ["x", "y", "count"], ["x", "y", "count"])
        verb("pa_problems", "problems", "Everything wrong in one list: rooms missing furniture or size, power, water, "
             "orders the game silently dropped, riot risk.", {}, [], [])
        verb("pa_auto", "auto", "Safe automatic fixes: intake to beds, unpause, hire guards/cooks to the ratios, hookup, "
             "reset a tripped station. Run it every few turns.", {}, [], [])
        verb("pa_money", "money", "Balance, profit today and the change since yesterday.", {}, [], [])
        verb("pa_regime", "regime", "The daily schedule. No arguments: show it. preset balanced|work: replace it. Or set "
             "hours from..to to an activity (Sleep, Eat, Shower, Yard, FreeTime, Work, Lockup).",
             {"preset": {"type": "string", "enum": ["balanced", "work"]}, "from_hour": INT, "to_hour": INT,
              "activity": STR}, [], ["preset", "from_hour", "to_hour", "activity"])
        verb("pa_view", "view", "Move the player's camera to a rectangle and take a screenshot (see pa_screenshot).",
             RECT, list(RECT), list(RECT))
        verb("pa_remove", "remove", "Remove things. what = an object type (with x1,y1 = where) to dismantle it, or "
             "cable / pipe / wall with a rectangle x1,y1,x2,y2.",
             {"what": STR, **RECT}, ["what", "x1", "y1"], ["what", *RECT])
        verb("pa_zone", "zone", "Zone a rectangle as a room type (use the room's INSIDE). pa_room already zones.",
             {"room_type": STR, **RECT}, ["room_type", *RECT], ["room_type", *RECT])
        verb("pa_rooms", "rooms", "Every room with its type and whether the game says it is missing something.",
             {}, [], [])
        verb("pa_hire", "hire", "Hire staff: Guard, Cook, Workman, Warden (always); Doctor, Janitor, Gardener, Foreman, "
             "Chief, Accountant, Psychologist, Lawyer, DogHandler, ArmedGuard after research. Costs the game's price.",
             {"type": STR, "count": INT}, ["type"], ["type", "count"])
        verb("pa_research", "research", "No name: list research and its status. With a name: start it "
             "(needs a Warden with an Office; the cost is paid when it starts).", {"name": STR}, [], ["name"])
        verb("pa_pause", "pause", "Pause the game (you can still plan, build orders, zone, hire).", {}, [], [])
        verb("pa_resume", "resume", "Unpause. speed 1 = normal, up to 5.", {"speed": {"type": "number"}}, [], ["speed"])
        verb("pa_wait", "wait", "Let the game run for some real seconds (default 60, max 600) at a speed (default 3), "
             "then report what got built.", {"seconds": INT, "speed": {"type": "number"}}, [], ["seconds", "speed"])
        verb("pa_progress", "progress", "What you ordered that is built vs still waiting.", {}, [], [])
        verb("pa_save", "save", "Save the prison to saves/<name>.prison.", {"name": STR}, [], ["name"])
        verb("pa_help", "help", "List the easy verbs, or explain one (verb: room, cells, hire...).", {"verb": STR}, [],
             ["verb"])

        @self.tool("pa_screenshot", "Look at the game: a picture of what the game window shows right now "
                   "(the player's current view). scale 2 = half size (default), 3 = third.",
                   _schema({"scale": INT}, []))
        def _shot(a):
            import base64
            path = easy.screenshot(int(a.get("scale") or 2))
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            return {"__content__": [{"type": "image", "data": data, "mimeType": "image/png"},
                                    {"type": "text", "text": f"saved {path}"}]}

        @self.tool("pa_connection", "Diagnose the connection: bridge DLL loaded, game script running, pump, clients.",
                   _schema({}, []))
        def _connection(a):
            st = self.bridge.status()
            try:
                st["game"] = self.bridge.ping()
            except BridgeError as exc:
                st["game_error"] = str(exc)
            return st

        # ---- lower level, for experts -------------------------------------
        @self.tool("pa_place_object", "Buy and install one object (Bed, Toilet, JailDoor, Door, Cooker, PowerStation, "
                   "WaterPumpStation, Capacitor, ElectricalCable, PipeLarge, PipeSmall...). ox,oy = facing, default 0,1.",
                   _schema({"object": STR, "x": INT, "y": INT, "ox": INT, "oy": INT}, ["object", "x", "y"]))
        def _place(a):
            return self._call("place_object", a["object"], a["x"], a["y"], a.get("ox", 0), a.get("oy", 1))

        @self.tool("pa_api", "Experts: call any api.* helper by name with a list of arguments, e.g. build_area "
                   "[material,x1,y1,x2,y2], build_wall_rect, build_line, objects [type], count [[types]], demolish, "
                   "look_at, set_regime. pa_help lists the easy verbs; api.help() via pa_lua lists everything.",
                   _schema({"fn": STR, "args": {"type": "array"}}, ["fn"]))
        def _api(a):
            return self._call(a["fn"], *(a.get("args") or []))

        @self.tool("pa_lua", "Run raw Lua inside the game (experts). Use `return` to get a value back. "
                   "Game.* is limited to functions verified safe.",
                   _schema({"code": STR, "timeout": {"type": "number"}}, ["code"]))
        def _lua(a):
            result = self.bridge.exec(a["code"], a.get("timeout"))
            logs = self.bridge.drain_logs()
            return {"result": result, "logs": logs} if logs else result

    # ---- JSON-RPC ---------------------------------------------------------
    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            return self._ok(mid, {"protocolVersion": PROTOCOL_VERSION, "serverInfo": SERVER_INFO,
                                  "capabilities": {"tools": {}}, "instructions": INSTRUCTIONS})
        if method in ("notifications/initialized", "initialized") or method.startswith("notifications/"):
            return None
        if method == "ping":
            return self._ok(mid, {})
        if method == "tools/list":
            return self._ok(mid, {"tools": [{"name": n, "description": d, "inputSchema": s}
                                            for n, (d, s, _) in self.tools.items()]})
        if method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            if name not in self.tools:
                return self._err(mid, -32602, f"unknown tool {name}")
            try:
                result = self.tools[name][2](params.get("arguments") or {})
                if isinstance(result, dict) and "__content__" in result:
                    return self._ok(mid, {"content": result["__content__"], "isError": False})
                text = result if isinstance(result, str) else json.dumps(result, indent=1, default=str)
                return self._ok(mid, {"content": [{"type": "text", "text": text}], "isError": False})
            except EasyError as exc:
                return self._ok(mid, {"content": [{"type": "text", "text": f"ERROR: {exc}"}], "isError": True})
            except BridgeError as exc:
                return self._ok(mid, {"content": [{"type": "text", "text": "ERROR: " + explain(name, str(exc))}],
                                      "isError": True})
            except Exception as exc:  # reported to the model, not a protocol error
                return self._ok(mid, {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                                      "isError": True})
        if mid is None:
            return None
        return self._err(mid, -32601, f"method not found: {method}")

    @staticmethod
    def _ok(mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _err(mid, code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    def serve(self, stdin=None, stdout=None):
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                reply = self.handle(msg)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                reply = self._err(msg.get("id"), -32603, "internal error")
            if reply is not None:
                stdout.write(json.dumps(reply) + "\n")
                stdout.flush()


def main() -> int:
    Server().serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
