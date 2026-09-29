"""Client for the in-game PA agent bridge (pa_bridge.dll + mod world.lua).

Protocol: newline-delimited JSON over TCP on 127.0.0.1:8972.
Requests  -> {"id": n, "op": "exec"|"call"|"ping", ...}
Responses <- {"type": "result", "id": n, "ok": bool, "result"|"error": ...}
Also      <- {"type": "log", "msg": "..."} (print()/DebugOut from any script)
             {"type": "status", ...} (from the DLL itself, on connect / STATUS)
"""
from __future__ import annotations

import itertools
import json
import socket
import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PORT = 8972


class BridgeError(RuntimeError):
    pass


class BridgeTimeout(BridgeError):
    pass


@dataclass
class BridgeClient:
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    timeout: float = 10.0
    logs: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._sock: socket.socket | None = None
        self._buf = b""
        self._ids = itertools.count(1)
        self.last_status: dict | None = None

    # ---- connection -------------------------------------------------------
    def connect(self) -> dict:
        self.close()
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=3)
        except OSError as exc:
            raise BridgeError(
                f"Cannot reach the bridge on {self.host}:{self.port} ({exc}). "
                "Is Prison Architect running with pa_bridge (GLU32.dll) installed?") from exc
        self._sock.settimeout(self.timeout)
        status = self._read_until(lambda m: m.get("type") == "status", 3.0)
        self.last_status = status
        return status

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._buf = b""

    def _ensure(self):
        if self._sock is None:
            self.connect()

    def _send_line(self, text: str):
        """Send one line. If the connection died (e.g. the game restarted), reconnect once and resend.
        Only the send is retried: nothing reached the game on a failed send."""
        data = text.encode("utf-8") + b"\n"
        for attempt in (1, 2):
            if self._sock is None:
                self.connect()
            try:
                self._sock.sendall(data)
                return
            except OSError:
                self.close()
                if attempt == 2:
                    raise BridgeError("lost connection to the game; is Prison Architect still running?")

    def _read_message(self, deadline: float) -> dict:
        assert self._sock is not None
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeTimeout("timed out waiting for the game")
            self._sock.settimeout(remaining)
            try:
                chunk = self._sock.recv(1 << 20)
            except socket.timeout as exc:
                raise BridgeTimeout("timed out waiting for the game") from exc
            except OSError as exc:
                self.close()
                raise BridgeError(f"lost connection to the game ({exc}); it may have crashed or closed") from exc
            if not chunk:
                self.close()
                raise BridgeError("bridge closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        try:
            return json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return {"type": "raw", "line": line.decode("utf-8", errors="replace")}

    def _read_until(self, pred, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            msg = self._read_message(deadline)
            if msg.get("type") == "log":
                self.logs.append(msg.get("msg", ""))
                del self.logs[:-500]
            if msg.get("type") == "status":
                self.last_status = msg
            if pred(msg):
                return msg

    # ---- requests ---------------------------------------------------------
    def status(self) -> dict:
        self._ensure()
        self._send_line("STATUS")
        return self._read_until(lambda m: m.get("type") == "status", 3.0)

    def request(self, payload: dict, timeout: float | None = None) -> Any:
        self._ensure()
        rid = next(self._ids)
        payload = {**payload, "id": rid}
        self._send_line(json.dumps(payload, separators=(",", ":")))
        try:
            msg = self._read_until(lambda m: m.get("type") == "result" and m.get("id") == rid,
                                   timeout or self.timeout)
        except BridgeTimeout:
            hint = ""
            try:
                st = self.status()
                age = st.get("ms_since_poll")
                if not st.get("lua_seen"):
                    hint = " The in-game runtime has not connected: load a prison with the 'AI Bridge' mod enabled."
                elif age is not None and age > 2000:
                    if st.get("pump") == "ready":
                        hint = (f" The in-game script has not run for {age} ms although the bridge can serve a paused "
                                "game: the game is probably in a menu, loading, or minimised.")
                    else:
                        hint = (f" The in-game script has not polled for {age} ms; the game is probably paused "
                                "or in a menu (bridge DLL before 0.3 only works while the game runs).")
            except BridgeError:
                pass
            raise BridgeTimeout("timed out waiting for the game." + hint) from None
        if not msg.get("ok"):
            raise BridgeError(msg.get("error") or "unknown error")
        return msg.get("result")

    def exec(self, code: str, timeout: float | None = None) -> Any:
        return self.request({"op": "exec", "code": code}, timeout)

    def call(self, fn: str, *args: Any, timeout: float | None = None) -> Any:
        return self.request({"op": "call", "fn": fn, "args": list(args), "nargs": len(args)}, timeout)

    def ping(self) -> Any:
        return self.request({"op": "ping"}, 5.0)

    def drain_logs(self) -> list[str]:
        out, self.logs = self.logs, []
        return out
