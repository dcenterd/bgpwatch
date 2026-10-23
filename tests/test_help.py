import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch import helpdata as hd  # noqa: E402


class HelpTests(unittest.TestCase):
    def setUp(self):
        self.mods, self.edges, self.external = hd.import_matrix()

    def test_matrix_reads_real_imports(self):
        for pair in (("engine", "collectors"), ("live", "collectors"), ("alerts", "store"),
                     ("gui", "layout"), ("gui", "helpview"), ("main", "gui"), ("main", "engine")):
            self.assertIn(pair, self.edges, pair)
        self.assertNotIn(("models", "gui"), self.edges)
        self.assertIn("Route", self.edges[("gui", "models")])

    def test_every_module_is_documented_and_drawn(self):
        for m in self.mods:
            self.assertIn(m, hd.MODULE_INFO, f"{m} has no description in helpdata.MODULE_INFO")
            self.assertIn(m, hd.BOXES, f"{m} is missing from the component diagram")

    def test_diagram_is_consistent(self):
        for f, t, *_ in hd.EDGES:
            self.assertIn(f, hd.BOXES)
            self.assertIn(t, hd.BOXES)
        for key, (x, y, w, h, *_rest) in hd.BOXES.items():
            self.assertLessEqual(x + w, hd.DIAGRAM_SIZE[0], key)
            self.assertLessEqual(y + h, hd.DIAGRAM_SIZE[1], key)
        names = list(hd.BOXES)
        for i, a in enumerate(names):                      # no two boxes overlap
            ax, ay, aw, ah = hd.BOXES[a][:4]
            for b in names[i + 1:]:
                bx, by, bw, bh = hd.BOXES[b][:4]
                self.assertFalse(ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah,
                                 f"{a} overlaps {b}")

    def test_every_command_line_option_is_documented(self):
        import re
        src = (Path(__file__).resolve().parents[1] / "main.py").read_text()
        flags = re.findall(r'add_argument\("(--[a-z-]+)"', src)
        documented = " ".join(n for g, n, *_ in hd.PARAMS if g == "Command line")
        self.assertGreater(len(flags), 10)
        for f in flags:
            self.assertIn(f, documented, f"{f} is missing from helpdata.PARAMS")

    def test_every_saved_setting_is_documented(self):
        import re
        src = (Path(__file__).resolve().parents[1] / "bgpwatch" / "gui.py").read_text()
        keys = set(re.findall(r'\bd\["([a-z_]+)"\] =', src))
        text = " ".join(n for g, n, *_ in hd.PARAMS if g.startswith("Saved settings"))
        for k in keys:
            self.assertIn(k, text, f"settings key {k} is missing from helpdata.PARAMS")

    def test_params_are_well_formed(self):
        for row in hd.PARAMS:
            self.assertEqual(len(row), 5, row)
            self.assertTrue(all(isinstance(c, str) and c for c in row), row)

    def test_svg_and_csv(self):
        svg = hd.diagram_svg()
        self.assertTrue(svg.startswith("<svg") and svg.rstrip().endswith("</svg>"))
        csv = hd.matrix_csv().splitlines()
        self.assertEqual(len(csv), len(self.mods) + 1)
        self.assertEqual(csv[0].split(",")[0], "importer")


if __name__ == "__main__":
    unittest.main()
