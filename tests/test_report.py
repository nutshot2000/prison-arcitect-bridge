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
        self.assertFalse(t[0]["discovered"])      # only the exit outside was found; the entrance at 5,5 was not
        self.assertFalse(t[1]["outside_fence"])
        self.assertEqual(t[1]["entrances"], [(7, 6)])


if __name__ == "__main__":
    unittest.main()


GRID_SAVE = """
BEGIN Objects
    Size 6
    BEGIN "[i 0]" Id.i 0 Type PowerStation Pos.x 11.5 Pos.y 11.5 Switch false Overloaded 1 Demand 0 Capacity 50 END
    BEGIN "[i 1]" Id.i 1 Type WaterPumpStation Pos.x 11.5 Pos.y 21.5 END
    BEGIN "[i 2]" Id.i 2 Type Cooker Pos.x 17.0 Pos.y 11.5 END
    BEGIN "[i 3]" Id.i 3 Type Cooker Pos.x 20.0 Pos.y 11.5 END
    BEGIN "[i 4]" Id.i 4 Type Fridge Pos.x 30.0 Pos.y 30.5 END
    BEGIN "[i 5]" Id.i 5 Type PowerStation Pos.x 41.5 Pos.y 11.5 Switch true Demand 0 Capacity 50 END
END
BEGIN Electricity
    BEGIN "13 11 1" END
    BEGIN "14 11 1" END
    BEGIN "15 11 1" END
    BEGIN "16 11 1" END
    BEGIN "11 13 1" END
    BEGIN "11 14 1" END
    BEGIN "11 15 1" END
    BEGIN "11 16 1" END
    BEGIN "11 17 1" END
    BEGIN "11 18 1" END
    BEGIN "11 19 1" END
    BEGIN "11 20 1" END
END
"""


class GridLoadTests(unittest.TestCase):
    def test_tripped_station_shows_what_is_wired_to_it(self):
        from pa_agent.state.report import grid_loads
        g = {s["at"]: s for s in grid_loads(parse_prison(GRID_SAVE))}
        a = g[(11, 11)]
        # pump via the line south; the cable ends at x=16, under the 2-wide cooker at 16..17 but not the one
        # at 19..20; the fridge is not on any cable
        self.assertEqual(a["objects"], {"WaterPumpStation": 1, "Cooker": 1})
        self.assertEqual(a["estimated_load"], 25 + 12)
        self.assertFalse(a["on"])
        self.assertEqual(a["shared_with"], [])
        self.assertEqual(g[(41, 11)]["estimated_load"], 0)

    def test_stations_and_gates_are_not_reported_as_never_built(self):
        from pa_agent.state.report import verify_orders
        save = parse_prison("""
BEGIN Objects
    Size 2
    BEGIN "[i 0]" Id.i 0 Type PowerStation Pos.x 131.5 Pos.y 31.5 END
    BEGIN "[i 1]" Id.i 1 Type RoadGate Pos.x 141.5 Pos.y 4.5 END
END
""")
        v = verify_orders(save, [{"type": "PowerStation", "x": 130, "y": 30, "t": 0},
                                 {"type": "RoadGate", "x": 138, "y": 4, "t": 0},
                                 {"type": "PowerStation", "x": 100, "y": 30, "t": 0}], now=10000)
        self.assertEqual(v["installed"], 2)
        self.assertEqual(v["failed"], ["PowerStation@100,30"])


class TunnelCellTests(unittest.TestCase):
    def test_dug_cells_only(self):
        from pa_agent.state.report import tunnel_cells
        root = parse_prison("""
BEGIN Tunnels
    LastDigTime 5.0
    BEGIN "116 77" Dug 1.000000 Discovered true END
    BEGIN "117 77" Dug 0.400000 END
    BEGIN "118 77" Dug 0.000000 END
    BEGIN Diggers Size 0 END
END
""")
        self.assertEqual(tunnel_cells(root), [(116, 77), (117, 77)])


class DeploymentTests(unittest.TestCase):
    """Sectors / DeploymentSchedule as the game saved them on 10 Oct 2026 (shape only, values made up)."""
    SAVE = """
BEGIN Rooms
    BEGIN "[i 0]"  Id.i 3  RoomType Yard  END
    BEGIN "[i 1]"  Id.i 4  RoomType Canteen  END
END
BEGIN Sectors
    NextSectorId 9
    BEGIN Sectors
        Size 9
        BEGIN "[i 0]"
            id 0  TopLeft.x 0  TopLeft.y 0  BottomRight.x 9  BottomRight.y 9  Outside true
            BEGIN Stations   Size 0  END
        END
        BEGIN "[i 5]"
            id 5  TopLeft.x 1  TopLeft.y 2  BottomRight.x 3  BottomRight.y 4  Room.i 3  Zone MaxSecOnly
            BEGIN DogStations
                Size 1
                BEGIN "[i 0]"  Entity.i -1  Entity.u -1  LastOccupied 0.0  END
            END
            CustomZone2 true
        END
        BEGIN "[i 8]"
            id 8  TopLeft.x 5  TopLeft.y 5  BottomRight.x 7  BottomRight.y 7  Room.i 4
            BEGIN Stations
                Size 2
                BEGIN "[i 0]"  Entity.i 40  Entity.u 77  END
                BEGIN "[i 1]"  Entity.i -1  Entity.u -1  END
            END
        END
    END
END
BEGIN DeploymentSchedule
    BEGIN ChosenSchedule END
    BEGIN Schedules
        BEGIN "Schedule 0"
            BEGIN i  SectorId 5  NumGuards 0  NumDogs 1  PriorityLevel 2  END
        END
    END
END
"""

    def test_sectors(self):
        from pa_agent.state.report import deployment
        secs = {s["id"]: s for s in deployment(parse_prison(self.SAVE))}
        self.assertEqual(set(secs), {0, 5, 8})
        self.assertEqual(secs[0]["zone"], "Shared")
        self.assertTrue(secs[0]["outside"])
        self.assertEqual(secs[0]["posts"], {})
        yard = secs[5]
        self.assertEqual((yard["room"], yard["zone"], yard["priority"]), ("Yard", "MaxSecOnly", 2))
        self.assertEqual(yard["posts"], {"dog handler": (0, 1)})
        self.assertEqual(yard["custom"], [2])
        self.assertEqual(secs[8]["room"], "Canteen")
        self.assertEqual(secs[8]["posts"], {"guard": (1, 2)})

    def test_food_targets(self):
        from pa_agent.state.report import deployment
        save = """
BEGIN Rooms
    BEGIN "[i 0]"  Id.i 1  RoomType Kitchen  END
    BEGIN "[i 1]"  Id.i 2  RoomType Canteen  END
    BEGIN "[i 2]"  Id.i 3  RoomType Dormitory  END
END
BEGIN Sectors
    BEGIN Sectors
        Size 4
        BEGIN "[i 1]"  id 1  Room.i 1  BEGIN Targets    Size 1  "[i 0]" 2  END  END
        BEGIN "[i 2]"  id 2  Room.i 2  END
        BEGIN "[i 3]"  id 3  Room.i 3  ManualTargets true  BEGIN Targets    Size 1  "[i 0]" 2  END  END
    END
END
"""
        secs = {s["id"]: s for s in deployment(parse_prison(save))}
        self.assertEqual((secs[1]["targets"], secs[1]["manual"]), ([2], False))  # kitchen -> canteen, automatic
        self.assertEqual((secs[3]["targets"], secs[3]["manual"]), ([2], True))   # dorm eats there, set by hand
        self.assertEqual(secs[2]["targets"], [])
