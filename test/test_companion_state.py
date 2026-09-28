"""Host-side checks for small pieces of companion state."""
import importlib
import errno
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

    def test_memories_trim_at_140_utf8_bytes_without_splitting_emoji(self):
        with tempfile.TemporaryDirectory() as directory:
            memories = importlib.import_module("memories")
            memories.PATH = os.path.join(directory, "memories.json")
            self.assertTrue(memories.add("🦀" * 36))
            self.assertEqual(["🦀" * 35], memories.list_all())
            self.assertEqual(140, len(memories.list_all()[0].encode("utf-8")))
            self.assertTrue(memories.add("A" * 139 + "🦀"))
            self.assertEqual("A" * 139, memories.list_all()[1])

    def test_memories_recover_from_invalid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            memories = importlib.import_module("memories")
            memories.PATH = os.path.join(directory, "memories.json")
            with open(memories.PATH, "w") as handle:
                handle.write("not json")
            self.assertEqual([], memories.list_all())
            self.assertFalse(memories.delete(0))
            self.assertFalse(memories.add(""))

    def test_failed_memory_write_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            memories = importlib.import_module("memories")
            memories.PATH = os.path.join(directory, "memories.json")
            self.assertTrue(memories.add("Keep this preference"))
            with open(memories.PATH) as source:
                original = source.read()

            def partial_write(_, target):
                target.write("[")
                raise OSError("disk full")

            with patch.object(memories.json, "dump", side_effect=partial_write):
                self.assertFalse(memories.add("New preference"))
            with open(memories.PATH) as source:
                self.assertEqual(original, source.read())
            self.assertEqual(["Keep this preference"], memories.list_all())

    def test_memory_save_replaces_existing_file_on_fat_style_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            memories = importlib.import_module("memories")
            memories.PATH = os.path.join(directory, "memories.json")
            self.assertTrue(memories.add("First"))
            actual_rename = os.rename

            def fat_rename(source, target):
                if os.path.exists(target):
                    raise OSError(errno.EEXIST, "target exists")
                return actual_rename(source, target)

            with patch.object(memories.os, "rename", side_effect=fat_rename):
                self.assertTrue(memories.add("Second"))
            self.assertEqual(["First", "Second"], memories.list_all())

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

    def test_alert_duplicate_is_accepted_again_after_short_window(self):
        a = self.alerts
        self.assertTrue(a.add("Claude", "Desk", "needs", "Approve", "10:00"))
        self.assertFalse(a.add("Claude", "Desk", "needs", "Approve", "10:01"))
        self.now += a.DEDUP_MS + 1
        self.assertTrue(a.add("Claude", "Desk", "needs", "Approve", "10:03"))
        self.assertEqual(2, len(a.queue))

    def test_done_resolves_matching_needs_without_erasing_other_alerts(self):
        a, c = self.alerts, self.companion
        pending = []
        a.add("Claude", "Desk", "needs", "Approve", "10:00")
        a.queue_pending(pending, a.queue[-1])
        c.needs_you("Claude", "Desk")
        a.add("Codex", "Other", "needs", "Review", "10:00")
        a.queue_pending(pending, a.queue[-1])
        c.needs_you("Codex", "Other")
        a.add("Friend", "Chat", "message", "Hello", "10:00")
        a.add("Claude", "Desk", "done", "Finished", "10:01")
        a.resolve("Claude", "Desk", pending)
        c.resolve_needs("Claude", "Desk")
        self.assertEqual("Codex", a.latest_needs()["agent"])
        self.assertEqual("Codex", a.next_pending(pending)["agent"])
        self.assertNotIn("Claude", [item["alert"]["agent"] for item in pending])
        self.assertEqual(["Codex"], [item["key"][1] for item in c.queue if item["kind"] == "needs"])
        self.assertTrue(any(item["kind"] == "message" for item in a.queue))
        self.assertTrue(a.add("Claude", "Desk", "needs", "Approve", "10:02"))

    def test_focus_defers_routine_pending_alerts_without_blocking_needs(self):
        pending = []
        for n in range(25):
            alert = {"agent": "Agent", "project": "Desk", "kind": "done" if n % 2 else "message",
                     "message": "Update %d" % n, "at": "10:00"}
            self.alerts.queue_pending(pending, alert, focused=True)
        self.assertLessEqual(len(pending), self.alerts.MAX_PENDING)
        needs = {"agent": "Claude", "project": "Desk", "kind": "needs", "message": "Approve", "at": "10:01"}
        self.alerts.queue_pending(pending, needs, focused=True)
        self.assertEqual(needs, self.alerts.next_pending(pending, focused=True))
        self.assertIsNone(self.alerts.next_pending(pending, focused=True))
        summary = self.alerts.next_pending(pending, focused=False)
        self.assertEqual("summary", summary["kind"])
        self.assertEqual(25, summary["count"])
        self.assertIn("Update 24", summary["message"])
        self.assertEqual([], pending)

    def test_pending_alert_keeps_its_own_snapshot(self):
        pending = []
        alert = {"agent": "Claude", "project": "Desk", "kind": "done", "message": "Original", "at": "10:00"}
        self.alerts.queue_pending(pending, alert)
        alert["message"] = "Changed"
        self.assertEqual("Original", self.alerts.next_pending(pending)["message"])

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
