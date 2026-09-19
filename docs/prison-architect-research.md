# Prison Architect research — local evidence

Inspected 19 September 2026. These are observations of this machine, not universal paths or compatibility guarantees.

## Installation

- Steam app ID: `233450`.
- Installation: `C:\Program Files (x86)\Steam\steamapps\common\Prison Architect`.
- Executable: `Prison Architect64.exe` (14,425,088 bytes).
- Steam manifest build ID: `10630057`.
- Existing log/save label: `The_Jailhouse_1.02`; the previous debug log reports a February 2023 compile date. This is a local build label, not a claim about the newest release.
- Data files include `main.dat`, `prisons.dat`, `sounds.dat` and `collectables.dat`.
- No loose `.cpp`, `.h` or `.lua` source files were found under the installation. The engine source was not supplied or reviewed.

`main.dat` is a solid RAR archive, not a ZIP file. Its SHA-256 here is `e3d7d4fdfbd59dba506925bfbb2d63124e08ecdc5781f574ab379a7b508e7041`. The installed UnRAR utility could list and extract selected readable assets. Inspection copies are kept outside this repository and are not redistributed.

## Code actually inspected

- `data/grants.lua`: grant creation uses `Objective.CreateGrant`, `SetParent`, `RequireRoom`, `RequireEitherRoom`, `RequireObjects` and `RequireResearched`. These scripts encode objectives, not a general query API.
- `data/campaign/deathrow/deathrow.lua`: uses campaign functions including `Game.CamMove`, `Game.CamZoom`, `Game.SetMap`, `Game.Spawn`, `Game.Show` and `Game.Hide`.
- `data/language/base-language.txt`: tutorial text documents WASD/arrows for panning, mouse wheel for zoom and R/middle-click for rotation.

Campaign camera commands show that script-driven cameras exist in that context. They do **not** establish that a sandbox object script can query camera transforms. Likewise, a Lua runtime does not establish availability of `io`, `os`, sockets, named pipes or arbitrary filesystem writes.

## Saves and state

User data: `%LOCALAPPDATA%\Introversion\Prison Architect`.

Saves: its `saves` subdirectory. Two local `.prison` files were found. The inspected autosave is readable text with nested `BEGIN`/`END` sections and some inline sections. Top-level fields include `Version`, `NumCellsX`, `NumCellsY`, `OriginX/Y/W/H`, `TimeIndex`, `TimeWarpFactor`, `RandomSeed` and `Balance`. Sections include `Cells`, `Objects`, `Rooms` and `Finance`.

The inspected save describes a 200×160 map. This is an old snapshot, not a live prison-state reading. Fields such as balance appear at multiple nesting levels. A correct parser must preserve hierarchy, repeated fields, numeric types and unknown content. No save has been modified by the bridge.

The latest file cannot reliably identify the currently loaded prison. A future parser needs explicit save/session association and stable reads, plus source timestamps and checksums.

## Mods and scripting

The existing local mods directory is `%LOCALAPPDATA%\Introversion\Prison Architect\mods`. The historical developer documentation describes manifests and optional object Lua scripts, and lists nearby-object queries and navigation functions. See [Introversion's modding release notes](https://www.introversion.co.uk/prisonarchitect/builds-alpha.html).

Future installation procedure: put a correctly packaged mod directory containing its manifest and data under the local mods folder, then enable it through the game's mod UI. This procedure and the exact callback/protocol schema still need a live test on this build. No telemetry mod is installed by this project.

| Capability | Evidence/status |
| --- | --- |
| Grant objectives | Confirmed in packaged grant script |
| Campaign camera movement and zoom | Confirmed in packaged campaign script |
| Object scripts and nearby-object query API | Historical official developer documentation; not yet probed live |
| Live object positions/properties via a bridge object | Plausible, not implemented or verified |
| Whole-prison state from a normal object script | Unverified; do not promise |
| Camera readback from a normal object script | Unverified |
| Direct JSON/file/socket/named-pipe output | Unverified |
| Current menus, active tool and popup state | Read from screenshots in this prototype |

## Display and camera

Preferences at inspection requested 1920×1080, windowed, non-borderless, UI scale 1.0, `ScreenHighDPI=false` and `ZoomToMouse=true`. An older debug log mentioned 2560×1440. Preferences and historical logs are not substitutes for measuring the current client rectangle.

The bridge requests per-monitor DPI awareness before measuring windows. It converts client coordinates to desktop pixels with `ClientToScreen`, and supplies absolute virtual-desktop input. It does not use the window title to establish process identity.

Windowed operation is the initial target. Available resolution choices, borderless behavior, exclusive fullscreen capture, monitor changes and mixed-DPI layouts require live coverage. See the validation log for actual observations.

Because zoom-to-mouse is enabled, scrolling can change camera translation as well as scale. Future calibration must account for the wheel anchor and invalidate after panning/zooming. No permanent scale constant is justified yet.

## Sources for implementation decisions

- [MSS examples](https://python-mss.readthedocs.io/latest/examples.html): rectangular desktop capture and PNG encoding. Queried through Context7.
- [psutil documentation](https://psutil.readthedocs.io/): process iteration with selected attributes. Queried through Context7.
- [Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput): global input stream, insertion return value, integrity-level restrictions and held-key interference.

The capture backend does not claim occlusion-free capture. Raw input and UI navigation remain external even if future telemetry succeeds.
