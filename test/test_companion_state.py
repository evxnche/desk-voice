"""Host-side checks for small pieces of companion state."""
import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


BOARD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "board")


class CompanionStateTests(unittest.TestCase):
    def setUp(self):
        self.modules = patch.dict(sys.modules, {
            "dashboard": types.ModuleType("dashboard"),
            "font5": types.ModuleType("font5"),
            "audio": types.ModuleType("audio"),
            "pal": types.ModuleType("pal"),
            "room": types.ModuleType("room"),
        })
        self.modules.start()
        sys.path.insert(0, BOARD)
        for name in ("alerts", "companion", "memories"):
            sys.modules.pop(name, None)
        self.alerts = importlib.import_module("alerts")
        self.companion = importlib.import_module("companion")
        self.now = 1000
        self.ticks = patch.object(self.companion.time, "ticks_ms", lambda: self.now, create=True)
        self.diff = patch.object(self.companion.time, "ticks_diff", lambda a, b: a - b, create=True)
        self.ticks.start()
        self.diff.start()
        sys.modules["pal"].quiet_hours = lambda: False

    def tearDown(self):
        self.diff.stop()
        self.ticks.stop()
        self.modules.stop()
        sys.path.remove(BOARD)
        for name in ("alerts", "companion", "memories"):
            sys.modules.pop(name, None)

    def test_memories_are_normalized_bounded_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            memories = importlib.import_module("memories")
            memories.PATH = os.path.join(directory, "memories.json")
            self.assertTrue(memories.add("  My   usual\nfocus session is 40 minutes  "))
            self.assertFalse(memories.add("My usual focus session is 40 minutes"))
            self.assertEqual(["My usual focus session is 40 minutes"], memories.list_all())
            for n in range(11):
                self.assertTrue(memories.add("Memory %d" % n))
            self.assertFalse(memories.add("Thirteenth"))
            self.assertEqual(12, len(memories.list_all()))
            self.assertTrue(memories.delete(0))
            self.assertNotIn("My usual focus session is 40 minutes", memories.list_all())
            self.assertTrue(memories.clear())
            self.assertEqual([], memories.list_all())

    def test_memories_recover_from_invalid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            memories = importlib.import_module("memories")
            memories.PATH = os.path.join(directory, "memories.json")
            with open(memories.PATH, "w") as handle:
                handle.write("not json")
            self.assertEqual([], memories.list_all())
            self.assertFalse(memories.delete(0))
            self.assertFalse(memories.add(""))

    def test_alerts_deduplicate_and_expose_latest_needs_copy(self):
        a = self.alerts
        self.assertTrue(a.add("Claude", "Desk", "needs", "Approve", "10:00"))
        self.assertFalse(a.add("Claude", "Desk", "needs", "Approve", "10:01"))
        self.assertEqual(1, len(a.queue))
        latest = a.latest_needs()
        latest["message"] = "changed"
        self.assertEqual("Approve", a.latest_needs()["message"])
        self.assertTrue(a.add("Claude", "Desk", "done", "Complete", "10:02"))
        for n in range(6):
            a.add("Agent", str(n), "done", "Complete", "10:03")
        self.assertEqual(6, len(a.queue))
        self.assertIsNone(a.latest_needs())

    def test_focus_defers_ordinary_lines_but_allows_urgent_needs(self):
        c = self.companion
        c.flight_news("Flight landed")
        self.assertIsNone(c.next_line(lambda _: False, focused=True))
        c.needs_you("Claude", "Desk")
        c.needs_you("Claude", "Desk")
        self.assertEqual(2, len(c.queue))
        self.assertEqual(("needs", "Claude needs you in Desk."), c.next_line(lambda _: False, focused=True))
        self.assertIsNone(c.next_line(lambda _: False, focused=True))
        self.assertEqual(("flight", "Flight landed"), c.next_line(lambda _: False))

    def test_all_lines_expire_and_queue_is_bounded(self):
        c = self.companion
        for n in range(20):
            c.needs_you("Agent", str(n))
        self.assertLessEqual(len(c.queue), c.MAX_QUEUE)
        self.now += c.STALE_MS + 1
        self.assertIsNone(c.next_line(lambda _: False))
        self.assertEqual([], c.queue)

    def test_hearing_quiet_hours_and_flight_gap_are_preserved(self):
        c = self.companion
        c.flight_news("Flight landed")
        self.assertIsNone(c.next_line(lambda _: True))
        sys.modules["pal"].quiet_hours = lambda: True
        self.assertIsNone(c.next_line(lambda _: False))
        sys.modules["pal"].quiet_hours = lambda: False
        self.assertEqual(("flight", "Flight landed"), c.next_line(lambda _: False))
        c.check_rain({"rain_soon": "noon"})
        self.assertIsNone(c.next_line(lambda _: False))
        self.now += c.GAP_MS
        self.assertEqual(("rain", "Rain's on the way, starting around noon."), c.next_line(lambda _: False))


if __name__ == "__main__":
    unittest.main()
