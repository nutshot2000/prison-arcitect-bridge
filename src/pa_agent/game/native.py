"""Explicit ctypes signatures are essential for 64-bit HWND and INPUT correctness."""
import ctypes as C
import os
from ctypes import wintypes as W

from ..errors import BridgeError


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", INPUTUNION)]


class Native:
    def __init__(self):
        if os.name != "nt":
            raise BridgeError("Game capture and control currently require Windows.")
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.callback = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        signatures = {
            "EnumWindows": ([self.callback, W.LPARAM], W.BOOL),
            "GetWindowThreadProcessId": ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            "GetClientRect": ([W.HWND, C.POINTER(W.RECT)], W.BOOL),
            "ClientToScreen": ([W.HWND, C.POINTER(W.POINT)], W.BOOL),
            "IsWindowVisible": ([W.HWND], W.BOOL), "IsIconic": ([W.HWND], W.BOOL),
            "GetForegroundWindow": ([], W.HWND),
            "SetForegroundWindow": ([W.HWND], W.BOOL),
            "GetWindowTextW": ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
            "GetDpiForWindow": ([W.HWND], W.UINT),
            "SetProcessDpiAwarenessContext": ([C.c_void_p], W.BOOL),
            "GetThreadDpiAwarenessContext": ([], C.c_void_p),
            "GetAwarenessFromDpiAwarenessContext": ([C.c_void_p], C.c_int),
            "WindowFromPoint": ([W.POINT], W.HWND),
            "GetAncestor": ([W.HWND, W.UINT], W.HWND),
            "SendInput": ([W.UINT, C.POINTER(INPUT), C.c_int], W.UINT),
            "GetSystemMetrics": ([C.c_int], C.c_int),
            "GetAsyncKeyState": ([C.c_int], W.SHORT),
            "RegisterHotKey": ([W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL),
            "UnregisterHotKey": ([W.HWND, C.c_int], W.BOOL),
            "PeekMessageW": ([C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = args, result
        for name, args, result in [
            ("CreateMutexW", [C.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE),
            ("WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD),
            ("ReleaseMutex", [W.HANDLE], W.BOOL),
            ("CloseHandle", [W.HANDLE], W.BOOL),
        ]:
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        self.user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
        awareness = self.user.GetAwarenessFromDpiAwarenessContext(self.user.GetThreadDpiAwarenessContext())
        if awareness != 2:
            raise BridgeError("Per-monitor DPI awareness unavailable; run PA-Agent in its own Python process.")

    def send(self, event: INPUT) -> None:
        if self.user.SendInput(1, C.byref(event), C.sizeof(INPUT)) != 1:
            raise BridgeError(f"Windows rejected input (error {C.get_last_error()}); check elevation levels.")

    def move(self, x: int, y: int) -> None:
        left, top, width, height = [self.user.GetSystemMetrics(i) for i in (76, 77, 78, 79)]
        if not (left <= x < left + width and top <= y < top + height):
            raise BridgeError("Target point is outside the virtual desktop.")
        event = INPUT(type=0)
        event.mi = MOUSEINPUT(round((x - left) * 65535 / (width - 1)),
                             round((y - top) * 65535 / (height - 1)), 0, 0xC001, 0, 0)
        self.send(event)

    def mouse(self, flags: int, data: int = 0) -> None:
        event = INPUT(type=0)
        event.mi = MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)
        self.send(event)

    def key(self, code: int, up: bool = False, unicode: bool = False) -> None:
        event = INPUT(type=1)
        flags = (2 if up else 0) | (4 if unicode else (1 if code in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E) else 0))
        event.ki = KEYBDINPUT(0 if unicode else code, code if unicode else 0, flags, 0, 0)
        self.send(event)
