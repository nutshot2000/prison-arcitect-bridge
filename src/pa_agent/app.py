import argparse
import json
import platform
import sys
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path

from . import __version__
from .config import Config, stop_file, user_data_directory
from .errors import BridgeError
from .game.process import expected_executables, find_prison_architect_processes


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="PA-Agent: window-targeted Prison Architect control")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--config", type=Path)
    root.add_argument("--output", type=Path, help="Directory for frames and structured action logs")
    mode = root.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Send actual input (default is dry-run)")
    mode.add_argument("--dry-run", action="store_true", help="Validate and record without sending input")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("doctor", "detect", "focus", "stop", "reset-stop"):
        commands.add_parser(name)
    screenshot = commands.add_parser("screenshot")
    screenshot.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    inp = commands.add_parser("input", help="One bounded raw action in client-area pixels")
    actions = inp.add_subparsers(dest="action", required=True)
    for name in ("move", "click", "double-click", "drag", "scroll"):
        action = actions.add_parser(name)
        action.add_argument("x", type=int)
        action.add_argument("y", type=int)
        if name in ("click", "double-click", "drag"):
            action.add_argument("--button", choices=("left", "right", "middle"), default="left")
        if name == "drag":
            action.add_argument("x2", type=int)
            action.add_argument("y2", type=int)
            action.add_argument("--duration", type=float, default=0.5)
        if name == "scroll":
            action.add_argument("amount", type=int)
    key = actions.add_parser("key")
    key.add_argument("key")
    key.add_argument("--duration", type=float, default=0.08)
    text = actions.add_parser("text")
    text.add_argument("text")
    state = commands.add_parser("state", help="Parse a .prison save (read-only); default: newest save")
    state.add_argument("save", nargs="?", type=Path)
    state.add_argument("--full", action="store_true", help="Emit the whole save tree as JSON")
    lua = commands.add_parser("lua", help="Run Lua inside the live game (needs pa_bridge + AI Bridge mod)")
    lua.add_argument("code", help="Lua code; use return to get a value, or @file.lua")
    lua.add_argument("--timeout", type=float, default=10.0)
    commands.add_parser("bridge", help="Show live bridge status (DLL, in-game runtime, game time)")
    commands.add_parser("reload-mod", help="Developers: load mod/ai_bridge/data/world.lua into the running game "
                                           "(no prison reload; ordered-work tracking restarts)")
    play = commands.add_parser("play", help="Easy verbs for playing (status, next, look, room, hire...); 'play help'")
    play.add_argument("verb", nargs="?", default="help")
    play.add_argument("args", nargs="*")
    call = commands.add_parser("call", help="Call one api.* helper: call <fn> [args...] (numbers/JSON parsed)")
    call.add_argument("fn")
    call.add_argument("args", nargs="*")
    commands.add_parser("mcp", help="Run the MCP server on stdio for AI agents")
    test = commands.add_parser("input-test", help="Default: move pointer to client centre, no clicks")
    test.add_argument("--key", choices=("escape", "space"), help="Optionally test one key; changes game UI/state")
    return root


def doctor(config: Config) -> dict:
    paths = expected_executables(config.executable)
    result = {"version": __version__, "os": platform.platform(), "python": platform.python_version(),
              "dependencies": {name: version(name) for name in ("psutil", "mss")},
              "executables": [str(p) for p in paths], "processes": find_prison_architect_processes(paths),
              "save_directory": str(user_data_directory() / "saves"),
              "save_directory_exists": (user_data_directory() / "saves").is_dir(),
              "dry_run": config.dry_run, "emergency_stop_latched": stop_file().exists(),
              "emergency_hotkey": "Ctrl+Shift+F12 (reserved during live input sessions)",
              "ready_for_capture": False, "ready_for_input": False}
    try:
        from .game.native import Native
        from .game.window import WindowManager
        manager = WindowManager(Native(), paths)
        target = manager.find()
        result["window"] = asdict(target)
        manager.validate(target)
        result["ready_for_capture"] = True
        result["ready_for_input"] = not stop_file().exists()
        result["note"] = "Preflight only; capture, hotkey registration, and input injection are tested when invoked."
    except BridgeError as exc:
        result["next_step"] = str(exc)
    return result


def read_state(save: Path | None, full: bool) -> dict:
    from .state import load_prison, summarize
    if save is None:
        saves = sorted((user_data_directory() / "saves").glob("*.prison"), key=lambda p: p.stat().st_mtime)
        if not saves:
            raise ValueError("No .prison saves found")
        save = saves[-1]
    loaded = load_prison(save)
    meta = {"path": str(loaded.path), "bytes": loaded.size, "mtime": loaded.mtime, "sha256": loaded.sha256}
    return {"source": meta, "state": loaded.root.to_dict() if full else summarize(loaded.root)}


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        config = Config.load(args.config)
        if args.output:
            config = replace(config, output_directory=args.output.resolve())
        if args.live or args.dry_run:
            config = replace(config, dry_run=not args.live)
        if args.command in ("stop", "reset-stop"):
            path = stop_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            if args.command == "stop":
                path.write_text("Stopped by CLI\n", encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
            result = {"stop_latched": path.exists(), "path": str(path)}
        elif args.command == "doctor":
            result = doctor(config)
        elif args.command == "mcp":
            from .bridge.mcp_server import main as mcp_main
            return mcp_main()
        elif args.command in ("lua", "bridge"):
            from .bridge import BridgeClient
            client = BridgeClient(timeout=getattr(args, "timeout", 10.0))
            if args.command == "bridge":
                result = client.status()
                result["game"] = client.ping()
            else:
                code = Path(args.code[1:]).read_text(encoding="utf-8") if args.code.startswith("@") else args.code
                result = {"result": client.exec(code, args.timeout), "logs": client.drain_logs()}
        elif args.command == "play":
            from .bridge.easy import Easy, EasyError
            try:
                print(Easy().run(args.verb, args.args))
                return 0
            except EasyError as exc:
                print(f"ERROR: {exc}")
                return 2
        elif args.command == "reload-mod":
            from .bridge import BridgeClient
            src = (Path(__file__).resolve().parents[2] / "mod" / "ai_bridge" / "data" / "world.lua").read_text(encoding="utf-8")
            if "]====]" in src:
                raise ValueError("world.lua contains ]====], cannot embed it")
            code = ("local G = getfenv(Update)\n"
                    f"local f = assert(loadstring([====[{src}]====], 'world.lua'))\n"
                    "setfenv(f, G); f(); return G.PA_BRIDGE.VERSION")
            client = BridgeClient(timeout=20)
            result = {"reloaded": client.exec(code)}
            result["state"] = client.call("state")
        elif args.command == "call":
            from .bridge import BridgeClient
            def parse(v: str):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    return v
            result = BridgeClient(timeout=20).call(args.fn, *[parse(a) for a in args.args])
        elif args.command == "state":
            result = read_state(args.save, args.full)
        else:
            from .controller import PrisonArchitectController
            controller = PrisonArchitectController(config)
            if args.command == "detect":
                result = controller.get_window()
            elif args.command == "focus":
                result = ({"status": "dry_run", "window": controller.get_window()} if config.dry_run
                          else asdict(controller.manager.focus()))
                controller.recorder.event("focus", result=result)
            elif args.command == "screenshot":
                result = controller.screenshot(tuple(args.region) if args.region else None)
            elif args.command == "input-test":
                win = controller.manager.find()
                result = (controller.execute("key", key=args.key) if args.key else
                          controller.execute("move", x=win.client.width // 2, y=win.client.height // 2))
            else:
                arguments = {k: v for k, v in vars(args).items() if k not in
                             {"config", "output", "live", "dry_run", "command", "action"}}
                result = controller.execute(args.action, **arguments)
        print(json.dumps(result, indent=2))
        return 0
    except (BridgeError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": "Interrupted; held inputs released."}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
