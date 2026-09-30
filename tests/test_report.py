import unittest

from pa_agent.state.prison_save import parse_prison
from pa_agent.state.report import situation, situation_text, utility_map

SAVE = """
Balance 1000
BEGIN Cells
    BEGIN "1 1" Mat ConcreteFloor Ind true Room.i 0 END
    BEGIN "2 1" Mat BrickWall END
END
BEGIN Objects
    Size 5
    BEGIN "[i 0]" Id.i 0 Type PowerStation Pos.x 5.5 Pos.y 5.5 Powered true On true Demand 40.0 Capacity 50 END
    BEGIN "[i 1]" Id.i 1 Type PowerStation Pos.x 9.5 Pos.y 5.5 Switch false Powered true Capacity 50 Overloaded 2 END
    BEGIN "[i 2]" Id.i 2 Type WaterPumpStation Pos.x 5.5 Pos.y 9.5 Powered true On true END
    BEGIN "[i 3]" Id.i 3 Type Cooker Pos.x 1.5 Pos.y 1.5 END
    BEGIN "[i 4]"
        Id.i 4
        Type Prisoner
        Pos.x 1.5
        Pos.y 1.5
        Cell.i -1
        BEGIN Needs
            ComplainNeedId.i 6
            BEGIN Needs
                BEGIN "[i 6]" id.i 6 Type Hygiene Charge 100.0 END
            END
        END
    END
END
BEGIN Rooms
    Size 1
    BEGIN "[i 0]" Id.i 0 RoomType Cell RequirementsFailed true END
END
BEGIN Electricity
    BEGIN "3 1 1" END
END
BEGIN Water
    BEGIN "1 1" PipeType 2 END
END
BEGIN StatsTracker
    BEGIN Today EscapedPrisoners 3.0 EntityDeath 1.0 NumIncidents 7.0 END
    BEGIN Persistent TotalEscapedPrisoners 5.0 TotalDeaths 2.0 END
END
"""


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.root = parse_prison(SAVE)
        self.s = situation(self.root)

    def test_text_booleans_are_read(self):
        # the parser keeps 'true' as text; the report must still see power
        st = {p["at"]: p["on"] for p in self.s["power_stations"]}
        self.assertTrue(st[(5, 5)])
        self.assertFalse(st[(9, 5)])          # Switch false = tripped/off
        self.assertTrue(self.s["pumps"][0]["powered"])
        self.assertEqual(self.s["unpowered"], {"Cooker": 1})

    def test_people_and_events(self):
        self.assertEqual(self.s["prisoners"], 1)
        self.assertEqual(self.s["prisoners_where"], {"Cell": 1})
        self.assertEqual(self.s["prisoners_without_cell"], 1)
        self.assertEqual(self.s["complaining_about"], {"Hygiene": 1})
        self.assertEqual(self.s["rooms_failing"], ["Cell"])
        text = situation_text(self.s)
        self.assertIn("TODAY escaped 3", text)
        self.assertIn("OFF", text)

    def test_room_checker(self):
        from pa_agent.state.report import room_problems
        probs = room_problems(self.root)
        # the Cell room is 1 cell with no bed and no toilet
        self.assertEqual(len(probs), 1)
        self.assertIn("too small", probs[0])
        self.assertIn("missing Bed", probs[0])
        self.assertIn("missing Toilet", probs[0])

    def test_verify_orders(self):
        from pa_agent.state.report import verify_orders
        orders = [{"type": "Cooker", "x": 1, "y": 1, "t": 0},        # the cooker at 1.5,1.5 exists
                  {"type": "Cooker", "x": 7, "y": 7, "t": 0},        # nothing there, ordered long ago
                  {"type": "Toilet", "x": 3, "y": 3, "t": 990}]      # recent: still coming
        v = verify_orders(self.root, orders, now=1000)
        self.assertEqual(v["installed"], 1)
        self.assertEqual(v["waiting"], 1)
        self.assertEqual(v["failed"], ["Cooker@7,7"])

    def test_utility_map_marks(self):
        m = utility_map(self.root, 0, 0, 10, 10, "both")
        rows = m.splitlines()
        # rows[0] title, rows[1] ruler, rows[2] is y=0; each row has a 5-char y prefix
        self.assertEqual(rows[3][5 + 1], "!")   # the cooker at 1,1 has no power
        self.assertEqual(rows[3][5 + 3], "-")   # cable at 3,1
        self.assertIn("P", m)
        self.assertIn("p", m)
        self.assertIn("W", m)
        # water layer: the small pipe at 1,1 must be drawn (PipeType is text in the save)
        wm = utility_map(self.root, 0, 0, 10, 10, "water").splitlines()
        self.assertEqual(wm[3][5 + 1], "s")

    def test_unreachable_construction(self):
        from pa_agent.state.report import pending_work
        # a fence line at x=5 splits a 10x6 map; the workman is west of it
        fence = "\n".join(f'    BEGIN "5 {y}" Mat Fence END' for y in range(6))
        save = f"""
NumCellsX 10
NumCellsY 6
BEGIN Cells
{fence}
END
BEGIN Objects
    BEGIN "[i 0]" Id.i 0 Type Workman Pos.x 1.5 Pos.y 1.5 END
END
BEGIN WorkQ
    BEGIN Items
        BEGIN "[i 0]" Id 1 Type Construct CellX 2 CellY 2 MatType BrickWall END
        BEGIN "[i 1]" Id 2 Type Construct CellX 7 CellY 2 MatType BrickWall END
        BEGIN "[i 2]" Id 3 Type Construct CellX 8 CellY 2 MatType BrickWall END
        BEGIN "[i 3]" Id 4 Type Construct CellX 6 CellY 4 MatType ConcreteTiles END
    END
END
"""
        p = pending_work(parse_prison(save))
        self.assertEqual(p["construction_jobs"], 4)
        # 6,4 is next to the fence but on the far side; 7,2 and 8,2 touch -> two areas
        self.assertEqual(sum(a["cells"] for a in p["unreachable"]), 3)
        self.assertEqual(p["unreachable"][0], {"cells": 2, "x1": 7, "y1": 2, "x2": 8, "y2": 2})

    def test_tunnels(self):
        from pa_agent.state.report import tunnels
        fence = "\n".join(f'    BEGIN "{x} 2" Mat Fence END' for x in range(2, 9)) + "\n" + \
                "\n".join(f'    BEGIN "{x} 8" Mat Fence END' for x in range(2, 9))
        save = f"""
BEGIN Cells
{fence}
END
BEGIN Tunnels
    LastDigTime 1.0
    BEGIN "5 5" Dug 1.0 Entrance true END
    BEGIN "5 4" Dug 1.0 END
    BEGIN "5 3" Dug 1.0 END
    BEGIN "5 2" Dug 1.0 END
    BEGIN "5 1" Dug 1.0 Entrance true Discovered true END
    BEGIN "7 6" Dug 1.0 Entrance true END
END
"""
        t = tunnels(parse_prison(save))
        self.assertEqual(len(t), 2)
        self.assertEqual(t[0]["cells"], 5)
        self.assertTrue(t[0]["outside_fence"])     # reaches y=1, beyond the fence at y=2
        self.assertTrue(t[0]["discovered"])
        self.assertFalse(t[1]["outside_fence"])
        self.assertEqual(t[1]["entrances"], [(7, 6)])


if __name__ == "__main__":
    unittest.main()
