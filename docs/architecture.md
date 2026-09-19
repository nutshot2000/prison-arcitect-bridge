# Architecture

```text
CLI -> PrisonArchitectController -> WindowManager + capture + InputSession
                  |
                  +-> timestamped frames, metadata and JSONL events

Future MCP adapter -> same controller (no separate game logic)
Future read-only state adapters -> source-tagged observations
```

`config.py` validates TOML. `models.py` defines immutable window/client geometry. `game/process.py` discovers Steam libraries and allowlists exact game executable paths. `game/native.py` declares explicit 64-bit Win32 signatures. `game/window.py` binds PID, process creation time, executable path and HWND; it refuses ambiguity.

`game/capture.py` captures the foreground client region using MSS and checks window identity and geometry again after the grab. It refuses off-screen rectangles. Capture metadata states the backend and its overlay limitation.

`game/input.py` serializes controllers with a Windows named mutex and reserves Ctrl+Shift+F12 in a watchdog thread. It checks a persistent stop file, game focus, window identity, geometry and target-point coverage. It releases only keys/buttons held by this controller. Movement is absolute across the virtual desktop. Drags and key holds are bounded; repeated checks occur during waits and drag steps.

`controller.py` records request, before frame, dispatch, after frame and outcome/error. Action success is not inferred from animation. The CLI returns JSON on stdout and errors on stderr. There is no network service or model dependency.

## Constraints

- One foreground game instance and one live input session at a time.
- Input checks cannot eliminate the Win32 focus race. OS failure/forced termination can defeat in-process cleanup; a separate watchdog is a later hardening option.
- Same-process Steam overlays can intercept game input without changing the foreground HWND. Screenshots are still necessary.
- Key chords and persistent unbounded holds are not exposed in this milestone.
- An error after input may mean the action happened but verification failed. Do not retry automatically.
- Log/frame retention is currently manual. Long-session quotas come before unattended runs.
- Synchronous API fits bounded local actions. A future asynchronous adapter must serialize calls and preserve cancellation cleanup.
