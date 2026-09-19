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
