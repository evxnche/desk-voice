"""Menu screen: every line fits the 400 px screen, pages fit between header and hint, every screen is listed."""
import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch

BOARD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "board")


class MenuTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, BOARD)
        stubs = {name: types.ModuleType(name) for name in ("dashboard", "font5", "room")}
        self.patch = patch.dict(sys.modules, stubs)
        self.patch.start()
        sys.modules.pop("menu", None)
        self.menu = importlib.import_module("menu")

    def tearDown(self):
        self.patch.stop()
        sys.modules.pop("menu", None)
        sys.path.remove(BOARD)

    def test_lines_fit_the_screen(self):
        for page in self.menu.PAGES:
            self.assertLessEqual(len(page), self.menu.PER_PAGE)
            self.assertEqual(page[0][0], "head")          # no page starts mid-section without its heading
            self.assertNotEqual(page[-1][0], "head")      # nor ends on a heading
            for kind, text in page:
                width = 6 * len(text) + 10 if kind == "head" else 8 * len(text) + 14
                self.assertLessEqual(width, 400, text)

    def test_every_item_is_on_a_page(self):
        items = [i for _, section in self.menu.SECTIONS for i in section]
        shown = [t for page in self.menu.PAGES for kind, t in page if kind == "item"]
        self.assertEqual(items, shown)

    def test_every_screen_is_listed(self):
        screens = self.menu.SECTIONS[0][1]
        for name in ("plan", "pal", "limits", "today", "game", "radar", "music", "my flight"):
            self.assertTrue(any(line.startswith(name + ":") for line in screens), name)

    def test_key_tap_cycles_pages(self):
        self.menu.enter()
        for _ in self.menu.PAGES:
            self.menu.next_page()
        self.assertEqual(self.menu.page, 0)


if __name__ == "__main__":
    unittest.main()
