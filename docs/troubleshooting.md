# Troubleshooting

| Message/symptom | Action |
| --- | --- |
| No game window | Start the game, not only the Paradox launcher. Run `doctor`. For a non-Steam copy set its executable in TOML. |
| Multiple windows | Close extra game instances; the controller deliberately refuses to guess. |
| Game not foreground | Use `--live focus` or select the game manually, then re-observe. Windows may refuse programmatic focus; that failure is surfaced rather than bypassed. |
| Minimized/off-screen | Restore and move the whole client onto a monitor. |
| Input rejected by Windows | Run game and controller at the same normal privilege level. Inspect overlays. |
| Window changed during action | Capture a fresh frame after moving/resizing the window. |
| Point covered | Remove the overlay or other window and capture again. |
| Emergency stop latched | Inspect the game, stop existing controller processes, then `reset-stop`. |
| Hotkey unavailable | Another controller/application owns Ctrl+Shift+F12. Resolve that conflict. |
| Black or wrong screenshot | Use windowed mode and keep the game foreground; exclusive fullscreen is not validated. |
| Action says dispatched but nothing happened | Inspect the frames. A accepted Windows event does not prove the game accepted it. |
| Unicode text not visible | Select the intended text field first. Game-specific Unicode handling is not guaranteed. |
| DPI awareness unavailable | Start a fresh standalone Python process; do not embed in a host with incompatible DPI setup. |

Errors after injection are ambiguous outcomes. Always observe before repeating a click, drag or key. Local action records are under `runs/<session>/events.jsonl` and may contain typed text: treat them as local game-session data.
