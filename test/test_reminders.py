"""Reminders (board/reminders.py): saved as clock times, due ones come off the list once, nothing is
set or fired before the clock is synced, and they can be cancelled one at a time or all at once."""
import importlib
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BOARD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "board")


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sys.path.insert(0, BOARD)
        sys.modules.pop("reminders", None)
        self.r = importlib.import_module("reminders")
        self.r.PATH = os.path.join(self.tmp.name, "reminders.json")
        self.now = [1_800_000_000]
        self.patch = patch.object(self.r.time, "time", lambda: self.now[0])
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        sys.path.remove(BOARD)
        sys.modules.pop("reminders", None)
        self.tmp.cleanup()

    def test_due_once_at_its_time(self):
        self.assertTrue(self.r.add("reset your Codex limits", 30))
        self.now[0] += 29 * 60
        self.assertEqual(self.r.due(), [])
        self.now[0] += 60
        self.assertEqual(self.r.due(), ["reset your Codex limits"])
        self.assertEqual(self.r.due(), [])

    def test_not_before_the_clock_is_set(self):
        with patch.object(self.r.time, "localtime", lambda *a: (2000,) + (0,) * 8):
            self.assertFalse(self.r.add("stretch", 5))
            self.assertEqual(self.r.due(), [])

    def test_cancel_one_or_all(self):
        self.r.add("stretch", 5)
        self.r.add("pay rent", 60)
        self.assertTrue(self.r.cancel("Stretch"))
        self.assertEqual([x["text"] for x in self.r._load()], ["pay rent"])
        self.assertTrue(self.r.cancel())
        self.assertEqual(self.r._load(), [])


if __name__ == "__main__":
    unittest.main()
