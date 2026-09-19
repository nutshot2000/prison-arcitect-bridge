"""Exercise the real Windows stop watcher without injecting any input."""
import json
import tempfile
import time
from pathlib import Path

from pa_agent.game.input import InputSession
from pa_agent.game.native import Native
from pa_agent.game.process import discover_executables
from pa_agent.game.window import WindowManager


def main():
    manager = WindowManager(Native(), discover_executables())
    with tempfile.TemporaryDirectory() as temp:
        latch = Path(temp) / "STOP"
        with InputSession(manager, latch, dry_run=False) as session:
            latch.write_text("test stop", encoding="utf-8")
            deadline = time.monotonic() + 1
            while not session.halted.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not session.halted.is_set():
                raise RuntimeError("Stop watcher did not latch within one second")
            print(json.dumps({"hotkey_registered": True, "stop_file_detected": True,
                              "input_injected": False, "physical_hotkey_tested": False}))


if __name__ == "__main__":
    main()
