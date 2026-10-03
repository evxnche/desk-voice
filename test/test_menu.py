"""Menu screen: every cell's text fits its column unbroken, pages fit between header and hint, every row
is shown once in order, and every screen is listed."""
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
        stubs = {name: types.ModuleType(name) for name in ("dashboard", "font5", "room", "schedule")}
        stubs["dashboard"].ascii = lambda s: s
        self.patch = patch.dict(sys.modules, stubs)
        self.patch.start()
        for name in ("menu", "plan"):
            sys.modules.pop(name, None)
        self.menu = importlib.import_module("menu")

    def tearDown(self):
        self.patch.stop()
        for name in ("menu", "plan"):
            sys.modules.pop(name, None)
        sys.path.remove(BOARD)

    def test_tables_are_392_px_wide(self):
        for cols, _ in self.menu.TABLES:
            self.assertEqual(sum(w for _, w in cols), 392)
            for title, w in cols:
                self.assertLessEqual(8 * len(title) + 6, w, title)

    def test_cells_wrap_without_cutting_words(self):
        for cols, rows in self.menu.TABLES:
            for row in rows:
                self.assertEqual(len(row), len(cols))
                for text, lines in zip(row, self.menu._cells(cols, row)):
                    self.assertEqual(" ".join(lines), text)

    def test_pages_fit_between_header_and_hint(self):
        m = self.menu
        for page in m.PAGES:
            y = m.TOP
            for cols, rows in page:
                self.assertTrue(rows)                      # no heading row left alone
                y += m.HEAD + sum(m._height(c) for c in rows) + m.GAP
            self.assertLessEqual(y - m.GAP, m.BOTTOM)

    def test_every_row_is_shown_once_in_order(self):
        m = self.menu
        wanted = [m._cells(cols, r) for cols, rows in m.TABLES for r in rows]
        shown = [c for page in m.PAGES for _, rows in page for c in rows]
        self.assertEqual(wanted, shown)

    def test_every_screen_is_listed(self):
        names = [row[0] for row in self.menu.TABLES[0][1]]
        for name in ("plan", "pal", "limits", "today", "game", "radar", "music", "my flight", "menu"):
            self.assertIn(name, names)

    def test_key_tap_cycles_pages(self):
        for _ in self.menu.PAGES:
            self.menu.next_page()
        self.assertEqual(self.menu.page, 0)


if __name__ == "__main__":
    unittest.main()
