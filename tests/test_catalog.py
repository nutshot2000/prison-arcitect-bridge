import tempfile
import unittest
from pathlib import Path

from pa_agent.state import catalog

# the shape of the game's materials / language files (written for the test, not copied game data)
MATERIALS = """
BEGIN Material   Name None  END
BEGIN Material
    Name                 ConcreteFloor
    Price                -10
    IndoorOutdoor        2
END
BEGIN Material
    Name                 BrickWall
    BlockMovement        true
    ObjectRequired       Brick
END
BEGIN Material
    Name                 Demolish
END
BEGIN Object
    Name                 Bed
    Width                1
    Height               2
    Price                -200
    BEGIN Sprite x 1 y 2 END
    Properties           StaticObject
END
BEGIN Object
    Name                 Guard
    Properties           Entity
    Properties           Staff
END
"""
MATERIALS_DLC = """
BEGIN Material
    Name                 FancyWoodFloor
    Price                -50
    DLC                  SomePack
END
BEGIN Object
    Name                 GardenLamp
    Width                1
    Height               1
    Price                -80
    Research             GroundsKeeping
    Properties           StaticObject
    Properties           Electrical
END
BEGIN Object
    Name                 WashBasket
    Price                -100
END
"""
BASE_LANGUAGE = """
material_concretefloor                   Concrete Floor
object_bed                               Bed
"""
DLC_LANGUAGE = """
material_FancyWoodFloor                  Fancy Wood Floor
object_GardenLamp                        Lamp (Garden)
"""
FILES = {catalog.SOURCES[0]: MATERIALS, catalog.SOURCES[1]: MATERIALS_DLC,
         catalog.LANGUAGE[0]: BASE_LANGUAGE, catalog.LANGUAGE[1]: DLC_LANGUAGE}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "catalog.json"
        self.items = catalog.extract(cache=self.cache, files=FILES)

    def tearDown(self):
        self.tmp.cleanup()

    def test_kinds(self):
        it = self.items
        self.assertEqual(it["ConcreteFloor"]["kind"], "floor")
        self.assertEqual(it["BrickWall"]["kind"], "wall")
        self.assertEqual(it["Demolish"]["kind"], "internal")
        self.assertEqual(it["Bed"]["kind"], "object")
        self.assertEqual(it["Guard"]["kind"], "character")
        self.assertEqual(it["WashBasket"]["kind"], "item")
        self.assertNotIn("None", it)  # one-line block

    def test_fields(self):
        bed, lamp, fancy = self.items["Bed"], self.items["GardenLamp"], self.items["FancyWoodFloor"]
        self.assertEqual(bed["size"], [1, 2])
        self.assertEqual(bed["cost"], 200)  # the game stores a purchase as a negative price
        self.assertEqual(lamp["research"], "GroundsKeeping")
        self.assertTrue(lamp["power"])
        self.assertEqual(fancy["dlc"], "SomePack")
        self.assertEqual(fancy["display"], "Fancy Wood Floor")  # DLC language file, mixed-case key
        self.assertEqual(self.items["ConcreteFloor"]["display"], "Concrete Floor")  # base file, lower-case key

    def test_search(self):
        hits = [n for n, _ in catalog.search(self.items, ["wood", "floor"])]
        self.assertEqual(hits, ["FancyWoodFloor"])
        self.assertEqual([n for n, _ in catalog.search(self.items, ["lamp"])], ["GardenLamp"])
        self.assertEqual(catalog.search(self.items, ["guard"]), [])  # characters are not buildable
        self.assertEqual([n for n, _ in catalog.search(self.items, ["floor"], ("floor",))],
                         ["ConcreteFloor", "FancyWoodFloor"])

    def test_cache_and_describe(self):
        self.assertEqual(catalog.load(cache=self.cache)["Bed"]["size"], [1, 2])
        text = catalog.describe("GardenLamp", self.items["GardenLamp"])
        self.assertIn('"Lamp (Garden)"', text)
        self.assertIn("$80", text)
        self.assertIn("research GroundsKeeping", text)
        self.assertIn("needs power", text)


if __name__ == "__main__":
    unittest.main()
