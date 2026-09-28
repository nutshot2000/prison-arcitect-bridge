# Prison Architect agent bridge — notes for agents

Read AGENTS.md for repo rules. This file is about using the live bridge.

## The live game

- `pa-agent.exe` lives in `.venv\Scripts\`. The MCP server (`pa-agent mcp`) exposes `pa_status`, `pa_lua`,
  `pa_build_walls`, `pa_build_area`, `pa_build_line`, `pa_place_object`, `pa_zone`, `pa_materials`, `pa_camera`,
  `pa_snapshot`.
- Without MCP: `.\.venv\Scripts\pa-agent.exe bridge` and `.\.venv\Scripts\pa-agent.exe lua "return api.info()"`.
- Requests only run while the game is unpaused and a prison is loaded. A timeout usually means paused or a menu.
- `pa_lua` runs Lua 5.1 in the mod's world script (`mod/ai_bridge/data/world.lua`). Available: `Game.*` (~85
  functions: SetZoneRoom, SaveMap, SpawnPrisoners, CamMove, SetMaterial, ...), `WorkQueue.Request(kind, ...)`
  (Construction, PlaceObject, MoveObject, DismantleObject, DumpObject, SellObject, RepairObject, SearchObject,
  EscortPrisoner), `World` (GetCell, ObjectIds, NumPrisoners, Capacity), `Object.*`, `Objective.*`, plus `api`,
  `json`, and `mem` (persists between calls). `io`/`os`/`require` are removed by the game.
- Coordinates are map cells, x right, y down.

## Unexplored (do this first when extending the API)

Run `.\.venv\Scripts\python.exe scripts\explore_api.py` (writes `runs\api_explore.json`) to learn how to list
objects, read money, hire staff, set research/regime. Put new helpers in `api` in world.lua, copy the mod to
`%LOCALAPPDATA%\Introversion\Prison Architect\mods\ai_bridge`, reload the prison, and add a matching MCP tool in
`src/pa_agent/bridge/mcp_server.py`. Record live results in docs/validation.md.

## Install / uninstall

- Install: `native\bin\GLU32.dll` into the game folder; mod folder as above; enable "AI Bridge" in Extras > Mods.
- Uninstall: delete `GLU32.dll` from the game folder.
- The DLL only patches the exact Steam build `The_Jailhouse_1.02` (r11056); on other builds it only forwards GLU.
