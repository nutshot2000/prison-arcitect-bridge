# Prison Architect Agent Bridge

A Windows controller for the original **Prison Architect**, designed to become a model-independent MCP bridge. This is the first implementation of milestones 1–3, version **0.1.0a1**, not a completed v0.1 or an autonomous player.

Repository: [nutshot2000/prison-arcitect-bridge](https://github.com/nutshot2000/prison-arcitect-bridge).

## Start here

1. Open Prison Architect and leave it at the main menu, windowed and fully visible.
2. In this folder, install Python 3.11+ and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\pa-agent.exe doctor
```

If you already installed this checkout's virtual environment, run the last command directly.

```powershell
# Focus is an explicit operation; ordinary inputs never steal focus.
.\.venv\Scripts\pa-agent.exe --live focus
.\.venv\Scripts\pa-agent.exe screenshot

# Validate and record only. No mouse or keyboard events are sent.
.\.venv\Scripts\pa-agent.exe --dry-run input-test

# Move the mouse to the game client centre; no clicks.
.\.venv\Scripts\pa-agent.exe --live input-test
```

Screenshots, metadata and JSONL event records appear in a separate directory under `runs/` for every CLI invocation. All coordinates are **unscaled pixels relative to the game client**, excluding the title bar and borders. Inspect your own screenshot before choosing any coordinates.

## Implemented

- Steam library discovery, exact executable-path allowlisting, process identity checks and unambiguous window detection.
- Per-monitor DPI-aware client coordinates, including negative desktop origins.
- Foreground client-area screenshots and bounded screenshot regions, with metadata.
- Mouse move, left/right/middle click, double-click, bounded drag and wheel.
- Bounded single-key presses/holds and literal Unicode text, without OS shortcut chords.
- Dry-run by default, strict foreground checks, target-point occlusion checks and per-step revalidation.
- One live controller at a time; key/button cleanup on handled failures, focus loss and interrupts.
- Ctrl+Shift+F12 emergency stop during live sessions; persistent stop file and CLI stop command.
- Before/after screenshots and event logging. A dispatched input is explicitly **not** game-success verification.

See [validation.md](docs/validation.md) for what has actually been tested, including live results and remaining gaps.

## More commands

```powershell
.\.venv\Scripts\pa-agent.exe detect
.\.venv\Scripts\pa-agent.exe screenshot --region 0 0 400 300
.\.venv\Scripts\pa-agent.exe --dry-run input click 100 100 --button right
.\.venv\Scripts\pa-agent.exe --dry-run input drag 100 100 200 200 --duration 0.5
.\.venv\Scripts\pa-agent.exe --dry-run input scroll 400 300 1
.\.venv\Scripts\pa-agent.exe --dry-run input key escape
.\.venv\Scripts\pa-agent.exe --dry-run input text 'Example text'
.\.venv\Scripts\pa-agent.exe stop
.\.venv\Scripts\pa-agent.exe reset-stop
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`--live`, `--dry-run`, `--config` and `--output` are global flags and precede the command. `stop` always latches the stop flag; `reset-stop` explicitly clears it. Neither is a simulated game action. Never reset a stop while another controller is still executing.

## Current limitations

MCP, world coordinates, save parsing, UI recognition, Lua telemetry, benchmarks and autonomous construction are **not implemented**. The first assignment explicitly asks to establish the standalone controller before these features. Persistent key-down/key-up commands are deliberately withheld; use bounded holds (`input key w --duration 0.5`).

The screenshot backend crops the desktop. The game must be foreground, restored and on-screen. Overlays can appear in captures; exclusive fullscreen and mixed-DPI multi-monitor configurations still require live validation. Windows input is a global stream: focus checks reduce risk but cannot make delivery atomic with a focus change. Abrupt process termination or OS failure cannot guarantee cleanup. Do not run the game elevated while the controller is unelevated.

The repository contains original bridge code only. Owning the game is required. No game executable, extracted game script, private save or screenshot is included in the source package. Local test evidence remains in ignored `runs/` directories.

## Next milestone

**Milestone 4: measured camera calibration and world/client transforms**, with known tile landmarks, explicit uncertainty and invalidation after pan, zoom, load, resize or UI-scale changes. Then implement action-specific verification and read-only state parsing; add MCP only after the controller is proven.

## Project documents

- [Revised specification](docs/project-specification.md)
- [Installation and game research](docs/prison-architect-research.md)
- [Setup](docs/setup.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Validation evidence](docs/validation.md)

MIT-licensed bridge code. This is an early source preview; no benchmark-ready release is claimed.
