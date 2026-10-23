import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bgpwatch.gui import counterpart_theme  # noqa: E402

NAMES = {"nord-dark", "nord-light", "vapor-dark", "vapor-light", "solo-dark", "bootstrap-light"}


class ThemeTests(unittest.TestCase):
    def test_pairs_flip_both_ways(self):
        self.assertEqual(counterpart_theme("nord-dark", NAMES), "nord-light")
        self.assertEqual(counterpart_theme("nord-light", NAMES), "nord-dark")

    def test_theme_without_a_pair_is_unchanged(self):
        self.assertEqual(counterpart_theme("solo-dark", NAMES), "solo-dark")
        self.assertEqual(counterpart_theme("bootstrap-light", NAMES), "bootstrap-light")
        self.assertEqual(counterpart_theme("weird", NAMES), "weird")

    def test_every_installed_ttkbootstrap_theme_has_a_pair(self):
        try:
            import ttkbootstrap as tb
        except ImportError:
            self.skipTest("ttkbootstrap not installed")
        names = set(tb.Style().theme_names())
        for n in names:
            self.assertNotEqual(counterpart_theme(n, names), n, n)


if __name__ == "__main__":
    unittest.main()
