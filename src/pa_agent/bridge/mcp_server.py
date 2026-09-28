"""Dependency-free MCP (stdio) server exposing Prison Architect to agents.

Run:  pa-agent mcp        (or: python -m pa_agent.bridge.mcp_server)

Register in an MCP client, e.g. Claude Code:
  claude mcp add prison-architect -- C:\\path\\to\\.venv\\Scripts\\pa-agent.exe mcp
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from .client import BridgeClient, BridgeError

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "prison-architect-bridge", "version": "0.3.0"}

INSTRUCTIONS = """You are playing a live game of Prison Architect.
Start with pa_help (what you can do) and pa_state (the prison right now), then
pa_map to see the layout (+ marks ordered work not built yet), pa_progress to\nfollow construction. Coordinates are map cells: x to the right, y down.
Build with pa_building (walls + floor + door), pa_furnish (furniture for a room
kind), pa_cell_block (a row of cells), or the lower-level pa_build_* and
pa_place_object. Everything is built by workmen over time and costs money.
Zoning rooms, hiring staff, pausing, saving and the camera are NOT available:
when you need a room zoned, tell the human exactly which room and rectangle.
pa_api calls any helper from pa_help by name; pa_lua runs raw Lua for experts."""


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


INT = {"type": "integer"}
STR = {"type": "string"}
RECT = {"x1": INT, "y1": INT, "x2": INT, "y2": INT}


class Server:
    def __init__(self, bridge: BridgeClient | None = None):
        self.bridge = bridge or BridgeClient()
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
        @self.tool("pa_status", "Check the connection: bridge loaded, game script running, game time and speed.",
                   _schema({}, []))
        def _status(a):
            st = self.bridge.status()
            try:
                st["game"] = self.bridge.ping()
            except BridgeError as exc:
                st["game_error"] = str(exc)
            return st

        @self.tool("pa_help", "List every game helper with its arguments and an example. Call this first.",
                   _schema({}, []))
        def _help(a):
            return self._call("help")

        @self.tool("pa_state", "Live summary of the prison: time, speed, map size, prisoners, cell capacity.",
                   _schema({}, []))
        def _state(a):
            return self._call("state")

        @self.tool("pa_map", "Text map of an area (default whole map): # wall, _ floor, . open ground, = road.",
                   _schema({"x1": INT, "y1": INT, "x2": INT, "y2": INT}, []))
        def _map(a):
            if all(k in a for k in RECT):
                return self._call("map", a["x1"], a["y1"], a["x2"], a["y2"])
            return self._call("map")

        @self.tool("pa_find_space", "Find an empty area of open ground of the given size, optionally near a point.",
                   _schema({"width": INT, "height": INT, "near_x": INT, "near_y": INT}, ["width", "height"]))
        def _space(a):
            args = [a["width"], a["height"]]
            if "near_x" in a and "near_y" in a:
                args += [a["near_x"], a["near_y"]]
            return self._call("find_space", *args)

        @self.tool("pa_building", "Build a room: walls around the rectangle, a floor inside and a door. "
                   "door_side: north/south/east/west (default south). Returns the inside rectangle.",
                   _schema({**RECT, "door_side": STR, "door": STR, "wall": STR, "floor": STR}, list(RECT)))
        def _building(a):
            return self._call("building", a["x1"], a["y1"], a["x2"], a["y2"], a.get("door_side", "south"),
                              a.get("door", "Door"), a.get("wall", "BrickWall"), a.get("floor", "ConcreteFloor"))

        @self.tool("pa_furnish", "Place the right furniture in a room's inside rectangle. kind: kitchen, canteen, "
                   "shower, yard, holding, cell, office, staffroom.",
                   _schema({"kind": STR, **RECT}, ["kind", *RECT]))
        def _furnish(a):
            return self._call("furnish", a["kind"], a["x1"], a["y1"], a["x2"], a["y2"])

        @self.tool("pa_cell_block", "Build a row of 3x3 cells (bed, toilet, jail door) opening south onto a corridor.",
                   _schema({"x": INT, "y": INT, "count": INT}, ["x", "y", "count"]))
        def _cells(a):
            return self._call("cell_block", a["x"], a["y"], a["count"])

        @self.tool("pa_progress", "What you ordered that is finished vs still pending (construction and objects).",
                   _schema({}, []))
        def _progress(a):
            return self._call("progress")

        @self.tool("pa_objects", "List every object/person of a type with positions (Workman, Prisoner, Guard, Bed...).",
                   _schema({"type": STR, "limit": INT}, ["type"]))
        def _objects(a):
            return self._call("objects", a["type"], a.get("limit", 200))

        @self.tool("pa_staff", "How many of each kind of staff you have.", _schema({}, []))
        def _staff(a):
            return self._call("staff")

        @self.tool("pa_build_area", "Fill a rectangle with a material (ConcreteFloor, PavingStone, Building...).",
                   _schema({"material": STR, **RECT}, ["material", *RECT]))
        def _area(a):
            return self._call("build_area", a["material"], a["x1"], a["y1"], a["x2"], a["y2"])

        @self.tool("pa_build_walls", "Walls around the outline of a rectangle (BrickWall, ConcreteWall, Fence).",
                   _schema({"material": STR, **RECT}, ["material", *RECT]))
        def _walls(a):
            return self._call("build_wall_rect", a["material"], a["x1"], a["y1"], a["x2"], a["y2"])

        @self.tool("pa_build_line", "A straight horizontal or vertical line of a material (wall, fence, road).",
                   _schema({"material": STR, **RECT}, ["material", *RECT]))
        def _line(a):
            return self._call("build_line", a["material"], a["x1"], a["y1"], a["x2"], a["y2"])

        @self.tool("pa_place_object", "Buy and install one object (Bed, Toilet, JailDoor, Door, Cooker, ...). "
                   "ox,oy = facing, default 0,1.",
                   _schema({"object": STR, "x": INT, "y": INT, "ox": INT, "oy": INT}, ["object", "x", "y"]))
        def _place(a):
            return self._call("place_object", a["object"], a["x"], a["y"], a.get("ox", 0), a.get("oy", 1))

        @self.tool("pa_api", "Call any helper listed by pa_help by name, with a list of arguments.",
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

    # ---- snapshot ---------------------------------------------------------
    def snapshot(self, full: bool = False) -> dict:
        from ..config import user_data_directory
        from ..state import load_prison, summarize
        saves = user_data_directory() / "saves"
        name = "pa_agent_snapshot"
        target = saves / f"{name}.prison"
        before = target.stat().st_mtime if target.exists() else 0.0
        self.bridge.call("save", name)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if target.exists() and target.stat().st_mtime > before:
                time.sleep(0.3)  # let the write finish
                break
            time.sleep(0.2)
        else:
            candidates = sorted(saves.glob("*.prison"), key=lambda p: p.stat().st_mtime)
            raise BridgeError(f"save did not appear at {target}; newest save is "
                              f"{candidates[-1].name if candidates else 'none'}")
        loaded = load_prison(target)
        return loaded.root.to_dict() if full else summarize(loaded.root)

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
                text = json.dumps(result, indent=1, default=str)
                return self._ok(mid, {"content": [{"type": "text", "text": text}], "isError": False})
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
