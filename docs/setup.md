# Setup

Use Windows 10/11, an installed licensed copy of the original Prison Architect and Python 3.11 or newer. The live test environment is Windows 11 with Python 3.12.10, psutil 7.2.2 and MSS 10.2.0.

From the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\pa-agent.exe doctor
```

No model API key, Lua mod or MCP configuration is needed yet. Global Python is not modified. For reproducible dependency versions use `requirements-tested.txt`.

Start Prison Architect through Steam. Leave the main menu visible. Run `pa-agent --live focus` if needed, then `pa-agent screenshot`. The response gives the absolute PNG path and geometry. Inspect that image: it should exclude the title bar and window borders and contain the actual game.

`pa-agent input-test` is a dry run by default. `pa-agent --live input-test` moves the pointer to the client centre. A menu keyboard test can use `--live input-test --key escape` after inspecting what Escape will do in the current state. Each action stores before/after evidence.

To customize paths, copy `pa-agent.example.toml` to `pa-agent.local.toml` and pass `--config pa-agent.local.toml` before the command. Relative configuration paths resolve from the TOML file's directory. Unknown options are errors. An explicit executable must exist and have an expected Prison Architect executable basename.

## Stop

Press **Ctrl+Shift+F12** during a live input session, or run `pa-agent stop` from another terminal. The controller releases its held inputs and refuses further input. Inspect the game and end existing controllers before using `pa-agent reset-stop`.

The hotkey is registered only while a live input session exists. If another app owns that hotkey, live input fails rather than silently running without it. Captures remain available while a stop is latched, provided the game is foreground.

## Source distribution

Do not include `.venv`, `runs`, saves, game archives or extracted scripts in a published repository. The GitHub source preview covers the standalone controller; client integration and a completed v0.1 release are later work.
