import ctypes as C
import math
import threading
import time
from ctypes import wintypes as W
from pathlib import Path

from ..errors import BridgeError

KEYS = {"escape": 0x1B, "space": 0x20, "enter": 0x0D, "tab": 9, "backspace": 8,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "home": 0x24, "end": 0x23, "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22}
KEYS.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
BUTTONS = {"left": (2, 4), "right": (8, 16), "middle": (32, 64)}


def bounded_duration(value: float, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0.05 <= value <= maximum:
        raise BridgeError(f"Duration must be finite and between 0.05 and {maximum} seconds.")
    return float(value)


class InputSession:
    """One controller at a time, bounded actions, fail-closed focus checks."""
    def __init__(self, manager, stop_path: Path, dry_run: bool, max_drag_seconds: float = 5):
        self.manager, self.native = manager, manager.native
        self.stop_path, self.dry_run = stop_path, dry_run
        self.max_drag_seconds = max_drag_seconds
        self.lock = threading.RLock()
        self.halted, self.closed, self.ready = threading.Event(), threading.Event(), threading.Event()
        self.held: list[tuple[str, int]] = []
        self.watch_error: str | None = None
        self.release_errors: list[str] = []
        self.target = None
        self.mutex = None
        self.thread = None
        self.active = False
        self.action_started = 0.0

    def __enter__(self):
        if self.active or self.closed.is_set():
            raise BridgeError("InputSession is single-use and cannot be entered twice.")
        if self.stop_path.exists():
            raise BridgeError("Emergency stop is latched. Inspect the game, then run pa-agent reset-stop.")
        if not self.dry_run:
            self.mutex = self.native.kernel.CreateMutexW(None, False, "Local\\PA-Agent-Input-v1")
            if not self.mutex:
                raise BridgeError("Could not create the input ownership lock.")
            if self.native.kernel.WaitForSingleObject(self.mutex, 0) not in (0, 0x80):
                self.native.kernel.CloseHandle(self.mutex)
                self.mutex = None
                raise BridgeError("Another PA-Agent controller owns input.")
            self.thread = threading.Thread(target=self._watch, daemon=True)
            self.thread.start()
            if not self.ready.wait(2) or self.watch_error:
                self.__exit__(None, None, None)
                raise BridgeError(self.watch_error or "Emergency-stop watcher failed to start.")
        self.active = True
        return self

    def __exit__(self, *_):
        self.active = False
        self.closed.set()
        self.release_all()
        if self.thread:
            self.thread.join(timeout=2)
        if self.mutex:
            self.native.kernel.ReleaseMutex(self.mutex)
            self.native.kernel.CloseHandle(self.mutex)
            self.mutex = None

    def _watch(self):
        u = self.native.user
        registered = bool(u.RegisterHotKey(None, 0x5041, 0x4006, 0x7B))
        if not registered:
            self.watch_error = "Ctrl+Shift+F12 is unavailable. Close the other controller or hotkey owner."
            self.ready.set()
            return
        self.ready.set()
        try:
            while not self.closed.wait(0.02):
                message = W.MSG()
                triggered = False
                while u.PeekMessageW(C.byref(message), None, 0, 0, 1):
                    triggered |= message.message == 0x0312 and message.wParam == 0x5041
                triggered |= all(u.GetAsyncKeyState(k) & 0x8000 for k in (0x11, 0x10, 0x7B))
                if triggered:
                    # Latch in memory before filesystem I/O, which could fail.
                    self.halted.set()
                    self.release_all()
                    self.stop_path.parent.mkdir(parents=True, exist_ok=True)
                    self.stop_path.write_text("Emergency hotkey pressed\n", encoding="utf-8")
                if self.stop_path.exists():
                    self.halted.set()
                    self.release_all()
                if self.target and u.GetForegroundWindow() != self.target.hwnd:
                    self.halted.set()
                    self.release_all()
                if self.target and time.monotonic() - self.action_started > 12:
                    self.halted.set()
                    self.release_all()
        except Exception as exc:
            self.watch_error = str(exc)
            self.halted.set()
            self.release_all()
        finally:
            u.UnregisterHotKey(None, 0x5041)

    def release_all(self):
        with self.lock:
            for kind, code in reversed(self.held.copy()):
                try:
                    if kind == "mouse":
                        self.native.mouse(code)
                    else:
                        self.native.key(code, up=True, unicode=kind == "unicode")
                    self.held.remove((kind, code))
                except Exception as exc:
                    self.release_errors.append(str(exc))
                    self.halted.set()

    def _guard(self, point=None):
        if self.halted.is_set() or self.stop_path.exists():
            raise BridgeError("Input stopped: emergency stop, focus loss, or watcher failure.")
        if not self.target:
            raise BridgeError("No bound game window.")
        self.manager.validate(self.target, point)
        # Do not combine user-held modifiers with injected game keys/clicks.
        if any(self.native.user.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            raise BridgeError("Release physical Shift/Ctrl/Alt/Windows keys before input.")

    def _move(self, point):
        with self.lock:
            self._guard(point)
            self.native.move(*self.target.client.point(*point))

    def _down(self, kind, code, point=None):
        with self.lock:
            self._guard(point)
            # Track before sending so failure still causes a release attempt.
            self.held.append((kind, BUTTONS[code][1] if kind == "mouse" else code))
            if kind == "mouse":
                self.native.mouse(BUTTONS[code][0])
            else:
                self.native.key(code, unicode=kind == "unicode")

    def _wait(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._guard()
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))

    def execute(self, action: str, **args) -> dict:
        if not self.active:
            raise BridgeError("Use InputSession inside a with block so stop monitoring and cleanup are active.")
        allowed = {"move", "click", "double-click", "drag", "scroll", "key", "text"}
        if action not in allowed:
            raise BridgeError(f"Unsupported input action: {action}")
        target = self.manager.find()
        point = None
        if action in {"move", "click", "double-click", "drag", "scroll"}:
            point = (args["x"], args["y"])
            target.client.point(*point)
        button = args.get("button", "left")
        if button not in BUTTONS:
            raise BridgeError("Button must be left, right, or middle.")
        if action == "drag":
            target.client.point(args["x2"], args["y2"])
            duration = bounded_duration(args.get("duration", 0.5), self.max_drag_seconds)
        elif action == "key":
            name = str(args["key"]).lower()
            if name not in KEYS:
                raise BridgeError("Unsupported key. Use one letter/digit, arrows, escape, space, enter, tab, backspace, home, end, delete, pageup or pagedown. OS shortcuts are not exposed.")
            duration = bounded_duration(args.get("duration", 0.08), 2)
        elif action == "scroll":
            if type(args["amount"]) is not int or not -10 <= args["amount"] <= 10 or args["amount"] == 0:
                raise BridgeError("Scroll amount must be a nonzero integer between -10 and 10.")
        elif action == "text":
            value = args["text"]
            if not isinstance(value, str) or not 1 <= len(value) <= 256 or any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
                raise BridgeError("Text must contain 1–256 printable characters, without control characters.")
        self.action_started = time.monotonic()
        self.target = target
        try:
            self._guard(point)
            if self.dry_run:
                return {"status": "dry_run", "input_sent": False, "semantic_success": None, "action": action, "arguments": args}
            if point:
                self._move(point)
            if action in {"click", "double-click"}:
                for _ in range(2 if action == "double-click" else 1):
                    self._down("mouse", button, point)
                    self._wait(0.05)
                    self.release_all()
                    self._wait(0.06)
            elif action == "drag":
                self._down("mouse", button, point)
                steps = max(2, math.ceil(duration / 0.02))
                start = time.monotonic()
                for index in range(1, steps + 1):
                    self._move((round(args["x"] + (args["x2"] - args["x"]) * index / steps),
                                round(args["y"] + (args["y2"] - args["y"]) * index / steps)))
                    remaining = start + duration * index / steps - time.monotonic()
                    if remaining > 0:
                        self._wait(remaining)
            elif action == "scroll":
                with self.lock:
                    self._guard(point)
                    self.native.mouse(0x0800, args["amount"] * 120)
            elif action == "key":
                self._down("key", KEYS[name])
                self._wait(duration)
            elif action == "text":
                data = value.encode("utf-16-le")
                for i in range(0, len(data), 2):
                    self._down("unicode", int.from_bytes(data[i:i + 2], "little"))
                    self.release_all()
                    self._wait(0.01)
            self.release_all()
            self._guard()
            if self.release_errors:
                raise BridgeError("Input release failed: " + "; ".join(self.release_errors))
            return {"status": "dispatched", "input_sent": True, "semantic_success": None,
                    "action": action, "arguments": args}
        finally:
            self.release_all()
            self.target = None
