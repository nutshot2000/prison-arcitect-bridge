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

# Validation — 28-29 September 2026: bridge 0.4 played live

Setup: DLL 0.3.0 → 0.3.2 (built with zig, `native/build.sh`), mod world.lua 0.4.0, sandbox prison 150x120 with the
road at x 139-143. Played for 9 game days through the bridge (CLI `pa-agent play`, hot-reloaded with
`pa-agent reload-mod`). 42 Python tests + the Lua tests (`mod/test_world.lua`, run under LuaJIT via lupa) pass.

## Verified live

| Feature | Evidence |
| --- | --- |
| Several clients at once (MCP server + CLI + scripts) | `clients` in STATUS; explore script no longer hangs |
| Requests while paused (frame-hook pump) | clock frozen, `pumped` counter rising, answers returned |
| Pause / resume / speed (`world+0x88`) | clock stops/advances; game UI follows |
| Money (`World.Balance`), clock (`TimeIndex` = game minutes) | matches the in-game header |
| Zoning (game's SetZoneRoom handler, no campaign) | save shows `RoomType HoldingCell/Cell/Kitchen/...`; game uses the rooms |
| Save (Save-menu writer) | `saves/agent_test.prison` written in ~1 s |
| Research list/start (game's StartResearch, pays the cost) | Health started by the Warden, finished, Doctors hired |
| Intake (`intake beds` → game's SetIntakeType 1) | game's Intake panel: "Fill to capacity, closed to new inmates" |
| Screenshots (glReadPixels from the render loop, DLL 0.3.1) | PNGs of the live prison while the window was behind others |
| Hiring at the game's price (Object.Spawn + Balance) | staff walk in from the road, balance drops by the listed price |
| Cables / pipes (PlaceObject ElectricalCable / PipeLarge / PipeSmall) | appear in the save's Electricity / Water sections |
| Power stations: player switch is `Switch`, trip sets `Overloaded` | 1 = over 50 demand, 2 = two stations on one grid |
| PowerSwitch split (`switch x y off`) | kitchen grid 40/50, main 30/50, pump 26/50, all ON |
| Perimeter fence with RoadGate | escapes fell from 23/day to 0 |
| report / utilmap (from a fresh save) | matched what the game showed (drops, bolts, injured staff) |

## Bugs found by playing and fixed (each has a regression test)

- Furniture anchor: an object ordered at x covers x..x+w-1 (was treated as right-anchored: tables through walls,
  benches in doorways).
- Cell block floor ordered after the dividing walls replaced them (one long room, no cells).
- Walls ordered on door cells were built over finished doors (kitchen and shower sealed).
- Walls + floor built separately stay outdoor (`Ind` unset): prisoners reported `FailedToFindCell`. Rooms are now marked
  indoor like a finished foundation.
- `Building`, `Demolish`, `CancelJobs` are UI tools; the work queue builds them as literal materials. Refused now.
- hookup: capacitor is not a source; the map's street lights (ExternalPower) must not be cabled; existing cable/pipe
  is read from a save and reused (was re-buying 150+ pieces after a reload).
- Water pump needs power; a power station trips above 50 (a cooker ≈ 10); two stations on one grid trip each other.
- find_space offered ground outside the fence, on top of power stations, and on the yard.
- The easy report read `"true"` strings as false (parser keeps text).

## Still open

- Intake type 2/3 (max total, per day) set but not yet observed through a day change.
- `utilmap` draws objects over the cable under them (read neighbours).
- Canteen seat count vs prisoners is estimated (4 per bench), not measured.
- Camera control and the regime are not available.
- The first test prison had 41 escapes and 6 deaths before intake/fence/beds were fixed; the build order in
  `docs/START-HERE.md` avoids that.

## Follow-up — 29 September 2026 (after restarting Claude Desktop and the game)

- New MCP server: pa_connection, pa_intake, pa_report, pa_next and pa_screenshot (image returned inline) all worked.
- `intake beds` survived a game restart (it is stored in the save) and held over a day change: day 12 10:40 →
  day 14 00:05 at speed 5 (including the 08:00 intake), prisoners 65 → 60 with 58 beds, no new arrivals.
- `todo` rebuilds the game's To-do panel from the save; checked line by line against the in-game panel (intake,
  parole 29, visitors 65, solitary 63, lockdown 1, injured 6, exhausted 1). Adds the prison temperature (riot risk).
- utilmap water layer drew no pipes (PipeType is text in the save); fixed, with a test.

## Follow-up 2 — 29 September 2026: growing the prison with the easy verbs

Day 12 → 17, 59 → 82 prisoners, all through `pa-agent play`. Built live: 6 solitary cells, visitation room, staff
room DrinkMachine, bins, sprinklers, fence moved west (old line paved), third dormitory, second kitchen on its own
station, third canteen, 7-head shower block. Results: prison temperature 100 → 0, solitary queue 63 → 1, 82 beds for 82
prisoners, holding cell empty, profit $16.9k/day, 0 escapes. The game's To-do panel lost the waste, fire and staff
exhaustion items. A standard kitchen (3 cookers + 2 fridges) measured exactly 50/50 on its own station.
Fixed along the way: fence re-run no longer orders a second RoadGate (two had been installed; dismantled);
`todo` hints follow the rooms that exist.

## Follow-up 3 — 30 September 2026: DLL 0.4.0 live

- regime: the schedule everyone follows is the **Normal** category (array index 2; others "Unspecified" follow it).
  `regime balanced` wrote it; the game's clock panel switched to FreeTime and the save shows the new hours.
- camera: `view x1 y1 x2 y2` moved the player's view and screenshotted the close-up.
- rmcable / rmpipe: removed the dead road-light cable (131-137,10) and one sprinkler pipe; stations unaffected;
  hookup re-laid the pipe.
- finance ledger: `spend:-1` took $1 (negative = expense); hires now go through it and show in the day's profit.
- Yard "Secure" check (flood fill from the yard to the map edge) found two 1-cell perimeter holes at x=138 beside
  the road gates (left when a duplicate gate was dismantled); fenced.
- Kitchen "Sink: Working Position Cannot be Reached": bottom-wall objects faced down into the wall. Layout now
  faces them up; both kitchens fixed live, warning gone.
- Order verification matches an object on the ordered footprint; a Bed ordered on a wall cell was installed across it
  (the game accepted it) and `remove` dismantled it.

## Follow-up 4 — 30 September 2026: power hookup that cannot trip stations

- Incident: a raw `api.hookup("power", {})` (no known cells) could not see the existing network and ordered 118
  cables, joining four grids; four stations tripped (`Overloaded 2`). Recovered by pausing, saving before and after
  the cables were laid, diffing the two saves (86 new cells), `rmcable` on each and `power on`. The raw call now
  refuses an empty cell list when stations exist.
- `hookup` now floods the network into grids, marks the grids that hold a station (or a planned one), computes each
  grid's headroom (50 minus the connected users' load) and only wires a user to a grid with a source and room for
  it. Routes are tried both ways round (x-then-y, y-then-x) and rejected if any cell touches another sourced grid.
  A user on a cable island (line cut from its station) counts as unconnected.
- Live: the second staff room (TV 71,71, DrinkMachine 76,71) had been cut off from kitchen2's full station (50/50).
  `hookup power` ordered 49 cables along y=71 and up x=93 to the station at 94,42 (40 → 41/50); every station stayed
  ON, the TV reads powered and the report shows nothing without power. Offline test covers a full near grid, a far
  grid with room, an island and the both-full case.
- Other fixes since 83e7323: bottom-wall objects face up; the MCP tool list trimmed to the easy verbs + `pa_api`;
  the report counts hungry prisoners and tired staff.
