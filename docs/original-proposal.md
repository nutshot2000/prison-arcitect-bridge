# Prison Architect AI Agent Bridge

## 1. Project goal

Build an open-source GitHub project that allows AI agents such as Codex, Claude, Hermes, Gemini, local models, and custom agents to autonomously play Prison Architect.

The agent should eventually be able to do essentially everything a human player can:

- See the game.
- Move the mouse.
- Click buttons and menus.
- Drag areas.
- Zoom in and out.
- Pan around the map.
- Open reports.
- Select construction tools.
- Draw foundations.
- Build walls.
- Place doors.
- Place objects.
- Design rooms logically.
- Lay utilities.
- Hire and dismiss staff.
- Change policies.
- Set regimes.
- Research upgrades.
- Manage prisoner intake.
- Respond to incidents.
- Pause and change game speed.
- Save and load.
- Read game information.
- Plan long-term prison development.
- Verify whether its actions worked.
- Recover when something fails.

The project must not be tied to one specific LLM.

The main interface should be MCP, with a model-independent core underneath it.

---

# 2. Core philosophy

The system should provide two kinds of access simultaneously.

## Human-style access

This is the equivalent of sitting at the computer.

Examples:

```text
screenshot()
move_mouse(x, y)
click(x, y)
double_click(x, y)
drag(x1, y1, x2, y2)
scroll(amount)
press_key(key)
key_down(key)
key_up(key)
type_text(text)
```

This allows an LLM to genuinely play Prison Architect using the real interface.

## Game-aware access

These tools remove unnecessary fragility without solving the game for the model.

Examples:

```text
get_game_window()
get_camera_state()
screen_to_world(x, y)
world_to_screen(x, y)
click_world(x, y)
drag_world(x1, y1, x2, y2)
get_basic_state()
```

The AI should still decide:

- what to build;
- where to build it;
- how large it should be;
- how rooms should connect;
- what staff are needed;
- when to expand;
- how to solve problems.

Do not create tools like:

```text
build_perfect_cellblock()
fix_food_problem()
solve_riot()
optimise_prison()
```

Those would undermine the benchmark.

---

# 3. Repository structure

Create one GitHub repository initially.

Suggested name:

```text
prison-architect-agent
```

Structure:

```text
prison-architect-agent/
│
├── README.md
├── LICENSE
├── pyproject.toml
├── .gitignore
├── .env.example
│
├── docs/
│   ├── architecture.md
│   ├── setup.md
│   ├── mcp-tools.md
│   ├── prison-architect-research.md
│   ├── coordinate-system.md
│   ├── benchmark-design.md
│   └── troubleshooting.md
│
├── src/
│   └── pa_agent/
│       ├── __init__.py
│       │
│       ├── app.py
│       │
│       ├── config.py
│       │
│       ├── logging.py
│       │
│       ├── models.py
│       │
│       ├── errors.py
│       │
│       ├── constants.py
│       │
│       ├── version.py
│       │
│       ├── game/
│       │   ├── process.py
│       │   ├── window.py
│       │   ├── capture.py
│       │   ├── input.py
│       │   ├── camera.py
│       │   ├── coordinates.py
│       │   └── session.py
│       │
│       ├── vision/
│       │   ├── screenshot.py
│       │   ├── crops.py
│       │   ├── templates.py
│       │   ├── ui_detection.py
│       │   └── calibration.py
│       │
│       ├── state/
│       │   ├── save_locator.py
│       │   ├── save_parser.py
│       │   ├── telemetry.py
│       │   ├── game_state.py
│       │   └── state_cache.py
│       │
│       ├── actions/
│       │   ├── mouse.py
│       │   ├── keyboard.py
│       │   ├── world.py
│       │   ├── camera.py
│       │   └── validation.py
│       │
│       ├── mcp/
│       │   ├── server.py
│       │   ├── registry.py
│       │   ├── observations.py
│       │   ├── actions.py
│       │   └── schemas.py
│       │
│       ├── mod/
│       │   ├── bridge.py
│       │   └── protocol.py
│       │
│       ├── benchmark/
│       │   ├── runner.py
│       │   ├── episode.py
│       │   ├── scoring.py
│       │   ├── recorder.py
│       │   └── scenarios.py
│       │
│       └── replay/
│           ├── events.py
│           └── exporter.py
│
├── prison_architect_mod/
│   ├── manifest.txt
│   ├── data/
│   ├── scripts/
│   │   └── ai_bridge.lua
│   └── README.md
│
├── scenarios/
│   ├── empty_plot/
│   ├── failing_prison/
│   └── riot_recovery/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── scripts/
│   ├── install_mod.py
│   ├── detect_game.py
│   ├── inspect_save.py
│   └── calibration_tool.py
│
└── examples/
    ├── codex.md
    ├── claude.md
    ├── hermes.md
    └── generic-mcp.json
```

Python is a good starting language because it has strong Windows automation, image-processing, MCP, testing and data-parsing libraries.

Use modern Python with type hints throughout.

---

# 4. Phase 0 — Research Prison Architect

Before implementing automation, inspect the game.

Create:

```text
docs/prison-architect-research.md
```

Document:

- Steam installation location.
- Executable name.
- Save-file location.
- Mod directory.
- Supported resolutions.
- Windowed/borderless/fullscreen behaviour.
- UI scaling options.
- Camera movement behaviour.
- Zoom behaviour.
- Keyboard shortcuts.
- Save format.
- Mod scripting capabilities.
- Lua functions exposed by Prison Architect.
- Which game state can be obtained through Lua.
- Which state is available through save files.
- Which information exists only on screen.

Research the game's coordinate systems carefully.

Determine:

```text
world/grid coordinates
screen coordinates
window-client coordinates
Windows desktop coordinates
```

This research becomes the foundation for everything else.

### Phase 0 completion criteria

The repo should contain documentation explaining:

1. Where Prison Architect is installed.
2. How saves work.
3. How mods are installed.
4. What Lua can access.
5. What Lua cannot access.
6. How the camera behaves.
7. What must be controlled externally.

---

# 5. Phase 1 — Detect and control Prison Architect

Do not involve MCP yet.

First create a standalone Python controller.

## Process detection

Implement:

```python
find_prison_architect_process()
is_game_running()
get_process_id()
```

## Window detection

Implement:

```python
find_game_window()
get_window_rect()
focus_game_window()
is_game_focused()
```

Represent the window as something like:

```json
{
  "left": 100,
  "top": 80,
  "width": 1920,
  "height": 1080
}
```

All automation should be relative to the game client area rather than absolute desktop coordinates wherever possible.

---

# 6. Phase 2 — Screenshot system

Implement reliable game capture.

Required functions:

```text
capture_game()
capture_region(x, y, width, height)
capture_cursor_context()
```

Screenshots should include useful metadata:

```json
{
  "timestamp": "...",
  "width": 1920,
  "height": 1080,
  "window_rect": {...},
  "focused": true
}
```

Keep screenshot generation fast.

The system should be capable of taking repeated screenshots during gameplay.

Build a basic debug command:

```bash
pa-agent screenshot
```

It should save a screenshot and confirm that the correct game window was captured.

### Completion test

Launch Prison Architect.

Run:

```bash
pa-agent screenshot
```

The saved image must contain only the intended game window/client area.

---

# 7. Phase 3 — Raw human controls

Implement Windows input automation.

Required tools:

```text
move_mouse(x, y)
click(x, y)
right_click(x, y)
double_click(x, y)

drag(x1, y1, x2, y2, duration)

scroll(amount)

press_key(key)

key_down(key)
key_up(key)

type_text(text)
```

Coordinates supplied to these functions should be relative to the Prison Architect game window.

Safety behaviour:

- refuse input if game window cannot be found;
- optionally refuse if game is not foreground;
- clamp coordinates to game bounds;
- automatically release stuck keys;
- always release mouse button after failed drag;
- support emergency-stop hotkey.

Create:

```text
pa-agent input-test
```

This should allow manual verification.

---

# 8. Phase 4 — Camera understanding

This is one of the most important technical parts.

We need to understand how Prison Architect transforms map tiles into screen coordinates.

Build:

```text
get_zoom_estimate()
get_camera_offset()
screen_to_world(x, y)
world_to_screen(x, y)

click_world(x, y)

drag_world(
    world_x1,
    world_y1,
    world_x2,
    world_y2
)
```

This may initially require calibration.

Create:

```bash
pa-agent calibrate
```

The calibration utility should help establish:

- tile dimensions at different zoom levels;
- camera origin;
- screen centre;
- UI offsets;
- transformations between grid and screen space.

Do not assume transformation values permanently.

Store profiles per:

```text
resolution
window size
UI scale
zoom level
```

Potential internal model:

```text
screen_x = origin_x + world_x * tile_width
screen_y = origin_y + world_y * tile_height
```

adjusted for camera offset and zoom.

Later, Lua telemetry may make this easier.

### Important requirement

Coordinate errors must be detectable.

After a world-space action, capture another screenshot and verify that something changed near the expected location.

---

# 9. Phase 5 — Action verification

Do not allow the AI to assume that a click worked.

Every meaningful action should return evidence.

Example:

```json
{
  "success": true,
  "action": "drag",
  "before_frame": "frame_103",
  "after_frame": "frame_104",
  "visual_change_detected": true
}
```

For failed actions:

```json
{
  "success": false,
  "reason": "No significant visual change detected"
}
```

Build reusable verification primitives:

```text
compare_region_before_after()
detect_popup()
detect_tool_change()
detect_menu_change()
```

The agent can then recover instead of blindly continuing.

---

# 10. Phase 6 — Basic UI understanding

Do not immediately try to recognise every Prison Architect menu.

Start with stable UI components.

Identify:

```text
money
game clock
pause/play
game speed
build toolbar
reports
staff
rooms
objects
utilities
deployment
emergencies
```

Possible implementation methods:

- image templates;
- fixed anchors;
- icon recognition;
- text recognition where required;
- visual-language model reasoning through screenshots.

Prefer deterministic detection for important anchors.

Represent detected UI:

```json
{
  "visible_panels": ["build"],
  "buttons": [
    {
      "name": "rooms",
      "bbox": [x1, y1, x2, y2],
      "confidence": 0.94
    }
  ]
}
```

Expose:

```text
get_visible_ui()
find_ui_element(name)
click_ui_element(name)
```

Keep raw clicking available as well.

---

# 11. Phase 7 — Save-file parser

Add read-only access to `.prison` save data.

Do NOT write to saves initially.

Implement:

```text
find_current_save()
parse_save(path)
get_prison_summary()
get_map_dimensions()
get_objects()
get_entities()
get_rooms()
get_finances()
```

Store parsed data in clean Python models.

Example:

```json
{
  "money": 28145,
  "map": {
    "width": 160,
    "height": 120
  },
  "prisoners": 64,
  "staff": 29
}
```

The parser should tolerate unknown fields.

Never crash merely because Prison Architect adds or changes a property.

---

# 12. Phase 8 — Prison Architect Lua mod

Now introduce the in-game component.

The mod's purpose is primarily telemetry.

Do not make it responsible for the entire control system.

Create a bridge object or script that can collect information available from Prison Architect's scripting API.

Potential telemetry:

```text
game time
nearby entities
entity position
entity type
object state
selected known game state
custom bridge state
```

Build a simple external communication channel.

Options to investigate:

1. Shared JSON file.
2. Append-only event log.
3. Local filesystem message queue.
4. Local TCP/socket connection if possible.
5. Named pipe if practical.

Start simple.

Recommended first implementation:

```text
Prison Architect Lua
       ↓
telemetry.json
       ↓
Python bridge
```

Example:

```json
{
  "sequence": 1932,
  "timestamp": "...",
  "entities": [],
  "events": []
}
```

Write atomically so the Python process never reads a half-written file.

---

# 13. Phase 9 — Unified game state

Combine sources:

```text
screenshot
save file
Lua telemetry
window information
camera information
```

into one state model.

Example:

```json
{
  "session": {
    "running": true,
    "focused": true,
    "paused": false
  },

  "camera": {
    "zoom": 0.75,
    "estimated_world_center": [64, 43]
  },

  "prison": {
    "money": 28145,
    "prisoners": 64,
    "capacity": 72
  },

  "alerts": [],

  "telemetry_age_ms": 85
}
```

Every field should indicate where it came from when useful.

Example:

```json
{
  "money": {
    "value": 28145,
    "source": "save",
    "age_ms": 1400
  }
}
```

That makes debugging much easier.

---

# 14. Phase 10 — MCP server

Only after the basic bridge works should MCP be added.

Expose tools in groups.

## Observation tools

```text
pa_screenshot

pa_screenshot_region

pa_get_state

pa_get_window

pa_get_camera

pa_get_visible_ui

pa_screen_to_world

pa_world_to_screen
```

## Raw input tools

```text
pa_move_mouse

pa_click

pa_right_click

pa_double_click

pa_drag

pa_scroll

pa_press_key

pa_type_text
```

## World input tools

```text
pa_click_world

pa_drag_world
```

## Session tools

```text
pa_pause

pa_resume

pa_focus

pa_save
```

Avoid high-level strategy tools initially.

---

# 15. MCP tool design rules

Every MCP tool should have:

- strict JSON schema;
- useful description;
- clear coordinate rules;
- bounded inputs;
- helpful errors;
- concise result;
- optional verification.

For example:

```json
{
  "name": "pa_drag_world",
  "description": "Drag from one Prison Architect world tile to another using the current calibrated camera transform.",
  "input": {
    "x1": 34,
    "y1": 28,
    "x2": 51,
    "y2": 42
  }
}
```

Result:

```json
{
  "ok": true,
  "start_screen": [517, 396],
  "end_screen": [789, 620],
  "visual_change": true
}
```

---

# 16. Phase 11 — Model-independent agent protocol

MCP should be one frontend, not the whole application.

Internally create an interface:

```python
class PrisonArchitectController:
    async def screenshot(...):
        ...

    async def click(...):
        ...

    async def drag(...):
        ...

    async def get_state(...):
        ...
```

The MCP server calls this class.

Later other frontends can use it:

```text
REST
WebSocket
CLI
Python API
```

This means future models do not require rewriting the game integration.

---

# 17. Phase 12 — Codex integration

Document how Codex connects.

Create:

```text
examples/codex.md
```

Include:

- how to start the bridge;
- how to configure MCP;
- required permissions;
- sample prompt;
- troubleshooting.

Example agent instruction:

```text
You control Prison Architect through the prison-architect MCP server.

Operate the game autonomously.

Before important actions:
1. Observe the current state.
2. Decide what needs doing.
3. Perform the action.
4. Observe again.
5. Verify success.

Use screenshots for UI understanding.
Use world-coordinate tools for map construction where appropriate.
Do not assume an action succeeded without checking.
```

---

# 18. Phase 13 — Claude and Hermes support

Because the actual control protocol is MCP, adding another agent should mostly require configuration.

Create:

```text
examples/claude.md
examples/hermes.md
examples/generic-mcp.md
```

Avoid model-specific logic inside the game bridge.

---

# 19. Phase 14 — Construction primitives

Once basic autonomy works, add better map interaction.

Tools may include:

```text
select_build_category(name)
select_object(name)
select_room(name)

click_world(x, y)
drag_world(x1, y1, x2, y2)

rotate_selected_object()
cancel_current_tool()
```

Important:

These should automate UI mechanics, not planning.

Good:

```text
select_room("Cell")
drag_world(30, 40, 32, 43)
```

Bad:

```text
make_optimal_cell()
```

The AI remains responsible for architecture.

---

# 20. Phase 15 — Map representation

Build a world map model.

Possible representation:

```json
{
  "width": 160,
  "height": 120,
  "tiles": {
    "42,31": {
      "room": "Kitchen",
      "objects": ["Cooker"],
      "walkable": true
    }
  }
}
```

Do not send the full giant map to the LLM every turn.

Expose query tools:

```text
get_map_region(x1, y1, x2, y2)

get_room_bounds(room_id)

get_objects_in_region(...)

get_entities_near(...)
```

This reduces token usage dramatically.

---

# 21. Phase 16 — Persistent agent memory

The bridge should optionally store an agent notebook.

Example:

```json
{
  "areas": {
    "cellblock_a": [20, 40, 60, 80],
    "kitchen": [64, 25, 78, 38]
  },

  "plans": [
    "Expand kitchen at 80 prisoners",
    "Add second yard"
  ]
}
```

Tools:

```text
remember_location(name, bounds)

remember_note(text)

get_agent_memory()

delete_memory(key)
```

This should be benchmark-configurable because memory availability affects performance.

---

# 22. Phase 17 — Autonomous control loop

Create an example autonomous runner.

Pseudo-code:

```python
while episode.active:

    observation = controller.observe()

    decision = agent.reason(observation)

    action = decision.action

    result = controller.execute(action)

    verification = controller.observe()

    recorder.log(
        observation,
        decision,
        action,
        result,
        verification,
    )
```

Important principle:

```text
OBSERVE
   ↓
PLAN
   ↓
ACT
   ↓
VERIFY
   ↓
RECOVER OR CONTINUE
```

---

# 23. Phase 18 — Run recorder

Record everything.

Every action should create an event:

```json
{
  "sequence": 417,
  "game_time": "Day 4 13:25",
  "real_time": "...",

  "observation": {
    "frame": "000417-before.png"
  },

  "model": {
    "name": "example-model",
    "reason_summary": "Kitchen is overloaded."
  },

  "tool": {
    "name": "pa_drag_world",
    "arguments": {...}
  },

  "result": {...},

  "after_frame": "000417-after.png"
}
```

Do not depend on storing private model chain-of-thought.

Record concise model-provided action rationale instead.

---

# 24. Phase 19 — Benchmark framework

Only after normal play works should the formal benchmark become a priority.

Each scenario should define:

```yaml
name: empty_plot_v1

save: empty_plot.prison

time_limit:
  game_days: 7

starting_conditions:
  money: 50000

objectives:
  - receive_prisoners
  - remain_solvent
  - maintain_security

scoring:
  escapes: -1000
  deaths: -1500
  positive_cash: 0.1
  occupied_cells: 20
```

A benchmark episode should:

1. Restore the same save.
2. Start the bridge.
3. Start the model.
4. Record all actions.
5. Stop at scenario limit.
6. Calculate score.
7. Store result.

---

# 25. Benchmark modes

Create several modes.

## Human mode

Allowed:

```text
screenshot
mouse
keyboard
scroll
```

Tests:

```text
vision
UI comprehension
motor control
reasoning
```

## Assisted mode

Add:

```text
world coordinates
camera conversion
basic UI anchors
```

Tests:

```text
planning
spatial reasoning
game knowledge
```

without coordinate fragility dominating.

## Agent mode

Add:

```text
structured state
save information
telemetry
```

Tests:

```text
long-term planning
tool use
decision quality
```

## Debug mode

Everything exposed.

Used for development rather than leaderboard comparisons.

---

# 26. Initial benchmark scenarios

Start with five.

## Scenario 1 — Tutorial interaction

Objective:

```text
Open specified menus and perform basic construction.
```

Tests whether the model can operate the interface.

## Scenario 2 — Empty plot

Start:

```text
empty land
£50,000
```

Objective:

```text
construct a functioning 20-prisoner facility
```

## Scenario 3 — Broken kitchen

Existing prison.

Problems:

```text
food demand high
poor kitchen layout
insufficient cooks
```

Objective:

```text
stabilise food service
```

## Scenario 4 — Financial crisis

Start:

```text
low cash
high staff expenses
unused buildings
```

Objective:

```text
remain solvent for 7 days
```

## Scenario 5 — Disaster prison

Start:

```text
overcrowding
violence
high needs
staff problems
poor layout
```

Prompt:

```text
Stabilise this prison.
```

This should become one of the flagship tests.

---

# 27. Scoring

Avoid one simplistic metric.

Store raw metrics:

```text
cash
income
expenses
capacity
prisoner count
deaths
escapes
riots
fights
staff deaths
prisoner needs
staff needs
contraband
reoffending
punishment
rehabilitation
average lockdown time
construction efficiency
unused building area
```

Then calculate benchmark-specific scores.

Keep raw measurements available so scoring can change later without rerunning every episode.

---

# 28. Reproducibility

Every benchmark run should record:

```text
model
provider
model version
temperature
system prompt
toolset version
PA-Agent version
Prison Architect version
scenario version
save checksum
screen resolution
UI scale
benchmark mode
start time
episode duration
```

This is essential if the project becomes a serious LLM benchmark.

---

# 29. Replay viewer

Eventually create a lightweight replay viewer.

It should show:

```text
game screenshot
↓
model rationale
↓
tool call
↓
result
↓
next screenshot
```

Timeline example:

```text
00:14:31
Observed rising Food need

00:14:36
Opened kitchen area

00:14:43
Built two cookers

00:15:01
Hired two cooks
```

Eventually this could create videos automatically.

But do not build this before the core bridge works.

---

# 30. Reliability work

Autonomous agents will expose edge cases quickly.

Implement recovery for:

```text
lost game focus
unexpected popup
Steam overlay
pause screen
menu left open
wrong tool selected
camera accidentally moved
failed drag
failed click
save/loading screen
game crash
agent timeout
stuck mouse button
stuck keyboard key
```

Create:

```text
recover_game_state()
```

It should try only safe mechanical recovery actions.

Do not make strategic game decisions inside recovery code.

---

# 31. Logging

Use structured logging from day one.

Example:

```json
{
  "level": "INFO",
  "component": "camera",
  "event": "world_to_screen",
  "world": [42, 38],
  "screen": [817, 519],
  "zoom": 0.72
}
```

Logs should make failures reproducible.

---

# 32. Testing

Tests should not depend entirely on launching Prison Architect.

## Unit tests

Test:

```text
save parsing
coordinate conversion
MCP schemas
configuration
event recording
benchmark scoring
```

## Fixture-based vision tests

Store screenshots.

Test:

```text
detect build button
detect pause indicator
detect open reports panel
```

## Integration tests

With Prison Architect running:

```text
capture game
focus game
click known button
verify visual change
perform calibrated world click
```

---

# 33. Safety for local automation

Because this controls the real PC, implement strict window targeting.

Input should only be sent when:

```text
Prison Architect window exists
AND
the expected game process owns the window
```

Add:

```text
--dry-run
```

Dry-run mode should log intended inputs without performing them.

Also add an emergency-stop hotkey.

Example:

```text
CTRL + SHIFT + F12
```

When triggered:

```text
stop all automation
release all held keys
release mouse buttons
disconnect agent
```

---

# 34. Configuration

Example:

```yaml
game:
  executable: auto
  save_directory: auto

capture:
  fps_limit: 3

input:
  require_focus: true
  emergency_stop: CTRL+SHIFT+F12

telemetry:
  lua_bridge: true
  save_parser: true

mcp:
  enabled: true

benchmark:
  record_frames: true
```

Avoid hardcoded machine-specific paths.

---

# 35. CLI

Eventually support:

```bash
pa-agent doctor

pa-agent detect

pa-agent screenshot

pa-agent calibrate

pa-agent inspect-save

pa-agent install-mod

pa-agent start

pa-agent mcp

pa-agent benchmark run empty_plot

pa-agent benchmark results
```

`doctor` should diagnose common setup problems automatically.

---

# 36. README structure

The GitHub README should eventually include:

```text
What is PA-Agent?

Demo GIF/video

Features

Supported agent systems

Quick start

Install

Start Prison Architect

Start PA-Agent

Configure MCP

Give your model control

Available tools

Benchmark modes

Architecture

Roadmap

Contributing
```

---

# 37. Development order

Codex should build this in the following order.

Do not skip ahead.

## Milestone 1

Repository skeleton.

CLI.

Logging.

Configuration.

Tests.

## Milestone 2

Find Prison Architect process and window.

Capture screenshots.

## Milestone 3

Mouse and keyboard controls.

Window-relative coordinates.

Emergency stop.

## Milestone 4

Camera and coordinate calibration.

World ↔ screen conversion.

## Milestone 5

Action verification.

UI anchor detection.

## Milestone 6

Save parser.

Structured basic state.

## Milestone 7

Lua telemetry mod.

Bridge communication.

## Milestone 8

Unified game-state model.

## Milestone 9

MCP server.

Raw control tools.

Observation tools.

## Milestone 10

Run the first LLM.

Goal:

```text
model successfully opens menus,
moves camera,
zooms,
selects construction tool,
draws one structure,
and verifies that it succeeded
```

## Milestone 11

Construction primitives.

Room planning experiments.

## Milestone 12

Long-running autonomous play.

## Milestone 13

Benchmark runner.

Scenarios.

Scoring.

## Milestone 14

Replay viewer and polished GitHub release.

---

# 38. First major success target

Do not define success as:

```text
AI can click the game.
```

Define the first meaningful demo as:

> Starting from a known save, an LLM independently observes Prison Architect, opens the construction interface, selects foundations, builds a rectangular structure at a sensible location, adds an entrance, designates a room, places required objects and verifies each stage without human mouse or keyboard input.

Once this works reliably, the fundamental architecture is proven.

---

# 39. Second major success target

Give the model:

```text
£50,000
empty plot
```

Prompt:

```text
Build a small functioning prison capable of safely receiving 20 prisoners.
Do not ask the human for assistance.
```

The model should independently:

```text
inspect map
plan layout
build reception
build holding/cells
build shower
build kitchen
build canteen
build yard
build utilities
place objects
hire staff
enable intake
receive prisoners
react to problems
```

This should become the first public demonstration.

---

# 40. What Codex should NOT do initially

Do not:

- build a web dashboard first;
- build leaderboards first;
- add dozens of models first;
- spend weeks polishing UI;
- reverse-engineer the whole Prison Architect executable;
- directly modify save files to play the game;
- build sophisticated OCR before basic screenshots work;
- expose hundreds of MCP tools;
- implement automatic perfect building layouts;
- mix benchmark logic into input-control code;
- make the system Codex-specific.

First prove:

```text
SEE → ACT → VERIFY
```

Everything else follows from that.

---

# 41. Recommended first MCP tool set

Keep version 0.1 small.

```text
pa_get_status

pa_screenshot

pa_screenshot_region

pa_get_state

pa_get_window

pa_move_mouse

pa_click

pa_right_click

pa_double_click

pa_drag

pa_scroll

pa_press_key

pa_type_text

pa_get_camera

pa_world_to_screen

pa_screen_to_world

pa_click_world

pa_drag_world
```

Approximately 15–20 strong tools are better than 100 unreliable ones.

---

# 42. Definition of version 0.1

Version 0.1 is complete when:

1. Prison Architect is detected automatically.
2. The game window can be captured reliably.
3. An MCP agent can receive screenshots.
4. The agent can use mouse and keyboard.
5. The agent can zoom and pan.
6. Window-relative coordinates remain correct.
7. Basic world-coordinate conversion works.
8. Basic prison state can be read.
9. Actions generate useful success/error results.
10. A model can construct something in-game without human control.
11. A complete action log is stored.
12. Setup is documented well enough for another person to install it.

Do not call the project benchmark-ready before those twelve points work.

---

# 43. Definition of version 0.2

Version 0.2 should add:

- Prison Architect Lua telemetry.
- Better world coordinates.
- map queries;
- UI element detection;
- reliable room construction;
- object placement;
- persistent agent notes;
- long sessions;
- save/load management;
- automated scenario resets.

---

# 44. Definition of version 1.0

Version 1.0 should support:

- Codex;
- Claude;
- Hermes;
- generic MCP clients;
- full autonomous prison management;
- benchmark scenarios;
- repeatable resets;
- run recording;
- scoring;
- replay;
- multiple benchmark modes;
- documented installation;
- robust recovery;
- public GitHub releases.

---

# 45. Prompt to give Codex Work

Use the plan above as the project specification.

Then give Codex Work this initial instruction:

```text
Build this project incrementally from the attached specification.

This is a real Windows project for controlling Prison Architect with AI agents.

Work milestone-by-milestone and keep the architecture modular.

For the first implementation focus ONLY on Milestones 1–3:

1. Create the repository structure.
2. Implement configuration, structured logging and CLI scaffolding.
3. Detect a running Prison Architect process.
4. Locate its Windows game window.
5. Capture a screenshot of only the game client.
6. Implement window-relative mouse and keyboard control.
7. Implement strict window ownership/focus checks.
8. Add a dry-run mode.
9. Add an emergency-stop mechanism.
10. Add unit tests where practical.
11. Write setup and architecture documentation.

Do not build the benchmark yet.
Do not build model integrations yet.
Do not attempt complicated Lua telemetry yet.
Do not implement high-level gameplay automation.

Use Python with modern type hints and a clean src layout.

Before choosing libraries, inspect the current project environment and select actively maintained Windows-compatible packages.

Test the implementation against the actual Prison Architect installation on this machine whenever possible.

At the end, update the README with:
- what currently works;
- commands to run;
- known limitations;
- exact next milestone.

The immediate success condition is:

`pa-agent doctor` detects the environment, and `pa-agent screenshot` captures Prison Architect correctly, while the input test can safely perform window-relative mouse/keyboard actions only against the Prison Architect process.

Do not fake functionality. If something cannot yet be verified against the real game, clearly mark it unverified and create the appropriate test/debugging path.
```

After Codex finishes that milestone, the next prompt should focus on camera calibration and world coordinates rather than trying to build the entire project in one giant agent run.

That staged approach is important. This project is absolutely achievable, but the difficult part is making the interaction layer **reliable**, not writing an MCP server. Once Prison Architect can reliably be observed and controlled, plugging different LLMs into it becomes the relatively easy part.