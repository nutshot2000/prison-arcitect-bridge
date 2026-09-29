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
```

`todo` shows the game's To-do panel as text plus the **prison temperature** (riot risk). In the test prison it was
100/100 with 63 prisoners waiting for solitary; 6 solitary cells and a visitation room brought it to 46 within a day.
Out of space? Move the fence out (`fence` with the bigger rectangle) and pave the old fence line
(`lua "return api.build_line('ConcreteTiles', x, y1, x, y2)"`).

## Rules learned the hard way (live, 28-29 Sep 2026)

1. **Beds before prisoners.** Prisoners arrive every day at 08:00 whether you are ready or not ("All available"
   intake). With no cells, no guards and no fence they fight and walk off the map: the first test prison lost 41
   prisoners and 4 people died. Lower the intake in the game (Reports > Intake) until beds ≥ prisoners.
2. **Fence first.** `fence` around the whole prison, including Deliveries and Garbage by the road. Escapes dropped to
   0 once it stood.
3. **Power:** one PowerStation feeds **50**, and a cooker alone takes about **10** (6 cookers + 2 fridges + lights =
   90). **Two stations on the same grid switch each other off** (`Overloaded 2`), whether they touch or are joined by
   cable. They do not share load. Give every station its own grid: put a `place PowerSwitch x y` on each cable between
   the parts and `switch x y off`. Check with `power`: each station should read under 50. A tripped station shows
   `PROBLEM: ... OFF`; `power on` resets it after you fix the cause. `utilmap power` shows the cables (objects are
   drawn over the cable under them, so look at the cells around them).
4. **No power, no water.** The WaterPumpStation needs electricity. Blue drops over toilets/showers in the game = no
   water; check `power` first.
5. **Never cable the road's street lights.** The map powers them itself (`ExternalPower`). `hookup` skips them now.
   Wiring them into your grid overloaded every station in the test prison.
6. **Toilets, showers and sinks need water; cookers, fridges, TVs and lights need power.** Run `hookup` after every
   new room. It reuses cable and pipe already in the ground.
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

## Not available yet

Camera control, the daily regime, and changing the prisoner intake from the bridge (do it in Reports > Intake).
`lua <code>` runs raw Lua for anything else (see `api.help()`).
