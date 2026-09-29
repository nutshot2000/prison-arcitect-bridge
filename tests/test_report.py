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


if __name__ == "__main__":
    unittest.main()
