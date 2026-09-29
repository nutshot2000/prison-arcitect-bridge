import unittest

from pa_agent.bridge.client import BridgeError
from pa_agent.bridge.easy import Easy, EasyError, explain

STATE = {"clock": "day 2 08:05", "paused": False, "speed": 1, "money": 12345, "map": {"w": 150, "h": 120},
         "prisoners_total": 3, "prisoners": {"Normal": 3}, "cell_capacity_total": 0, "cell_capacity": {},
         "staff": {"Workman": 8}, "zones_made": [], "native": True}


class FakeBridge:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def call(self, fn, *args, timeout=None):
        self.calls.append((fn, args))
        if self.fail and fn == self.fail[0]:
            raise BridgeError(self.fail[1])
        if fn == "state":
            return dict(STATE)
        if fn == "progress":
            return {"construction": {"still_pending": 4, "finished_since_last_check": 2, "pending_sample": ["BrickWall@1,1"]},
                    "objects": {"Bed": {"installed": 1, "ordered": 2}}}
        if fn == "room":
            return {"room": "Kitchen", "built": "walls, floor and a Door at 5,9", "inside": {"x1": 1, "y1": 1, "x2": 8, "y2": 8},
                    "furniture": ["Cooker@1,1"], "zoned": True, "note": "Kitchen note."}
        if fn == "hire":
            return {"hired": args[1], "type": args[0], "cost": 500 * args[1], "money_left": 1000, "arrives_at": {"x": 141, "y": 1}}
        if fn == "overview":
            return {"block": 3, "rows": ["..=", "#_."]}
        if fn in ("regime", "regime_preset", "set_regime"):
            return {"category": 0, "hours": [f"{h:02d} Sleep" for h in range(24)], "totals": {"Sleep": 24},
                    "note": "n"}
        if fn in ("remove_cable", "remove_pipe"):
            return {"removed_cells": 4, "note": "gone"}
        if fn == "demolish":
            return {"walls_replaced": 2, "note": "floor"}
        if fn == "remove":
            return {"at": {"x": 5.5, "y": 6.5}, "note": "dismantled"}
        return {}


class EasyTests(unittest.TestCase):
    def test_status_text(self):
        out = Easy(FakeBridge()).run("status", [])
        self.assertIn("money $12,345", out)
        self.assertIn("prisoners 3", out)
        self.assertIn("Bed 1/2", out)

    def test_room_passes_ints_and_default_door(self):
        b = FakeBridge()
        out = Easy(b).run("room", ["kitchen", "0", "0", "9", "9"])
        self.assertEqual(b.calls[-1], ("room", ("kitchen", 0, 0, 9, 9, "south")))
        self.assertIn("zoned Kitchen", out)

    def test_hire_count(self):
        b = FakeBridge()
        out = Easy(b).run("hire", ["Guard", "2"])
        self.assertEqual(b.calls[-1], ("hire", ("Guard", 2)))
        self.assertIn("hired 2 Guard", out)

    def test_errors_get_hints(self):
        with self.assertRaises(EasyError) as cm:
            Easy(FakeBridge(fail=("hire", "Doctor needs the Health research first"))).run("hire", ["Doctor"])
        self.assertIn("HINT", str(cm.exception))
        self.assertIn("research", explain("x", "Janitor needs the Cleaning research first"))

    def test_wrong_arguments_show_usage(self):
        with self.assertRaises(EasyError) as cm:
            Easy(FakeBridge()).run("room", ["kitchen"])
        self.assertIn("Usage: room <kind>", str(cm.exception))
        with self.assertRaises(EasyError):
            Easy(FakeBridge()).run("room", ["kitchen", "a", "b", "c", "d"])

    def test_help_and_unknown(self):
        e = Easy(FakeBridge())
        self.assertIn("room <kind>", e.run("help", []))
        self.assertIn("Sizes that work", e.run("help", ["room"]))
        self.assertIn("Unknown verb", e.run("fly", []))

    def test_regime_forms(self):
        b = FakeBridge()
        e = Easy(b)
        self.assertIn("Sleep 24", e.run("regime", []))
        e.run("regime", ["balanced"])
        self.assertEqual(b.calls[-1], ("regime_preset", ("balanced",)))
        e.run("regime", ["13", "16", "Free", "Time"])
        self.assertEqual(b.calls[-1], ("set_regime", (13, 16, "Free Time")))
        with self.assertRaises(EasyError):
            e.run("regime", ["13", "16"])

    def test_remove_forms(self):
        b = FakeBridge()
        e = Easy(b)
        self.assertIn("4 cells", e.run("remove", ["cable", "1", "2", "3", "4"]))
        self.assertEqual(b.calls[-1], ("remove_cable", (1, 2, 3, 4)))
        e.run("remove", ["wall", "1", "1", "1", "5"])
        self.assertEqual(b.calls[-1][0], "demolish")
        self.assertIn("Bench", e.run("remove", ["Bench", "5", "6"]))
        with self.assertRaises(EasyError):
            e.run("remove", ["pipe", "1", "2"])

    def test_look_overview(self):
        out = Easy(FakeBridge()).run("look", [])
        self.assertIn("1 char = 3x3", out)
        self.assertIn("#_.", out)


class ImageTests(unittest.TestCase):
    def test_bmp_to_png_roundtrip(self):
        import struct
        import tempfile
        import zlib
        from pathlib import Path
        from pa_agent.bridge.image import downscale, read_bmp, write_png
        w, h = 3, 2
        stride = (w * 3 + 3) & ~3
        pad = bytes(stride - w * 3)
        rows_bottom_up = [bytes([0, 0, 255] * w) + pad,   # red in BGR: the bottom row
                          bytes([255, 0, 0] * w) + pad]   # blue in BGR: the top row
        body = b"".join(rows_bottom_up)
        hdr = b"BM" + struct.pack("<IHHI", 54 + len(body), 0, 0, 54) + \
            struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(body), 0, 0, 0, 0)
        with tempfile.TemporaryDirectory() as d:
            bmp = Path(d) / "a.bmp"
            bmp.write_bytes(hdr + body)
            W, H, rows = read_bmp(bmp)
            self.assertEqual((W, H), (3, 2))
            self.assertEqual(rows[0][:3], bytes([0, 0, 255]))   # top row: blue as RGB
            self.assertEqual(rows[1][:3], bytes([255, 0, 0]))   # bottom row: red as RGB
            png = write_png(Path(d) / "a.png", W, H, rows).read_bytes()
            self.assertEqual(png[1:4], b"PNG")
            raw = zlib.decompressobj().decompress(png[png.index(b"IDAT") + 4:])
            self.assertEqual(raw[:4], bytes([0, 0, 0, 255]))  # filter byte, then the blue pixel
            self.assertEqual(downscale(W, H, rows, 2)[:2], (1, 1))


if __name__ == "__main__":
    unittest.main()
