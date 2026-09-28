"""Explore the live game's Lua API through the bridge and save the answers.

Run from the project folder with the game unpaused:
    .\\.venv\\Scripts\\python.exe scripts\\explore_api.py

Writes runs\\api_explore.json. Probes only read state, except: one save
("pa_agent_snapshot") and zoning cells 11..14 x 11..13 as a Cell (inside the
brick-wall test square).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pa_agent.bridge import BridgeClient, BridgeError  # noqa: E402

HELPERS = r"""
local function keys(t, depth)
  depth = depth or 1
  if type(t) ~= "table" then return type(t) .. ":" .. tostring(t) end
  local out = {}
  for k, v in pairs(t) do
    if type(v) == "table" and depth > 1 then out[tostring(k)] = keys(v, depth - 1)
    elseif type(v) == "table" or type(v) == "function" or type(v) == "userdata" then out[tostring(k)] = type(v)
    else out[tostring(k)] = v end
  end
  return out
end
local function try(f, ...) local r = {pcall(f, ...)}; if r[1] then return r[2] else return "ERR: " .. tostring(r[2]) end end
"""

PROBES = {
    "world_keys": "return keys(World, 1)",
    "world_meta": "return keys(getmetatable(World), 2)",
    "world_numprisoners": "return keys(World.NumPrisoners, 2)",
    "world_capacity": "return keys(World.Capacity, 2)",
    "world_objectids_type": "return type(World.ObjectIds)",
    "world_objectids_sample": """
        local n, sample = 0, {}
        for k, v in pairs(World.ObjectIds) do
          n = n + 1
          if n <= 5 then sample[tostring(k)] = keys(v, 1) end
        end
        return {count = n, sample = sample}""",
    "world_objectid_fn": "return type(World.ObjectId)",
    "world_dataregistry": "return keys(World.DataRegistry, 2)",
    "world_cell_10_10": "return keys(World.GetCell(10, 10), 2)",
    "world_cell_room": "local c = World.GetCell(12, 12); return {room = keys(c.Room, 2), mat = Object.GetMaterial(12, 12)}",
    "this_keys": "return keys(this, 2)",
    "game_numrooms": "return try(Game.GetNumRooms)",
    "game_getobject": "return try(Game.GetObject, 'Workman')",
    "game_getproperty_balance": "return try(Game.GetProperty, 'Balance')",
    "game_getproperty_world_balance": "return try(Game.GetProperty, 'World', 'Balance')",
    "game_speed": "return try(Game.GetGameSpeed)",
    "workers_nearby": """
        local ids = {}
        for k, v in pairs(World.ObjectIds) do ids[#ids+1] = v; if #ids > 3000 then break end end
        local types = {}
        for _, o in ipairs(ids) do
          local ok, t = pcall(function() return o.Type end)
          local key = ok and tostring(t) or "?"
          types[key] = (types[key] or 0) + 1
        end
        return types""",
    "first_workman": """
        for k, v in pairs(World.ObjectIds) do
          local ok, t = pcall(function() return v.Type end)
          if ok and t == 'Workman' then return keys(v, 2) end
        end
        return 'none'""",
    "materials_test_square": "return api.materials(9, 9, 16, 15)",
    "zone_cell_test": "return try(api.zone, 'Cell', 11, 11, 14, 13)",
    "save_snapshot": "return try(api.save, 'pa_agent_snapshot')",
    "objective_keys": "return keys(Objective, 1)",
    "workqueue_keys": "return keys(WorkQueue, 2)",
}


def main():
    client = BridgeClient(timeout=15)
    results = {"status": client.connect(), "probes": {}}
    for name, body in PROBES.items():
        code = HELPERS + "\n" + body
        t0 = time.monotonic()
        try:
            value = client.exec(code)
            results["probes"][name] = {"ok": True, "result": value}
        except BridgeError as exc:
            results["probes"][name] = {"ok": False, "error": str(exc)}
        results["probes"][name]["ms"] = round((time.monotonic() - t0) * 1000)
        print(f"{name:32s} {'ok' if results['probes'][name]['ok'] else 'ERROR'}")
    results["logs"] = client.drain_logs()
    out = Path(__file__).resolve().parents[1] / "runs" / "api_explore.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
