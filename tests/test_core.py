import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pa_agent.config import Config
from pa_agent.errors import BridgeError
from pa_agent.game.input import InputSession, bounded_duration
from pa_agent.logging import Recorder
from pa_agent.models import GameWindow, Rect
from pa_agent.game.process import find_prison_architect_processes


class FakeNative:
    def __init__(self):
        self.events = []
        self.user = SimpleNamespace(GetAsyncKeyState=lambda _: 0)

    def move(self, x, y):
        self.events.append(("move", x, y))

    def mouse(self, flags, data=0):
        self.events.append(("mouse", flags, data))

    def key(self, code, up=False, unicode=False):
        self.events.append(("key", code, up, unicode))


class FakeManager:
    def __init__(self):
        self.native = FakeNative()
        self.window = GameWindow(123, 456, "game.exe", 1, "Game", Rect(-100, 80, 800, 600), True, False, 144)
        self.failure = None

    def find(self):
        return self.window

    def validate(self, target, point=None):
        if self.failure:
            raise BridgeError(self.failure)
        if point:
            target.client.point(*point)
        return self.window


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.manager = FakeManager()

    def session(self, dry=False):
        # Native hotkey/mutex integration is exercised separately on Windows.
        session = InputSession(self.manager, self.path / "STOP", dry)
        session.active = True  # Unit harness: no native hotkey or mutex.
        return session

    def test_session_requires_context(self):
        with self.assertRaisesRegex(BridgeError, "with block"):
            InputSession(self.manager, self.path / "STOP", True).execute("move", x=5, y=5)

    def test_client_coordinates_negative_monitor(self):
        self.assertEqual(Rect(-100, 80, 800, 600).point(10, 20), (-90, 100))

    def test_bounds_rejected_not_clamped(self):
        for point in [(-1, 0), (800, 0), (0, 600), (True, 0), (0.5, 2)]:
            with self.assertRaises(BridgeError):
                self.manager.window.client.point(*point)

    def test_crop_boundary(self):
        self.assertEqual(Rect(10, 20, 100, 100).crop(90, 90, 10, 10), Rect(100, 110, 10, 10))
        with self.assertRaises(BridgeError):
            Rect(10, 20, 100, 100).crop(90, 90, 11, 10)

    def test_duration_nan_and_infinity_rejected(self):
        for value in [float("nan"), float("inf"), -1, 0, 20, True]:
            with self.assertRaises(BridgeError):
                bounded_duration(value, 5)

    def test_dry_run_never_injects(self):
        result = self.session(True).execute("click", x=5, y=5)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(self.manager.native.events, [])

    def test_focus_loss_refuses_input(self):
        self.manager.failure = "focus lost"
        with self.assertRaisesRegex(BridgeError, "focus lost"):
            self.session().execute("click", x=5, y=5)
        self.assertEqual(self.manager.native.events, [])

    def test_stop_file_refuses_input(self):
        (self.path / "STOP").touch()
        with self.assertRaises(BridgeError):
            self.session().execute("key", key="space")
        self.assertEqual(self.manager.native.events, [])

    def test_click_dispatch_not_semantic_success(self):
        result = self.session().execute("click", x=5, y=5)
        self.assertEqual(result["status"], "dispatched")
        self.assertIsNone(result["semantic_success"])
        self.assertIn(("mouse", 4, 0), self.manager.native.events)

    def test_drag_failure_releases_button(self):
        session = self.session()
        original_move = self.manager.native.move

        def lose_focus(x, y):
            original_move(x, y)
            if len(self.manager.native.events) > 2:
                self.manager.failure = "focus lost during drag"

        self.manager.native.move = lose_focus
        with self.assertRaises(BridgeError):
            session.execute("drag", x=5, y=5, x2=30, y2=30, duration=0.1)
        self.assertIn(("mouse", 4, 0), self.manager.native.events)
        self.assertEqual(session.held, [])

    def test_key_failure_releases_key(self):
        session = self.session()
        with patch.object(session, "_wait", side_effect=BridgeError("stop")):
            with self.assertRaises(BridgeError):
                session.execute("key", key="w")
        self.assertIn(("key", ord("W"), True, False), self.manager.native.events)

    def test_stop_during_drag_releases_button(self):
        session = self.session()

        def stop(_):
            session.halted.set()
            session._guard()

        with patch.object(session, "_wait", side_effect=stop):
            with self.assertRaises(BridgeError):
                session.execute("drag", x=5, y=5, x2=30, y2=30, duration=0.1)
        self.assertEqual(session.held, [])
        self.assertIn(("mouse", 4, 0), self.manager.native.events)

    def test_out_of_bounds_drag_does_not_start(self):
        with self.assertRaises(BridgeError):
            self.session().execute("drag", x=5, y=5, x2=900, y2=30)
        self.assertEqual(self.manager.native.events, [])

    def test_unsupported_shortcuts_rejected(self):
        for key in ("alt+tab", "win", "ctrl+s", "f12"):
            with self.assertRaises(BridgeError):
                self.session().execute("key", key=key)

    def test_physical_modifier_refuses_input(self):
        self.manager.native.user.GetAsyncKeyState = lambda _: 0x8000
        with self.assertRaisesRegex(BridgeError, "physical"):
            self.session().execute("key", key="a")
        self.assertEqual(self.manager.native.events, [])

    def test_scroll_bounds(self):
        for amount in (11, -11, 0, 1.5, True):
            with self.assertRaises(BridgeError):
                self.session().execute("scroll", x=5, y=5, amount=amount)

    def test_unicode_text_pairs(self):
        self.session().execute("text", text="Aé")
        self.assertEqual(len(self.manager.native.events), 4)
        self.assertTrue(self.manager.native.events[-1][2])

    def test_text_controls_rejected(self):
        for text in ("a\nb", "\t", "\x7f", "", "x" * 257):
            with self.assertRaises(BridgeError):
                self.session().execute("text", text=text)

    def test_configuration_relative_paths(self):
        config = self.path / "config.toml"
        config.write_text('output_directory = "frames"\ndry_run = false\n', encoding="utf-8")
        loaded = Config.load(config)
        self.assertEqual(loaded.output_directory, self.path / "frames")
        self.assertFalse(loaded.dry_run)

    def test_configuration_typos_and_types_fail(self):
        for text in ('dryrun = true', 'dry_run = "false"', 'max_drag_seconds = nan', 'output_directory = 2'):
            config = self.path / "config.toml"
            config.write_text(text, encoding="utf-8")
            with self.assertRaises(BridgeError):
                Config.load(config)

    def test_recorder_preserves_order(self):
        recorder = Recorder(self.path)
        recorder.event("before")
        recorder.event("after")
        events = [json.loads(line) for line in (recorder.directory / "events.jsonl").read_text().splitlines()]
        self.assertEqual([e["sequence"] for e in events], [1, 2])

    def test_process_name_spoof_wrong_path_rejected(self):
        genuine = self.path / "game/Prison Architect64.exe"
        fake = SimpleNamespace(info={"pid": 1, "name": "Prison Architect64.exe", "exe": str(self.path / "other/Prison Architect64.exe"), "create_time": 1})
        with patch("pa_agent.game.process.psutil.process_iter", return_value=[fake]):
            self.assertEqual(find_prison_architect_processes([genuine]), [])


if __name__ == "__main__":
    unittest.main()
