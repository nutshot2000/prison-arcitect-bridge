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

## Follow-up 5 — 30 September 2026: unlocks, new rooms, a riot, and a stalled expansion

- `unlock laundry|janitor|chief` printed the research chains correctly against the live research state
  (Maintainance by the Warden → Foreman + office → PrisonLabour/Cleaning). `research Maintainance` started and
  finished (the Foreman shows as hireable in the game's staff menu).
- `todo` now prints a `do:` command under each game To-do item plus the worst needs. `next` adds the research
  ladder and chapel/common room for Spirituality/Recreation, and demotes "station nearly full".
- `room parole 83 10 89 16` built and zoned a ParoleRoom. Real room type names checked against `roomtypes`
  (Chapel, CommonRoom, ParoleRoom, Laundry, Classroom, Workshop, Library, CleaningCupboard all exist).
- Riot (day 27): 13 of 14 guards and the Warden down, 42 of 86 hungry, 32 injured. `next`/`auto` counted the
  unconscious guards as on duty; now only guards on their feet count and replacing them goes to the top.
  Hired 12 guards + 2 doctors by hand.
- Stalled expansion: fence moved west (40..147) and the chapel/common room ordered at x 44..53 BEFORE the old
  fence line at x=62 was opened. The 180 room jobs were unreachable; workmen kept hauling their bricks/concrete
  to the fence and dropping them (a brick stack ended up outside the fence at 46,7), and the 70 paving jobs on
  the old line never got materials. `progress`/`problems` now report UNREACHABLE construction jobs from the save
  (flood fill from the workmen through non-wall cells), and `room`/`cells`/`solitary`/`building` refuse to order
  anything no workman can reach.
- DO NOT write `World.GetCell(x, y).Mat` from Lua: it reads back as written, but the game crashed within a minute
  after 69 fence cells were changed this way. Recovery: the same change made offline in a copy of the autosave
  (`agent_fixed.prison`: old fence cells at x=62 → ConcreteTiles).

## Follow-up 6 — 30 September 2026: DLL 0.5 (emergencies, grants), tunnels, research

- Emergencies: the Emergencies buttons dispatch through one switch (0x1401f7b44). Contraband manager =
  world+0x21a0; start(c, tunnel, drugs) 0x1405021f0, stop 0x140503ec0, announce 0x140502130; Bangup
  0x1407c7c30(world) (flag world+0x5dc = regime Bangup), Lockdown 0x1407c77e0(world) (world+0x4612).
  `emergency tunnelsearch` ran live (state went active, then finished).
- Tunnels (save section `Tunnels`: Dug/Entrance/Discovered): 3 tunnels from toilets in a dormitory and the cell
  block to outside the fence explained 9-12 escapes a day. The tunnel search and SearchObject jobs on the toilets
  only marked the exit holes outside as discovered; the inside entrances stayed hidden. `report` now counts a tunnel
  as found only when its inside entrance is. Dogs (Security → Patrols → Dogs) are the next thing to try.
- Grants: world+0xd90 is the Grants object (catalogue +0x30, state records +0x40: state 0 available, 1 accepted,
  2 completed). AcceptGrant 0x1405cdd20(grants, &name, 1, &emptylist) after the UI's lock check 0x1405cdbc0.
  Live: bootstraps +$30,000 (completed at once, the To-do "Accept your first Grant" cleared), Health, Visitation,
  Administration, Maintenance accepted; two more refused by the game's limit on grants running at once.
  `Objective.CreateGrant` from mod Lua does nothing visible (the catalogue already holds the grant).
- CEO letter: the letter window removes objective ReadCeosLetter with 0x1406717f0(world+0xc88, &name, 0) and sets
  world+0x46dc; `Objective.Complete('ReadCeosLetter')` did not clear it. DLL 0.5.1 `read_letter` (not tried live yet).
- Research: Maintainance, Cleaning, PrisonLabour, MentalHealth, Security, Finance done; Foreman, Chief, Accountant,
  Psychologist, 3 Janitors hired, 5 offices (one per department head).
- Mistakes fixed: an office ordered over the new solitary block replaced its dividers/doors (three times, twice
  because of the next bug); `room`/`building`/`cells`/`solitary` now refuse rectangles over zoned rooms or ordered
  work. `reload-mod` left the OLD code answering while the game was paused (the DLL runs the pump registered at
  hello); it now calls the new chunk's `hello()`, and a paused reload was verified to refuse the overlap.

## Follow-up 7 — 2 October 2026: an hour of autonomous play (Claude via MCP), fixes from it

Fresh 150x120 map, played day 1 → day 8 through the MCP tools: 50 cells, 2 kitchens/canteens, 5 power stations,
laundry, workshop, classroom, library, chapel, infirmary, CCTV room, kennel; 41 prisoners; 8 grants completed.
Problems hit, and what changed:

- **Power hookup tripped stations three times.** (1) The kitchen cable ran under the other cookers, which got power
  without being counted; (2) estimated loads were low (pump 20 vs 25 measured); (3) a built station's Demand only has
  what is already powered, so cable still to be laid was not counted and a second `hookup` (`auto`) added more.
  `api.hookup` now tracks every cell an object covers (`object_feet`, footprints from `SIZE`), charges a route for
  each unpaid object it runs under (and tries the other L-route when that does not fit), subtracts not-yet-powered
  objects on a grid, and uses loads fitted to live Demand: 3 cookers + 2 fridges = 50, pump + 2 TVs = 27, saw + press
  + TV = 21, 3 laundry machines = 30, 2 CCTV monitors + 3 cameras = 23. Lua test: a fridge whose straight route runs
  under a second cooker fails on the old code ("cable under the unpaid cooker at 20,41") and passes now.
  Live after reload: `hookup power` on the running prison connected 2 objects (2 cable pieces), no trips.
- **A tripped station read "OFF, demand 0/50".** `power` / `problems` now flood-fill the save's cables from each station
  and list what is on its grid (`grid_loads`); on the day-6 save the estimate equals the game's Demand on all four
  grids (50, 27, 44, 30).
- **A fence line replaced a shower's brick wall** (fence round Deliveries along x=125). `build_area`/`build_line` and
  `perimeter` skip cells that have, or are ordered to get, a non-fence wall. Live: Fence over the kitchen's west wall
  → queued 0, kept 8.
- **`problems` listed every station and road gate as "ORDERS never built"** (centre further from the ordered cell
  than the match window). Fixed with per-type reach; unit test.
- **Grant refusals said "unknown, already taken, or too many at once".** `api.grant` now says which: unknown (lists
  the available ones), already accepted, completed, locked, or too many running (2 at once, 3 after ExtraGrant:
  observed live — a third was refused at 2, three ran at once after ExtraGrant). Live: Foo, EnhancedSecurity
  (running), Bailout (locked), bootstraps (completed) each got the right message. The "too many" branch was not
  triggered live.
- **`pa_wait` 90 s came back "Request timed out"** from the MCP client. MCP `pa_wait` is capped at 55 s per call.
- Not in the bridge (needed the game UI via screen control): guard patrols, prisoner job slots, reform programs.
  In Deployment > Patrols a short drag with Assign Guards added 12 guard slots.

Tests: 52 Python tests and `mod/test_world.lua` (LuaJIT via lupa 2.8) pass.

## Follow-up 8 — 2 October 2026: room requirements from the game

- The kennel built by `building` + `zone` (5x4 inside, no crate) never worked; the game's tooltip said
  "[FAILED] Minimum Size 5 x 5", "[FAILED] Dog Crate", and `rooms`/`problems` said nothing (no Kennel entry in
  `ROOM_REQS`). The game's room definitions are in `data/materials.txt` inside `main.dat` (a RAR archive).
- New `room_rules.py`: extracts and parses every `BEGIN Room` block from the installed game with UnRAR (38 rooms)
  into `runs/room_rules.json`; game data stays out of the repo. `rules [room|refresh]` (MCP `pa_rules`) prints them;
  `room` refuses a rectangle below the minimum; `room_problems` uses the game's rules over the hand-written ones
  (which gained Kennel, Armoury, Solitary). `room kennel|armoury|security` furnish to the requirements
  (DogCrate 1x2, WeaponRack 2x1 from materials.txt).
- Live: `rules refresh` read all 38 rooms; `problems` then flagged the hand-built armoury (missing WeaponRack,
  GuardLocker, Table), fixed with `furnish armoury`. The rebuilt 6x6 kennel with 2 crates passes. Learned from the
  data: kitchen workers need the KitchenInduction program, workshop workers WorkshopInduction, library Academic.
- Tests: 56 Python, Lua tests pass (parser, cached extract, small-kennel report, room pre-check, new layouts).
- Phone booths had no power: they are `Properties Wired` (not `Electrical`) in materials.txt and were missing from
  hookup's list. Added (PhoneBooth, VisitorTableSecure); `hookup power` wired 7, all 7 powered after.
- Tunnels: the guards had found a 61-cell tunnel days earlier but it was never filled; meanwhile 4 diggers from the
  new south block (toilets at 123..135,92) dug along y=90 past the fence and 20 prisoners escaped in one day. A
  Remove Tunnels drag in the game UI created no fill job. `WorkQueue.Request("Construction", "RemoveTunnels", x, y)`
  on a dug cell does: tested on 116,77 (filled, floor stayed Dirt), then all 116 dug cells from the save were
  ordered and `tunnels` reported none ~1 game hour later. New `api.fill_tunnels`, verb `tunnels [fill]` (MCP
  `pa_tunnels`); `auto` fills tunnels; `report` now says `tunnels fill`.

## Follow-up 9 — 10 October 2026: guard patrols, DLL 0.6 (found with REA + Ghidra, checked live)

Static analysis of `Prison Architect64.exe` (r11056, sha256 cc460fc4...) with REA 6.3.0 on Ghidra 12.1.4; the
known AcceptGrant address 0x1405cdd20 resolves there, so the build matches.

- Save format (diffs of saves before/after drawing by hand, prison day 13): section `Patrols` lists route cells
  `"x y 0"  Set true  PatrolType n  [PriorityLevel n]` (Blue Patrol = 0, Magenta Patrol = 1; PriorityLevel omitted
  when 0) and `Patrols > Stations`, one per Assign click: `Pos.x Pos.y Pos.aboveGround  LastVisit  EntityType
  Guard|DogHandler  PatrolType  PriorityLevel  Schedule -1  Visitor.i/u` (a guard was visiting within minutes;
  Visitor -1 = nobody yet). Each Prioritize drag raises the whole route one level (user: blue once -> 1, magenta
  twice -> 2), and its stations take the same level. Assign Armed Guards needs Armoury.
- Code: PatrolSystem = world+0x1228; Patrols-tab drags are applied ~40 cells/s by 0x1404d3470(?, drag).
  Cell records +0x30 (0x30 bytes, index y*W+x, +W*H above ground; 0x140681f80(ps,x,y,z) returns one):
  Set u8 @0x18, @0x1c = 0, PatrolType i32 @0x28 (-1 none, 0 blue, 1 magenta, 2 both), PriorityLevel i32 @0x2c
  (max 2); ps+0x58 = 1 after changes. Stations +0x38 (count +0x44, 11 i32: x, y, z, entity code, 0, -1, -1,
  Schedule, PatrolType, PriorityLevel, ...), ps+0x59 = 1 after changes; add 0x140683dd0(ps,x,y,z,schedule,code),
  remove 0x140683ed0(ps,x,y,z,0,type|-1). Assign tools 0xc..0xf use codes 0x69, 0x78, 0x6b, 0x6f; live:
  105 (0x69) = Guard, 120 (0x78) = DogHandler (0x6b/0x6f probably ArmedGuard/Orderly, untested).
  Connected route: 0x140684330(ps,&xy,z,&prev{-1,-1,0},type) fills +0x48 (count +0x54); 0x140684170(ps,&xy,z,type,up)
  moves that route's PriorityLevel and its stations' one step.
- Correction: 0x1404d5260 (writes world cells +0x40/+0x41/+0xcc, tools 0x13/0x14) is the Deployment tab's
  painter, not patrols. "PatrolSet"/"PatrolClear" are only sound events (bank `_Deployment`).
- DLL 0.6.0: `patrols` (read) and `patrol:route|clear|assign|priority`, mirroring 0x1404d3470; Lua
  `api.patrols()` / `api.patrol(...)`; verbs `patrols`, `patrol` (MCP `pa_patrols`, `pa_patrol`). Live on the
  day-13 prison: `patrols` matched the save (42 cells, Guard 105 at 105,54, DogHandler 120 at 108,48);
  `patrol route magenta 96 51 101 51` + `assign guard 98 51` + `priority up 98 51` -> the save had the 6 cells
  `PatrolType 1 PriorityLevel 1` and a Guard station with a guard already visiting; the other routes kept their
  levels; `patrol clear 96 51 101 51` removed the cells and the station (save checked). No crash, game kept running.
- Not done: `both` (type 2) routes, diagonal/L lines (draw two straight ones), above-ground cells, Armed/Orderly
  codes, deployment sectors (the Deployment tab).

Tests: 57 Python tests and `mod/test_world.lua` (LuaJIT via lupa 2.8) pass.

## Follow-up 10 — 10 October 2026: To-do panel gaps, DLL 0.6.1 (REA + live check)

The save has no objective state (its `Objectives` section is empty); the panel's figures are in memory:
- Grant parts: objective records (world+0xc88) are completed by 0x140676030, which sets done u8 @0x104, plays
  `ObjectiveCompleted` and pays (advance @0xf4, completion @0xf8, paid @0xfc). `objectives` now returns
  `name[<parent]|done|advance|completion`. Live: Administration offices/Warden done, Accountant_Research/Accountant
  not; Health Ward/Doctors done, Psychologist not; $5,000 / $10,000 — exactly the panel (user screenshot).
- Exhausted staff (0x1402da200): the panel prints world+0x46d8 (exhausted) and +0x46d4 (resting). The save-based
  Energy < 15 estimate said 6 where the panel said 3 (1 resting); `todo` now uses the live counts.
- Intake (0x1402d8420): strike world+0x2930 == 1, riot +0x20e4 (each unless +0x1a58); otherwise
  0x140665020(world+0x1778) open -> arrivals 0x140669440(same) at hour +0x1a54, else "closed to new inmates".
  New native `todostate` / `api.todo_state()`. Live: intake closed, as the panel showed.
- `todo` shows the grant sections ([x] done / [ ] to do, money, `unlock` hints) and the intake state.

## Follow-up 11 — 10 October 2026: catalog of everything buildable; floor / wall / place verbs

- The game defines 147 materials and ~600 objects (base `data/materials.txt` + `data/materials_dlc.txt`, DLC packs
  PrisonWingPriviledges, SeaAirLand, FreeContentPack_1); toolbar names are in `data/language/base-language.txt`
  (`material_<lowercase>`) and `d11.txt` (DLC, mixed case). The bridge knew 42 materials and 41 object sizes, and
  the easy front end had no verb that laid floors or walls at all (only `pa-agent lua "api.build_area(...)"`).
- `catalog [floor|wall|object] <words>` / MCP `pa_catalog`: name, toolbar name, size, cost, research, power/water,
  DLC. Parsed from the installed game into `runs/catalog.json` (git-ignored); 748 entries: 69 floors, 47 walls,
  426 objects (+ items, characters, vehicles, engine-only materials, which search leaves out).
- New `floor <Material> x1 y1 x2 y2` and `wall <Material> x1 y1 x2 y2` (line or outline), MCP `pa_floor`, `pa_wall`,
  and `pa_place` is back. All three resolve names against the catalog (case-insensitive, or the toolbar name such
  as "Dark Wood Floor") and refuse unknown ones with suggestions; `place` also accepts movable items
  (LaundryBasket). Every object name the bridge itself uses resolves.
- Live (day 13 prison): `floor "Dark Wood Floor" 110 11 111 12` (DLC floor, given by its toolbar name) and
  `place Plant 112 13` on Dirt; one game minute later all 4 cells read DarkWoodFloor and the Plant was
  installed (user's screenshot showed both).

Tests: 61 Python tests pass (4 new catalog tests on hand-written data in the game's format).

## Follow-up 12 — 10 October 2026: Deployment (read-only for now)

- Save diff after one click each (user, day 13): Assign Guards / Cooks / Dog Handlers add a post to the clicked room's
  sector (`Sectors > Sectors > [i n] > Stations / CookStations / DogStations > [i k] Entity.i`, -1 until a worker
  takes it; a guard and a cook took theirs at once), a `DeploymentSchedule > Schedules > "Schedule 0"` entry
  (SectorId, Num<Type>, PriorityLevel) appears, Prioritize Area raised the yard sector to PriorityLevel 2 (two
  clicks), and Max Sec Only set `Zone MaxSecOnly` on the whole yard sector (one click applies to the whole sector;
  no cells change). 49 sectors (NextSectorId 217 is only the next id).
- Code: sector save 0x1407183b0 - post vectors guard +0x80, dog +0x98, armed +0xb0, cook +0xc8, doctor +0xe0,
  janitor +0xf8, gardener +0x110, farmer +0x128, orderly +0x140, CustomZone0..11 bytes +0x1bd. Patrols and the
  direction arrows go through the drag dispatcher 0x1404dbee0 (case 8; tools 0x13..0x15 -> 0x1404d5260 paints cells
  +0x40/+0x41/+0xcc). The Deployment-tab clicks were not found: they appear to go through the network command
  layer (SectorZoneChange, GuardDeploymentChange, SectorJobCountChange are registered by name in 0x140030e40).
  Writing sector data directly is NOT done: the schedule may rebuild posts at shift change, and a direct Mat write
  crashed the game before (follow-up 5).
- `deployment [all]` / MCP `pa_deployment` (read-only, from a fresh save): per sector the room, zone (with its
  meaning, and a WARNING when a one-category zone is on a shared room such as the Yard), posts (manned / total),
  priority, custom zones. Live output matched the test exactly. Only MaxSecOnly was seen in a save; the other zone
  names are from the game's `CanEnterCell: Can't enter Zone<X>` strings.

Tests: 62 Python tests pass.

## Follow-up 13 — 10 October 2026: Logistics (read-only)

- The Logistics tab's Min/Med/Max/SuperMax Sec Grading, Room Quality and Cell Status are views: a save before and
  after using them changed nothing (the grading panel shows the sector grade, e.g. Med Sec 85/250, from privileges,
  facility quality and conditions). Food / Laundry Distribution need AdvancedManagement (researched through the
  bridge, $1,000, a few game minutes). There is no laundry room, so Laundry Distribution has no lines.
- Food Distribution is stored on sectors, not rooms (room `Connected` lists stay empty): a kitchen sector's
  `Targets` = canteen sector ids it supplies (always saved); a cell block / dorm sector's `Targets` = the canteen it
  eats at, saved only when set by hand, with `ManualTargets true`. In the view dashed lines are automatic, solid ones
  manual. User test: north kitchen 6 -> south canteen 119 (manual; kitchen 112 then supplied both canteens),
  dorm 109 -> canteen 8, dorm 111 -> canteen 119. Changing it goes through SectorAddTarget / SectorClearTargets
  (network command layer, like Deployment), so the bridge does not write it.
- `logistics` / MCP `pa_logistics`: kitchens -> canteens (with [set by hand]), canteens no kitchen supplies (WARNING),
  eating areas set by hand, and a note when no laundry exists. Live output matched the user's screenshot.

Tests: 63 Python tests pass.
