# Prison Architect agent bridge — notes for agents

Read AGENTS.md for repo rules. To PLAY, read docs/START-HERE.md first (build order + rules learned live).

## The live game

- Easy front door: `.\prison.ps1 <verb>` = `.\.venv\Scripts\pa-agent.exe play <verb>` (help, status, next, report,
  look, space, room, cells, fence, station, place, hookup, power, switch, utilmap, zone, rooms, hire, research,
  intake, pause, resume, wait, progress, save, screenshot, lua). Same verbs as MCP tools `pa_*` (`pa-agent mcp`).
- Loop: `status` → `next` → one action → `wait 60` → `report`. Set `intake beds` first.
- `report` / `utilmap` / `rooms` / `next` save the game (`pa_agent_snapshot`) and parse it
  (`src/pa_agent/state/report.py`). `screenshot` gets the last rendered frame from the DLL (works behind windows).
- Raw: `pa-agent call <fn> [args]`, `pa-agent lua "return api.help()"`. Requests work while paused (DLL ≥ 0.3).
- Coordinates are map cells, x right, y down. Objects ordered at x cover x..x+w-1; beds (h 2) at y cover y-1..y.

## Architecture

- `native/pa_bridge.c` → GLU32.dll proxy (build: `sh native/build.sh`, zig or clang). Patches `Game.DebugOut`,
  TCP 127.0.0.1:8972 (8 clients), native actions via `Game.DebugOut("\1cmd")`: zone, roomtypes, speed/setspeed,
  save, research, intake, screenshot. Addresses are for Steam build r11056 only and are byte-checked at start.
- `mod/ai_bridge/data/world.lua` → `api.*` (room, cell_block, perimeter, hookup, utilities, switch, hire, zone...).
  Test offline: `python <lupa runner> mod/test_world.lua mod/ai_bridge/data/world.lua` (see docs/validation.md).
- `src/pa_agent/bridge/` → client.py (TCP), easy.py (verbs + hints), mcp_server.py, image.py (BMP→PNG).
- `src/pa_agent/state/room_rules.py` → the game's room requirements, parsed from the installed game's
  `main.dat` (RAR; `data/materials.txt`, needs WinRAR/UnRAR) into `runs/room_rules.json`. Never commit game data:
  only the parser and hand-written fallbacks (`ROOM_REQS` in report.py) are in the repo.

## Developing

- After editing world.lua: `pa-agent reload-mod` loads it into the running game (planned-work tracking restarts).
  Install for real with `scripts\install_bridge.ps1` (game closed; also copies the DLL).
- New game internals: disassemble with capstone (see docs/validation.md for the addresses found), then verify live.
- Game facts: power station 50 capacity; loads cooker 12, fridge 7, pump 25, laundry 10, saw/press 10, TV 1
  (fitted to live Demand; `LOAD` in world.lua and `POWER_LOAD` in report.py must agree); a cable under any cell of
  an object powers it; one station per grid (`Overloaded 2` otherwise), player
  on/off field is `Switch`; the pump needs power; UI tool names (Building, Demolish, CancelJobs) are not materials.
- Record live tests in docs/validation.md. Never push without asking the user.

## Install / uninstall

- Install: `scripts\install_bridge.ps1` with the game closed; enable "AI Bridge" in Extras > Mods.
- Uninstall: delete `GLU32.dll` from the game folder (the previous one is kept as `GLU32.dll.bak`).
