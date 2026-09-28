# Validation — 19 September 2026

## Confirmed

Environment: Windows 11 build 26200, Python 3.12.10, psutil 7.2.2, MSS 10.2.0. Game: `The_Jailhouse_1.02`, Steam build manifest `10630057`.

**24 automated tests pass.** Coverage includes client boundaries, negative desktop origin, crop bounds, invalid durations, configuration validation, dry-run injection suppression, process-path mismatch, focus-loss refusal, drag/key cleanup, stop during drag, blocked OS chords, held modifiers, Unicode event pairs, ordered records, mandatory session context, 64-bit INPUT size and native DPI initialization.

**Real game test:** the installed PA-Agent CLI found PID 7244 and HWND 11929686, measured a 1920×1080 client at desktop (9,115), and reported DPI 120 (125%). Those IDs and positions are historical test evidence, never configuration constants.

| Test | Result | Local evidence |
| --- | --- | --- |
| `doctor` discovery | Correct executable, running process, window and save folder | Captured CLI output during test |
| Full screenshot | Visually confirmed main menu; client only, no title bar/borders | `runs/20260919T155119-9e0d1321/` |
| Dry-run input-test | Returned `input_sent: false`; event and evidence frames saved | `runs/20260919T155131-b7003ba3/` |
| Live client-relative click (1113,673) | Options menu visibly opened | `runs/20260919T155145-d76cc7ab/` |
| Live Escape key | Main menu visibly restored | `runs/20260919T155157-076101fa/` |
| Focus loss | Later capture/input attempts refused when game was background | CLI returned explicit foreground error |
| Stop watcher | Real Windows hotkey registration succeeded; temporary stop file latched within 1 second; zero injected events | `scripts/check_stop_watcher.py` |

Game actions above were performed by this project's Python controller, not substituted with another automation tool. Computer Use was used later for window observation/focus recovery; that recovery did not establish persistent foreground ownership for subsequent CLI calls.

These paths are local test evidence under ignored `runs/`. They are intentionally absent from the distributable source ZIP. The source package contains no game screenshots, saves or extracted game scripts.

## Not established

- Physical Ctrl+Shift+F12 end-to-end emergency-stop activation (registration and stop-file path tested).
- In-game drags, right/middle/double clicks, wheel/panning, text entry or object placement. These paths are implemented; unit tests cover validation/cleanup, not all game behaviors.
- Live cropped screenshot: attempted after focus was lost and correctly refused; crop bounds are unit-tested.
- Windows `SetForegroundWindow` recovery under every focus policy: a live focus request was refused. Select the game manually when Windows prevents foreground changes.
- Exclusive fullscreen, borderless mode, multiple monitors with mixed DPI, overlays and GPU-specific capture behavior.
- Construction verification, camera calibration, save parser, mod telemetry, MCP clients and autonomous gameplay. Those milestones are not implemented.
- Clean installation on a second PC.

## Re-run

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check_stop_watcher.py
.\.venv\Scripts\pa-agent.exe doctor
.\.venv\Scripts\pa-agent.exe screenshot
.\.venv\Scripts\pa-agent.exe --dry-run input-test
```

For live input, place the game in the foreground, inspect the newest screenshot, then choose a harmless operation with `--live`. Do not reuse the coordinates above if the resolution, UI layout or screen has changed.

# Validation — 23 September 2026: save parser and Lua capability probe

## Save parser (`pa_agent.state`)

5 unit tests pass (synthetic fixture; no game data in the repo). Live parse of local saves: pa4 (0.5 MB) 0.04 s, autosave (0.9 MB) 0.04 s, MaxSec_Ironfort (13.5 MB) 0.84 s: 370 prisoners with names/positions, 13 staff types, 24 room types, research state. `pa-agent state [save] [--full]` added (CLI run on Windows not yet tested; tested via the Linux VM with Python 3.10 and a tomllib stub).

## Lua probe (`mod/ai_bridge_probe`)

Installed into `%LOCALAPPDATA%\Introversion\Prison Architect\mods`, enabled via Extras > Mods (stored as `Mods "AI Bridge Probe"` in preferences.txt). Probe object injected into a copy of pa4 (`probe_inject.prison`); results read back from the user's `probe.prison` save. Script properties persist in the save: object scripts under their object, `data/world.lua` under `BEGIN WorldScripts`.

| Capability | Object script | World script (`data/world.lua`) |
| --- | --- | --- |
| io / os / debug / package / require / loadfile / dofile | nil | nil |
| loadstring, load, setfenv, getfenv, string.dump, coroutine | available (`loadstring("return 6*7")()` = 42) | available |
| Game | DebugOut, Time only | ~85 functions incl. SaveMap, Pause, GetGameSpeed, Spawn, SpawnPrisoners, SetZoneRoom, SetMaterial, SetProperty/GetProperty, GetObject, GetNumRooms, GetRoomCondition, SendEntityToPos/Room, Cam*, Delivery, SetIntakeOpen |
| WorkQueue.Request | nil (documented but not bound) | works: ConcreteWall at (20,20) and a Bench were queued and then **built by workmen** (confirmed in save) |
| Objective / Trigger | nil | available |
| World | GetCell, ObjectId(s), DataRegistry; NumPrisoners/Capacity are tables, not functions | same |
| Object | Spawn, Delete, Get/SetProperty, NavigateTo, GetNearbyObjects, CreateJob... | same |
| Interface | available | nil |
| DebugOut / F3 debugger | no window appeared; nothing written to debug.txt | same |

Conclusions: the world script is the in-game "hands" (building, zoning candidates, spawning, camera, pause, on-demand save). Output can leave via saves (`Game.SaveMap` untested). There is still **no live input channel**: nothing outside the game can hand the script a command without a save reload. A native helper that runs Lua in this world-script environment is the remaining gap.

Input note: computer-use clicks/keys were unreliable in the game menus at 125% scaling (clicks offset, then ignored); the manual steps were done by the user.

# Validation — 23 September 2026: first live bridge run

Bridge DLL 0.2.1 (installed as `GLU32.dll`), mod AI Bridge (runtime 0.2.0), user's Windows PowerShell, new sandbox prison, game unpaused.

- 0.2.0 crashed at startup with `0xC0000139` (entry point not found) before its DllMain ran: something in the process loads `glu32.dll` by name and needs exports beyond the 6 the exe uses. 0.2.1 forwards all 52 glu32 exports and starts normally.
- `pa_bridge.log`: loaded, `Game.DebugOut` patched, listening on 127.0.0.1:8972, runtime hello received.
- `pa-agent bridge` → `{"patched": true, "lua_seen": 1, "ms_since_poll": 0, "game": {"pong": true, "time": 57502.26}}`.
- `pa-agent lua "return api.build_wall_rect('BrickWall', 10, 10, 15, 14)"` → `{"queued": 18}` (correct outline count). Construction by workmen not yet visually confirmed.

Not yet tested live: MCP server with a real client, `pa_snapshot` (`Game.SaveMap` path), `api.zone`, `api.camera`, behavior while paused.
