import io, json, socket, threading, unittest
from pa_agent.bridge.client import BridgeClient, BridgeError
from pa_agent.bridge.mcp_server import Server

class FakeBridge(threading.Thread):
    """Mimics pa_bridge.dll + world.lua: status on connect, echoes exec results."""
    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket(); self.srv.bind(("127.0.0.1", 0)); self.srv.listen(1)
        self.port = self.srv.getsockname()[1]; self.seen = []
    def run(self):
        c, _ = self.srv.accept(); f = c.makefile("rwb")
        f.write(b'{"type":"status","bridge":"0.2.0","patched":true,"lua_seen":1,"ms_since_poll":5}\n'); f.flush()
        for line in f:
            line = line.strip()
            if line == b"STATUS":
                f.write(b'{"type":"status","bridge":"0.2.0","patched":true,"lua_seen":1,"ms_since_poll":7}\n'); f.flush(); continue
            req = json.loads(line); self.seen.append(req)
            f.write(b'{"type":"log","msg":"hello from lua"}\n')
            if req.get("op") == "exec" and "error" in req["code"]:
                out = {"type":"result","id":req["id"],"ok":False,"error":"agent:1: boom"}
            elif req.get("op") == "call":
                out = {"type":"result","id":req["id"],"ok":True,"result":{"fn":req["fn"],"args":req["args"]}}
            else:
                out = {"type":"result","id":req["id"],"ok":True,"result":42}
            f.write(json.dumps(out).encode()+b"\n"); f.flush()

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeBridge(); self.fake.start()
        self.client = BridgeClient(port=self.fake.port, timeout=3)
    def test_exec_call_status_logs(self):
        self.assertTrue(self.client.connect()["patched"])
        self.assertEqual(self.client.exec("return 6*7"), 42)
        self.assertEqual(self.client.call("zone", "Cell", 1, 2, 3, 4), {"fn": "zone", "args": ["Cell", 1, 2, 3, 4]})
        self.assertEqual(self.client.status()["ms_since_poll"], 7)
        self.assertIn("hello from lua", self.client.drain_logs())
        with self.assertRaises(BridgeError):
            self.client.exec("error('x')")
    def test_mcp(self):
        s = Server(self.client)
        out = io.StringIO()
        msgs = [{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}},
                {"jsonrpc":"2.0","method":"notifications/initialized"},
                {"jsonrpc":"2.0","id":2,"method":"tools/list"},
                {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"pa_lua","arguments":{"code":"return 1"}}},
                {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"pa_api","arguments":{"fn":"zone","args":["Cell",1,1,4,4]}}},
                {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"pa_lua","arguments":{"code":"error()"}}}]
        s.serve(io.StringIO("\n".join(json.dumps(m) for m in msgs)+"\n"), out)
        replies = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual([r["id"] for r in replies], [1,2,3,4,5])
        names = [t["name"] for t in replies[1]["result"]["tools"]]
        self.assertIn("pa_lua", names); self.assertIn("pa_help", names); self.assertNotIn("pa_camera", names)
        self.assertIn("42", replies[2]["result"]["content"][0]["text"])
        self.assertIn('"fn": "zone"', replies[3]["result"]["content"][0]["text"])
        self.assertTrue(replies[4]["result"]["isError"])

class NoGameTest(unittest.TestCase):
    def test_unreachable(self):
        c = BridgeClient(port=1)
        with self.assertRaises(BridgeError) as cm: c.exec("return 1")
        self.assertIn("Is Prison Architect running", str(cm.exception))

if __name__ == "__main__":
    unittest.main()
