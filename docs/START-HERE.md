# Start here: play Prison Architect through the bridge

The easy front door is one verb per call with a few lines of plain text back. When something fails you get
`ERROR:` plus a `HINT:` line with the usual fix.

```powershell
.\prison.ps1 help            # all verbs
.\prison.ps1 help room       # one verb, with sizes that work
```

In an MCP client (Claude Desktop, Claude Code) the same verbs are tools: `pa_status`, `pa_next`, `pa_report`,
`pa_look`, `pa_room`, `pa_cells`, `pa_fence`… Coordinates are map cells: **x to the right, y down, (0,0) top-left**.

## Before the first command

- The game runs with `GLU32.dll` 0.3.1+ in its folder (`scripts\install_bridge.ps1`) and a prison is loaded with the
  **AI Bridge** mod enabled (Extras > Mods).
- `.\prison.ps1 status` answers with money and a clock. Paused is fine: the bridge answers while paused.

## The loop

```
status  ->  next  ->  do ONE thing  ->  wait 60  ->  report
```

- `status`: money, clock, prisoners vs cell beds, staff, power/water state and any `PROBLEM:` lines.
- `next`: a numbered list of what the prison needs, as commands.
- `report`: what is going on inside. It shows where prisoners are, what they complain about, injured staff,
  escapes and fights today, and **DO NEXT** advice. Use it whenever things look wrong.
- `screenshot`: saves a picture of what the game shows (MCP: `pa_screenshot` returns the image). `utilmap power`
  / `utilmap water` draws cables and pipes and marks anything without power (`!`) or water (`t`).

## Build order that works (do the first four BEFORE the first intake at 08:00)

```powershell
.\prison.ps1 look                                   # where is the road? build west of it
.\prison.ps1 lua "return api.place_object('PowerStation', 96, 11)"      # 3x3; leave a gap to any other station
.\prison.ps1 lua "return api.place_object('WaterPumpStation', 120, 11)" # 3x3, needs power too
.\prison.ps1 fence 92 8 147 79                      # perimeter round EVERYTHING incl. deliveries; road gets RoadGates
.\prison.ps1 hire Guard 4
.\prison.ps1 room holding 110 20 118 27 east        # new prisoners wait here (jail door)
.\prison.ps1 cells 96 30 8                          # 8 cells, zoned
.\prison.ps1 room dormitory 119 48 133 62 west      # ~24 beds, the cheapest beds
.\prison.ps1 room kitchen 96 40 104 47 east         # then: hire Cook 2
.\prison.ps1 room canteen 106 38 117 47 west
.\prison.ps1 room shower 119 40 125 45 south
.\prison.ps1 room yard 96 50 115 61
.\prison.ps1 hookup                                 # cable + pipes to everything that needs them
.\prison.ps1 wait 120
.\prison.ps1 report
```

Then, as the prison fills (check `todo` / `report`):

```powershell
.\prison.ps1 solitary 73 36 6                       # punishments pile up without it -> riot risk (temperature)
.\prison.ps1 room staffroom 110 10 117 16 south     # needs a sofa AND a DrinkMachine (room places both)
.\prison.ps1 hire Warden
.\prison.ps1 room office 120 20 125 25 west
.\prison.ps1 research Health                        # then: hire Doctor 2, room infirmary ...
.\prison.ps1 room visitation 74 50 84 58 east       # families visit; calms prisoners
.\prison.ps1 room parole 83 10 89 16                # prisoners up for parole get their hearing here
.\prison.ps1 room chapel 44 10 53 19                # Spirituality (Altar + Pews + PrayerMat, 8x8+)
.\prison.ps1 room commonroom 44 22 53 29            # Recreation (TV, pool table, phone); hookup power
.\prison.ps1 unlock laundry                         # research steps for laundry / janitors / workshop
```

`todo` shows the game's To-do panel as text plus the **prison temperature** (riot risk). In the test prison it was
100/100 with 63 prisoners waiting for solitary; 6 solitary cells and a visitation room brought it to 46 within a day.
Out of space? Move the fence out (`fence` with the bigger rectangle), open the old fence line
(`remove fence x y1 x y2`) and **wait until it is gone before ordering anything beyond it**. Rooms ordered behind a
closed fence stall every workman (`room` refuses them now; `progress` shows UNREACHABLE jobs).

## Rules learned the hard way (live, 28-29 Sep 2026)

1. **Beds before prisoners.** Prisoners arrive every day at 08:00 whether you are ready or not ("All available"
   intake). With no cells, no guards and no fence they fight and walk off the map: the first test prison lost 41
   prisoners and 4 people died. Lower the intake in the game (Reports > Intake) until beds ≥ prisoners.
2. **Fence first.** `fence` around the whole prison, including Deliveries and Garbage by the road. Escapes dropped to
   0 once it stood.
3. **Power:** one PowerStation feeds **50**. Measured draws: cooker 12, fridge 7, water pump 25, laundry machine
   10, workshop saw/press 10 each, CCTV camera ~5, monitor ~4, TV 1. So one kitchen (3 cookers + 2 fridges) fills a
   station, and the pump plus a kitchen trips one. A cable under ANY cell of an object powers it (cookers and fridges
   are 2 wide). **Two stations on the same grid switch each other off** (`Overloaded 2`), whether they touch or are joined by
   cable. They do not share load. Give every station its own grid: put a `place PowerSwitch x y` on each cable between
   the parts and `switch x y off`. Check with `power`: each station should read under 50. A tripped station shows
   `PROBLEM: ... OFF` and a `TRIPPED` line with what is wired to it (a tripped station itself reads demand 0);
   `power on` resets it after you fix the cause. `utilmap power` shows the cables (objects are
   drawn over the cable under them, so look at the cells around them).
4. **No power, no water.** The WaterPumpStation needs electricity. Blue drops over toilets/showers in the game = no
   water; check `power` first.
5. **Never cable the road's street lights.** The map powers them itself (`ExternalPower`). `hookup` skips them now.
   Wiring them into your grid overloaded every station in the test prison.
6. **Toilets, showers and sinks need water; cookers, fridges, TVs and lights need power.** Run `hookup` after every
   new room. It reuses cable and pipe already in the ground, only wires power users to a grid that has a station
   with spare capacity (counting everything a new cable runs under, and work still to be laid), and never routes a
   cable next to another grid's line (that would join two stations). What it
   cannot connect safely is listed as `not connected`: add a station (`station`) and run `hookup` again.
   Never call the raw `api.hookup("power", {})` with an empty cell list: it cannot see existing cable and lays a
   second network over the first (the play verb passes the cells from the save; the raw call now refuses).
7. **Rooms are zoned by `room` and `cells`.** `zone` on an unfinished `Building` foundation does nothing: build
   walls + floor (the bridge marks them indoors) instead. Never order the UI tool names `Building`, `Demolish`,
   `CancelJobs` as materials: the game builds them as junk floor. The API refuses them now.
8. **Everything is built by workmen.** Nothing moves while paused, and injured workmen are slow. If `progress` stalls,
   `resume`, check money, and look at `report` for injured staff.
9. **A kitchen needs cookers, fridges AND a sink**, plus power, water and 2+ Cooks. `room kitchen` places all of it.
   One `room kitchen` (3 cookers + 2 fridges) draws exactly 50: **give every kitchen its own power station**.
10. **Scale with the prison** (measured at 82 prisoners): about 1 cooker + 1 cook per 10 prisoners, 1 shower head per
    10-12 (3 heads for 82 left Hygiene at 99; a 15x6 shower room adds 7), 1 guard per 6.
11. **The game's To-do items and their fixes** (`todo`): "not efficiently disposing of waste" → Bins (rooms place
    them now); "not equipped to handle a fire" → Sprinklers on water (kitchens/canteens get one); "staff exhausted" →
    a Staffroom WITH a DrinkMachine; long Solitary queue → `solitary`; families waiting → `room visitation`.
12. **Objects on a room's bottom wall face up.** A sink or fridge facing into the wall shows "Working Position
    Cannot be Reached" and is never used. `room` does this; if you `place` by hand, pass the facing.
13. **Grants: 2 at once, 3 after the ExtraGrant research.** `grant` says why the game refused one.
14. **Fences never replace walls.** A `Fence` line over a built or ordered wall leaves those cells alone (live: a fence
    round Deliveries turned a shower's east wall into fence). Prisoners walking through Deliveries pick up
    contraband; a fence with `StaffDoor`s round it was tried on 2 Oct 2026 (effect not confirmed yet).
15. **Not in the bridge: patrols, deployment, prisoner job slots, reform programs.** Use the game's Deployment,
    Logistics and Reform screens. In Deployment > Patrols, dragging Assign Guards along a route adds a guard slot for
    every cell it passes (one short drag added 12).
16. **`pa_wait` (MCP) runs at most 55 s per call**: clients drop tool calls after about a minute. Use speed 4-5.
17. **`rules <room>` gives the game's own requirements** (minimum size, enclosed/indoor, required objects, research,
    the program its prisoner workers need), read from your installed game the first time (`rules refresh` re-reads).
    `room` refuses a rectangle below the minimum, and `rooms`/`problems` say which requirement a room fails.
    Ones that bit live: Kennel 5x5 + DogCrate; Armoury WeaponRack + GuardLocker + Table; HoldingCell 5x5;
    kitchen workers need the KitchenInduction program and workshop workers WorkshopInduction (Reform tab).
18. **Tunnels: `tunnels fill`.** Found tunnels are NOT filled by themselves (one stayed open for days; 20 prisoners
    escaped through another in a day). `tunnels` lists them from the save, `tunnels fill` (and `auto`) orders workmen
    to fill every dug cell, found or not. Diggers start under cell toilets; keep dogs on a patrol.
19. **Phone booths need a cable** (`Wired` in the game data, not `Electrical`); `hookup power` wires them now.

## When something fails

`ERROR:` lines carry a `HINT:`. Common ones:

| Message | Meaning |
| --- | --- |
| `Cannot reach the bridge` | Game not running, or GLU32.dll not installed. |
| `timed out ... runtime has not connected` | No prison loaded, or the AI Bridge mod is not enabled. |
| `needs bridge DLL 0.3` | Old GLU32.dll: run `scripts\install_bridge.ps1` with the game closed. |
| `needs the Health research first` | `research Health` (needs a Warden with an Office). |
| `PowerStation ... is OFF (tripped)` | Too much on one grid or two stations touching; see rule 3. |
| `NOTHING WAS ZONED` | The cells are walls or unfinished foundation; wait for the floor, zone again. |

## Unlocking things (research) and the To-do list

Most staff and rooms are locked behind research. `unlock <thing>` prints what is still missing, in order, e.g.
`unlock laundry`: `research Maintainance` (the Warden) → `hire Foreman` + `room office` for him → `research
PrisonLabour` (the Foreman) → `room laundry`. Things: janitor laundry workshop library classroom doctor foreman
chief accountant psychologist cctv patrols metaldetector grants logistics, or any research name.

- Every department head (Warden, Foreman, Chief, Accountant, Lawyer, Psychologist) needs **their own Office**.
- Departments research in parallel, one item each; `next` suggests the next item per free head
  (Health → Maintainance → Security → Cleaning → PrisonLabour → Contraband → Patrols → ...).
- `todo` lists the game's To-do panel with a `do:` command under each item, then the worst prisoner needs and the
  room that answers them: Spirituality → `room chapel`, Recreation → `room commonroom`, Clothing → laundry,
  parole → `room parole`, families → `room visitation`, Alcohol/Drugs → only less smuggling (`unlock metaldetector`).

## Grants, emergencies, tunnels (bridge DLL 0.5)

- `grants` lists every grant with its money and status; `grant bootstraps` accepts one (advance paid at once).
  Start with bootstraps, Administration, Health. The game allows only a few running at once.
- `emergency tunnelsearch|shakedown|drugbust|stop|bangup|lockdown` presses the Emergencies buttons.
- `report` lists TUNNEL entrances. Escapes with a secure fence = tunnels: search, and get Dogs.

## Not available yet

Per-group regimes, Guard Response / Roll Call buttons. `lua <code>` runs raw Lua for anything else
(see `api.help()`).
