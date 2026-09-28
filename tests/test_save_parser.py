import unittest

from pa_agent.state import parse_prison, summarize
from pa_agent.state.prison_save import SaveFormatError

SAMPLE = '''
Version              The_Jailhouse_1.02
NumCellsX            10
NumCellsY            8
Balance              1234.50
BEGIN Cells
    BEGIN "0 0"        Con 74.9  END
END
BEGIN Objects
    Size 2
    BEGIN "[i 0]"  Id.i 0  Id.u 5  Type Light  Pos.x 1.5  Pos.y 2.5  END
    BEGIN "[i 1]"
        Id.u 6
        Type Prisoner
        Category MaxSec
        Pos.x 3.0
        Pos.y 4.0
        BEGIN Bio  Forname "Big"  Surname Al  END
    END
END
BEGIN Rooms
    BEGIN "[i 0]"  RoomType Cell  BEGIN Connected END  END
END
BEGIN Research
    BEGIN Warden Desired false Progress 1.0 END
    BEGIN Dogs Desired true Progress 0.25 END
END
Tag a
Tag b
'''


class SaveParserTests(unittest.TestCase):
    def setUp(self):
        self.root = parse_prison(SAMPLE)

    def test_hierarchy_and_inline_sections(self):
        cells = self.root.section("Cells")
        self.assertEqual(cells.section("0 0").get("Con"), "74.9")
        objs = self.root.section("Objects").items_indexed()
        self.assertEqual(len(objs), 2)
        self.assertEqual(objs[1].section("Bio").get("Forname"), "Big")

    def test_repeated_keys_preserved(self):
        self.assertEqual(self.root.get_all("Tag"), ["a", "b"])
        self.assertEqual(self.root.to_dict()["Tag"], ["a", "b"])

    def test_typed_export(self):
        d = self.root.to_dict()
        self.assertEqual(d["NumCellsX"], 10)
        self.assertEqual(d["Balance"], 1234.5)
        self.assertIs(d["Research"]["Dogs"]["Desired"], True)

    def test_summary(self):
        s = summarize(self.root)
        self.assertEqual(s["prisoner_count"], 1)
        self.assertEqual(s["prisoners_sample"][0]["name"], "Big Al")
        self.assertEqual(s["rooms"], {"Cell": 1})
        self.assertEqual(s["research_done"], ["Warden"])
        self.assertEqual(s["research_in_progress"], {"Dogs": 0.25})

    def test_malformed(self):
        for bad in ("BEGIN A x 1", "END", "BEGIN A key END", "BEGIN"):
            with self.assertRaises(SaveFormatError):
                parse_prison(bad)


if __name__ == "__main__":
    unittest.main()
