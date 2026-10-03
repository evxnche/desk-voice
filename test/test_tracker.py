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
EST = {"ok": True, "flight": "AF12", "seen": False, "est": True, "lat": 50.0, "lon": -30.0, "track": 260,
       "speed_kmh": 730, "over": "the open sea", "km_left": 2600, "km_total": 5840, "eta_min": 215,
       "schedule": {"state": "air", "off_uk": "2:05pm", "on_uk": "10:40pm"},
       "from": {"city": "Paris", "code": "CDG", "lat": 49.0, "lon": 2.5},
       "to": {"city": "New York", "code": "JFK", "lat": 40.6, "lon": -73.8}}


class Response:
    def __init__(self, body):
        self.status_code, self.content = 200, body

    def json(self):
        return json.loads(self.content)

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


    def test_estimated_position_draws_the_plane_and_keeps_gliding(self):
        self.tracker.start("AF12", EST)
        self.assertTrue(self.tracker.last["est"])
        self.assertIsNotNone(self.tracker.mapdata)
        self.tracker.info = dict(EST, seen=False, est=False)    # a cheap fetch since: no FlightAware
        self.tracker.info.pop("schedule")
        self.tracker.fetched_ms = self.now[0]
        start = self.tracker.where()
        self.now[0] += 10 * 60 * 1000                    # 10 minutes later, still heading west
        self.assertLess(self.tracker.where()[0], start[0])
        self.assertEqual(self.tracker.sched["on_uk"], "10:40pm")

    def test_flightaware_says_landed(self):
        self.tracker.start("AF12", dict(EST, est=False, schedule={"state": "landed", "on_uk": "9:12pm"}))
        self.assertTrue(self.tracker.landed)
        self.assertEqual(self.news, ["AF12 has landed in New York."])

    def test_flightaware_asked_at_most_every_15_minutes(self):
        self.tracker.start("AF12")
        def fetch():
            self.gets.clear()
            self.tracker._worker()
            return [u for u in self.gets if "/api/track?" in u][0]
        get = self.tracker.requests.get
        self.tracker.requests.get = lambda url, timeout=0: (self.gets.append(url), Response(json.dumps(
            dict(EST, est=False, seen=False)).encode()) if "/api/track?" in url else get(url))[1]
        self.assertIn("&fa=1", fetch())
        self.now[0] += 60 * 1000
        self.assertNotIn("&fa=1", fetch())
        self.now[0] += 15 * 60 * 1000
        self.assertIn("&fa=1", fetch())


if __name__ == "__main__":
    unittest.main()
