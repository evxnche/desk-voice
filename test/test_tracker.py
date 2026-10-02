"""Flight tracker: voice data shows at once, landing stops it, an unwatched screen leaves the cycle."""
import importlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

BOARD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "board")

SEEN = {"ok": True, "flight": "BA36", "seen": True, "lat": 55.0, "lon": 24.0, "alt_ft": 37000,
        "on_ground": False, "speed_kmh": 850, "track": 280, "vrate": 0, "over": "Lithuania",
        "km_left": 1700, "km_total": 6700, "eta_min": 130,
        "from": {"city": "Delhi", "code": "DEL", "lat": 28.6, "lon": 77.1},
        "to": {"city": "London", "code": "LHR", "lat": 51.5, "lon": -0.45}}
LANDED = dict(SEEN, on_ground=True, alt_ft=0, km_left=3, eta_min=None)


class Response:
    def __init__(self, body):
        self.status_code, self.content = 200, body

    def close(self):
        pass


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.now = [5000]
        self.gets = []
        sys.path.insert(0, BOARD)
        modules = {name: types.ModuleType(name) for name in
                   ("requests", "_thread", "framebuf", "dashboard", "font5", "secrets", "room", "flights", "palicon")}
        modules["secrets"].VOICE_URL = "https://example.test/api/voice"
        modules["secrets"].VOICE_KEY = "test"
        modules["room"].local_time = lambda: None
        modules["framebuf"].FrameBuffer = lambda *a: a
        modules["framebuf"].MONO_HLSB = 0
        def get(url, timeout=0):
            self.gets.append(url)
            meta = {"w": 248, "h": 250, "lat": 55.0, "lon": 20.0, "kmpx": 5, "labels": []}
            return Response(json.dumps(meta).encode() + b"\n" + bytes(248 * 250 // 8))
        modules["requests"].get = get
        self.patches = [patch.dict(sys.modules, modules),
                        patch.object(time, "ticks_ms", lambda: self.now[0], create=True),
                        patch.object(time, "ticks_diff", lambda a, b: a - b, create=True),
                        patch.object(time, "ticks_add", lambda a, b: a + b, create=True)]
        for p in self.patches:
            p.start()
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.temp.name)                     # track.json goes here
        sys.modules.pop("tracker", None)
        self.tracker = importlib.import_module("tracker")
        self.news = []
        self.tracker.on_news = self.news.append

    def tearDown(self):
        os.chdir(self.cwd)
        self.temp.cleanup()
        for p in reversed(self.patches):
            p.stop()
        sys.modules.pop("tracker", None)
        sys.path.remove(BOARD)

    def test_voice_data_shows_the_flight_and_map_at_once(self):
        self.tracker.start("BA36", SEEN)
        self.assertEqual(self.tracker.last["over"], "Lithuania")
        self.assertIsNotNone(self.tracker.mapdata)
        self.assertTrue(any("/api/trackmap" in u for u in self.gets))

    def test_landing_stops_following(self):
        self.tracker.start("BA36", SEEN)
        self.tracker.start("BA36", LANDED)               # "how's the flight doing?" once it's down
        self.assertEqual(self.news, ["BA36 has landed in London."])
        self.tracker.tick(lambda: True, True)
        self.assertEqual(self.tracker.flight, "")

    def test_same_flight_again_keeps_what_it_said(self):
        self.tracker.start("BA36", SEEN)
        self.tracker._said.add("descent")
        self.tracker.start("BA36")
        self.assertIn("descent", self.tracker._said)
        self.assertIsNotNone(self.tracker.last)

    def test_unwatched_screen_hides_after_20_minutes(self):
        self.tracker.start("BA36", SEEN)
        self.now[0] += 19 * 60 * 1000
        self.assertFalse(self.tracker.hidden())
        self.now[0] += 2 * 60 * 1000
        self.assertTrue(self.tracker.hidden())
        self.tracker._busy = True                        # no fetch: just looking at it
        self.tracker.tick(lambda: True, True)
        self.assertFalse(self.tracker.hidden())
        self.assertEqual(self.tracker.flight, "BA36")    # still followed for the landing line


if __name__ == "__main__":
    unittest.main()
