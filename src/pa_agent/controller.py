import time
from dataclasses import asdict

from .config import Config, stop_file
from .game.capture import capture_game
from .game.input import InputSession
from .game.native import Native
from .game.process import expected_executables
from .game.window import WindowManager
from .logging import Recorder


class PrisonArchitectController:
    """Synchronous model-independent core; a future MCP adapter calls this API."""
    def __init__(self, config: Config):
        self.config = config
        self.manager = WindowManager(Native(), expected_executables(config.executable))
        self.recorder = Recorder(config.output_directory)

    def get_window(self) -> dict:
        return asdict(self.manager.find())

    def screenshot(self, region=None) -> dict:
        result = capture_game(self.manager, self.recorder.directory, region)
        self.recorder.event("screenshot", **result)
        return result

    def execute(self, action: str, **arguments) -> dict:
        before = None
        self.recorder.event("action_requested", action=action, arguments=arguments, dry_run=self.config.dry_run)
        try:
            with InputSession(self.manager, stop_file(), self.config.dry_run, self.config.max_drag_seconds) as session:
                before = self.screenshot()
                result = session.execute(action, **arguments)
                time.sleep(0.15)
                after = self.screenshot()
                result.update(before_frame=before["path"], after_frame=after["path"],
                              verification="Inspect after_frame; dispatch is not proof of game success.")
                self.recorder.event("action_result", **result)
                return result
        except Exception as exc:
            self.recorder.event("action_error", action=action, error=str(exc),
                                before_frame=before["path"] if before else None,
                                outcome="unknown; observe before retrying")
            raise
