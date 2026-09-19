import ctypes as C
import time
from ctypes import wintypes as W
from pathlib import Path

import psutil

from ..errors import BridgeError
from ..models import GameWindow, Rect
from .native import Native
from .process import find_prison_architect_processes


class WindowManager:
    def __init__(self, native: Native, executables: list[Path]):
        self.native = native
        self.executables = executables

    def snapshot(self, hwnd: int, process: dict) -> GameWindow:
        u = self.native.user
        rect, point = W.RECT(), W.POINT(0, 0)
        if not u.GetClientRect(hwnd, C.byref(rect)) or not u.ClientToScreen(hwnd, C.byref(point)):
            raise BridgeError("Game window disappeared during inspection.")
        title = C.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, title, len(title))
        return GameWindow(hwnd, process["pid"], process["exe"], process["create_time"], title.value,
                          Rect(point.x, point.y, rect.right, rect.bottom), u.GetForegroundWindow() == hwnd,
                          bool(u.IsIconic(hwnd)), u.GetDpiForWindow(hwnd))

    def find(self) -> GameWindow:
        processes = {p["pid"]: p for p in find_prison_architect_processes(self.executables)}
        windows: list[GameWindow] = []
        errors = []

        @self.native.callback
        def callback(hwnd, _):
            pid = W.DWORD()
            self.native.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            if pid.value in processes and self.native.user.IsWindowVisible(hwnd):
                try:
                    win = self.snapshot(hwnd, processes[pid.value])
                    if win.client.width > 0 and win.client.height > 0:
                        windows.append(win)
                except BridgeError as exc:
                    errors.append(str(exc))
            return True

        if not self.native.user.EnumWindows(callback, 0):
            raise BridgeError("Windows enumeration failed.")
        if len(windows) != 1:
            raise BridgeError(f"Expected one Prison Architect window; found {len(windows)}. Launch the game, close extra instances, or configure its executable. {errors}")
        return windows[0]

    def validate(self, expected: GameWindow, point: tuple[int, int] | None = None) -> GameWindow:
        u = self.native.user
        pid = W.DWORD()
        u.GetWindowThreadProcessId(expected.hwnd, C.byref(pid))
        try:
            process = psutil.Process(expected.pid)
            same_process = process.create_time() == expected.created and Path(process.exe()).resolve() == Path(expected.executable).resolve()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            same_process = False
        if pid.value != expected.pid or not same_process:
            raise BridgeError("Game process/window identity changed. Re-detect before acting.")
        current = self.snapshot(expected.hwnd, {"pid": expected.pid, "exe": expected.executable, "create_time": expected.created})
        if current.minimized or not u.IsWindowVisible(current.hwnd):
            raise BridgeError("Game is minimized or hidden.")
        if not current.focused:
            raise BridgeError("Game is not foreground. Focus it before issuing input or capturing.")
        if current.client != expected.client or current.dpi != expected.dpi:
            raise BridgeError("Window moved, resized, or changed DPI during the action. Observe again.")
        if point:
            desktop = current.client.point(*point)
            hit = u.WindowFromPoint(W.POINT(*desktop))
            if u.GetAncestor(hit, 2) != current.hwnd:
                raise BridgeError("Target point is covered by another window.")
        return current

    def focus(self) -> GameWindow:
        target = self.find()
        if target.minimized:
            raise BridgeError("Restore the minimized game first.")
        self.native.user.SetForegroundWindow(target.hwnd)
        time.sleep(0.15)
        return self.validate(target)
