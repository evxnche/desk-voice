"""Procrastination cop (mac/deskpal-mac.py): nags after 15 minutes of distraction in work hours, again
every 15 minutes, starts over after a 2-minute break, stays quiet out of hours, and is proud on a
focused day."""
import datetime
import importlib.util
import os
import unittest
from unittest.mock import patch

PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mac", "deskpal-mac.py")


def load():
    spec = importlib.util.spec_from_file_location("deskpal_mac", PATH)
    mod = importlib.util.module_from_spec(spec)
    with patch("builtins.open", unittest.mock.mock_open(read_data="key")):
        spec.loader.exec_module(mod)
    return mod


class CopTests(unittest.TestCase):
    def setUp(self):
        self.mac = load()
        self.said, self.site, self.clock = [], "YouTube", [datetime.datetime(2026, 10, 5, 10, 0), 0.0]
        mac = self.mac
        mac.say_on_board = lambda kind, text: self.said.append(kind)
        mac.distraction = lambda: self.site
        mac.idle_seconds = lambda: 0
        test = self

        class Clock(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return test.clock[0]
        mac.datetime = type("dt", (), {"datetime": Clock})
        mac.time = type("t", (), {"time": staticmethod(lambda: test.clock[1])})
        self.cop = mac.Cop()

    def run_for(self, seconds, step=5):
        for _ in range(int(seconds // step)):
            self.clock[1] += step
            self.clock[0] += datetime.timedelta(seconds=step)
            self.cop.tick()

    def test_nags_after_15_minutes_then_every_15(self):
        self.run_for(14 * 60)
        self.assertEqual(self.said, [])
        self.run_for(2 * 60)
        self.assertEqual(self.said, ["cop"])
        self.run_for(15 * 60)
        self.assertEqual(self.said, ["cop", "cop"])

    def test_a_break_starts_the_count_again(self):
        self.run_for(10 * 60)
        self.site = None
        self.run_for(3 * 60)
        self.site = "YouTube"
        self.run_for(10 * 60)
        self.assertEqual(self.said, [])

    def test_quiet_out_of_work_hours(self):
        self.clock[0] = datetime.datetime(2026, 10, 4, 10, 0)      # a Sunday
        self.run_for(30 * 60)
        self.assertEqual(self.said, [])

    def test_proud_on_a_focused_day(self):
        self.site = None
        self.run_for(8 * 3600, step=30)                             # 10:00 to 18:00
        self.assertEqual(self.said, ["proud"])


if __name__ == "__main__":
    unittest.main()
