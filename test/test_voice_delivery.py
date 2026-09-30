"""Reply delivery checks without a board, network connection, or model calls."""
import ast
import importlib.util
import io
import os
import sys
import types
import unittest
from unittest.mock import patch


class VoiceDeliveryTests(unittest.TestCase):
    def setUp(self):
        names = ("requests", "_thread", "socket", "ssl", "network", "adpcm", "audio", "secrets",
                 "flights", "music", "home", "phone", "pal", "tracker", "memories", "alerts", "schedule", "plan")
        modules = {name: types.ModuleType(name) for name in names}
        modules["secrets"].VOICE_URL = "https://example.test/api/voice"
        modules["secrets"].VOICE_KEY = "test"
        modules["audio"].TX_BUF = 32000
        modules["audio"].starved = 0
        self.patch = patch.dict(sys.modules, modules)
        self.patch.start()
        path = os.path.join(os.path.dirname(__file__), "..", "board", "voice.py")
        spec = importlib.util.spec_from_file_location("voice_delivery", path)
        self.voice = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.voice)

    def tearDown(self):
        self.patch.stop()

    def test_short_download_is_rejected_instead_of_zero_padded(self):
        with self.assertRaises(OSError):
            self.voice._read_body(io.BytesIO(b"first words"), 100)

    def test_complete_download_preserves_all_bytes(self):
        data = b"reply audio" * 4000
        self.assertEqual(self.voice._read_body(io.BytesIO(data), len(data)), data)

    def test_cancelled_download_stops_between_reads(self):
        reads = []

        class Reader:
            def readinto(self, buf):
                reads.append(True)
                buf[:10] = b"\x00" * 10
                return 10

        with self.assertRaises(OSError):
            self.voice._read_body(Reader(), 100, stop=lambda: bool(reads))
        self.assertEqual(len(reads), 1)

    def test_long_reply_metadata_is_not_limited_to_four_kilobytes(self):
        head = b'{"reply":"' + b"a complete detailed explanation " * 400 + b'"}'
        body = head + b"\n" + b"\x00\x01" * 30000
        self.assertEqual(self.voice._head_end(body), len(head))
        with self.assertRaises(OSError):
            self.voice._head_end(b'{"reply":"unfinished')

    def test_long_audio_decodes_in_order_without_a_full_pcm_allocation(self):
        decoded = []

        class Decoder:
            def decode(self, data):
                decoded.append(bytes(data))
                return bytes(data) * 4

        self.voice.adpcm.Decoder = Decoder
        payload = bytes(range(256)) * 4000
        head = b'{"audio":"adpcm"}\n'
        body = head + payload
        chunks, total = self.voice._sound({"adpcm": True, "body": body, "done": True, "got": len(body)}, body, len(head) - 1)
        sizes = [len(piece) for piece in chunks]
        self.assertEqual(b"".join(decoded), payload)
        self.assertEqual(sum(sizes), total)
        self.assertLessEqual(max(sizes), 4096)

    def test_playback_starts_once_a_second_of_the_reply_is_in(self):
        head = b'{"reply":"the whole answer","audio":"adpcm"}\n'
        body = head + b"\x00" * 30000
        box = {"body": body, "got": 0, "status": 200}
        stream = types.SimpleNamespace(box=box, end=None, quit=False)

        class Face:
            next = 0
            thoughts = 0

            def __init__(self, keep=False):
                self.keep = keep

            def listening(self, *args):
                pass

            def thinking(self):
                self.thoughts += 1
                if self.thoughts >= 2:
                    box.update(got=len(head) + 8000)     # ~1 s of ADPCM; still downloading

            def speaking(self, *args):
                pass

            def voiced(self, sound):
                return sound

            def mouth(self):
                pass

        def speak(*args):
            self.assertNotIn("done", box, "playback waited for the whole download")
            self.assertEqual(box["got"], len(head) + 8000)
            return "done"

        self.voice.audio.WAKE_PHRASES = ["gee gee"]
        self.voice.audio.RATE = 15625
        self.voice.audio.record_speech = lambda *a, **kw: b"\x00" * 20000
        self.voice.phone.hush = lambda _: None
        pin = types.SimpleNamespace(value=lambda: 1)
        with patch.object(self.voice, "_Face", Face), \
                patch.object(self.voice, "_headers", lambda *a: {}), \
                patch.object(self.voice, "_start_stream", lambda _: stream), \
                patch.object(self.voice, "_sound", lambda *a: (iter([b"audio"]), 5)), \
                patch.object(self.voice, "_speak", speak), \
                patch.object(self.voice.time, "sleep_ms", lambda _: None, create=True):
            result = self.voice.ask(pin, pin, lambda: True, lambda _: True, lambda _: None,
                                    heard=(0, 1, 0, 0))
        self.assertEqual(result, {"board": []})

    def test_animation_keeps_only_recent_audio_levels(self):
        self.voice.audio.mean_level = lambda chunk: chunk[0]
        face = self.voice._Face()
        chunks = [bytes([index]) * 4 for index in range(100)]
        self.assertEqual(list(face.voiced(chunks)), chunks)
        self.assertEqual(face.played, 400)
        self.assertEqual(face.levels, list(range(93, 100)))   # the ~1 s the speaker buffer holds

    def test_screen_frames_do_not_starve_speaker_playback(self):
        queued = 0
        gaps = []
        started = False

        clock = [0]

        def advance(ms):
            nonlocal queued
            clock[0] += ms
            if started and ms > queued:
                gaps.append(ms - queued)
            queued = max(0, queued - ms)

        class Speaker:
            def write(self, data):
                nonlocal queued, started
                duration = len(data) * 1000 / (15625 * 2)
                capacity = 32000 * 1000 / (15625 * 2)
                queued += duration
                if queued > capacity:
                    advance(queued - capacity)
                started = True
                return len(data)

            def deinit(self):
                pass

        path = os.path.join(os.path.dirname(__file__), "..", "board", "audio.py")
        with open(path) as handle:
            tree = ast.parse(handle.read())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "play")
        ns = {"I2S": types.SimpleNamespace(TX=1, MONO=1, STEREO=2), "DOUT": 8, "TX_BUF": 32000, "RATE": 15625,
              "_i2s": lambda *a: Speaker(), "_es8311_init": lambda _: None,
              "_volume_reg": lambda v: v, "pa": lambda _: None,
              "time": types.SimpleNamespace(sleep_ms=advance, ticks_ms=lambda: int(clock[0]),
                                            ticks_diff=lambda a, b: a - b)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), path, "exec"), ns)

        def chunks():
            for _ in range(30):
                advance(10)  # decoding and caption bookkeeping
                yield bytes(4096)

        self.assertTrue(ns["play"](chunks(), mono=True, between=lambda: advance(80)))
        self.assertEqual(gaps, [], "screen updates delayed the next audio chunk beyond its playback time")
        self.assertEqual(ns["starved"], 0)
