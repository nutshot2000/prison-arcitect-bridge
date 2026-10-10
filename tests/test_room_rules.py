import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pa_agent.state import room_rules
from pa_agent.state.prison_save import parse_prison

# the shape of the game's materials.txt room blocks (written for the test, not copied game data)
MATERIALS = """
BEGIN Room       Name None  END

BEGIN Room
    Name                 Kennel
    Research             Dogs
	BEGIN LikelyObject	Id		DogBowl		END
    BEGIN Requirement Type MinimumSize  x 5  y 5  END
    BEGIN Requirement Type Enclosed END
    BEGIN Requirement Type Object  Id DogCrate  END
    Properties           StaffCanUseFacilities
END

BEGIN Room
    Name                 Kitchen
    BEGIN Requirement Type Object  Id Cooker  END
    BEGIN Requirement Type Object  Id Fridge  Alt	TallFridge	END
    Qualification        KitchenInduction
END

BEGIN Room
    Name                 Shop
    BEGIN Requirement Type Indoor END
    BEGIN Requirement Type AdjacentObject Id ShopFront END
END
"""


class ParseTests(unittest.TestCase):
    def test_room_blocks(self):
        r = room_rules.parse_rooms(MATERIALS)
        self.assertEqual(sorted(r), ["Kennel", "Kitchen", "Shop"])
        self.assertEqual(r["Kennel"]["min"], [5, 5])
        self.assertTrue(r["Kennel"]["enclosed"])
        self.assertEqual(r["Kennel"]["objects"], [["DogCrate"]])
        self.assertEqual(r["Kennel"]["research"], "Dogs")
        self.assertEqual(r["Kitchen"]["objects"], [["Cooker"], ["Fridge", "TallFridge"]])
        self.assertEqual(r["Kitchen"]["qualification"], "KitchenInduction")
        self.assertEqual(r["Shop"]["adjacent"], [["ShopFront"]])
        self.assertIn("at least 5x5 inside", room_rules.describe("Kennel", r["Kennel"]))
        self.assertIn("DogCrate", room_rules.describe("Kennel", r["Kennel"]))

    def test_extract_caches_from_a_given_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, cache = Path(tmp) / "materials.txt", Path(tmp) / "rules.json"
            src.write_text(MATERIALS, encoding="latin-1")
            room_rules.extract(src, cache=cache)
            self.assertEqual(room_rules.cached(cache)["Kennel"]["min"], [5, 5])


class ReportUsesGameRules(unittest.TestCase):
    def test_small_kennel_without_crate_is_flagged(self):
        from pa_agent.state.report import room_problems
        cells = "\n".join(f'    BEGIN "{x} {y}" Mat ConcreteFloor Ind true Room.i 0 END'
                          for x in range(10, 15) for y in range(10, 14))   # 5x4
        save = parse_prison(f"""
BEGIN Cells
{cells}
END
BEGIN Objects
    Size 0
END
BEGIN Rooms
    Size 1
    BEGIN "[i 0]" Id.i 0 RoomType Kennel END
END
""")
        with mock.patch("pa_agent.state.room_rules.cached", return_value=room_rules.parse_rooms(MATERIALS)):
            probs = room_problems(save)
        self.assertEqual(len(probs), 1)
        self.assertIn("too small (5x4, needs 5x5)", probs[0])
        self.assertIn("missing DogCrate", probs[0])


class RoomPrecheck(unittest.TestCase):
    def test_room_refuses_a_kennel_below_the_game_minimum(self):
        from pa_agent.bridge.easy import Easy, EasyError
        from tests.test_easy import FakeBridge
        bridge = FakeBridge()
        with mock.patch("pa_agent.state.room_rules.load", return_value=room_rules.parse_rooms(MATERIALS)):
            with self.assertRaises(EasyError) as cm:
                Easy(bridge).run("room", ["kennel", "76", "57", "82", "62"])   # 7x6 with walls = 5x4 inside
        self.assertIn("at least 5x5 inside", str(cm.exception))
        self.assertNotIn("room", [c[0] for c in bridge.calls])   # nothing was ordered


if __name__ == "__main__":
    unittest.main()
