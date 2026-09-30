"""Board voice headers, command wiring, and safe remote memory controls."""
import ast
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

BOARD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "board")


class RemoteMemoryTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, BOARD)
        self.modules = {}
        for name in ("adpcm", "audio", "secrets", "flights", "music", "home", "phone", "pal", "tracker",
                     "requests", "network", "dashboard", "room", "timer", "alerts", "remote", "usage", "plan"):
            self.modules[name] = types.ModuleType(name)
        self.modules["secrets"].VOICE_URL = "https://example.test/api/voice"
        self.modules["secrets"].VOICE_KEY = "test"
        self.modules["music"].headers = lambda: {"X-Music": "connected"}
        self.modules["tracker"].headers = lambda: {"X-Track": "BA36"}
        self.modules["alerts"].latest_needs = lambda: None
        self.modules["alerts"].queue = []
        self.modules["alerts"].clear = lambda: None
        self.modules["remote"].page = lambda: "page"
        self.modules["usage"].connected = lambda: []
        self.modules["plan"].headers = lambda: {}
        self.modules["audio"].volume = 7
        self.patch = patch.dict(sys.modules, self.modules)
        self.patch.start()
        self.memories = importlib.import_module("memories")
        self.voice = importlib.import_module("voice")
        self.clock = patch.object(self.voice.time, "ticks_ms", lambda: 1000, create=True)
        self.diff = patch.object(self.voice.time, "ticks_diff", lambda a, b: a - b, create=True)
        self.clock.start()
        self.diff.start()
        self.temp = tempfile.TemporaryDirectory()
        self.memories.PATH = os.path.join(self.temp.name, "memories.json")

    def tearDown(self):
        self.temp.cleanup()
        self.diff.stop()
        self.clock.stop()
        self.patch.stop()
        sys.path.remove(BOARD)
        for name in ("voice", "memories"):
            sys.modules.pop(name, None)

    def test_voice_sends_explicit_context_headers(self):
        self.memories.add("Focus for 40 minutes")
        self.modules["alerts"].latest_needs = lambda: {
            "agent": "Claude", "project": "Desk", "kind": "needs", "message": "Approve", "at": "10:00"}
        headers = self.voice._headers("")
        import base64
        self.assertEqual(["Focus for 40 minutes"], json.loads(base64.b64decode(headers["X-Memories"])))
        self.assertEqual("Approve", json.loads(base64.b64decode(headers["X-Agent-Alert"]))["message"])
        self.assertEqual("connected", headers["X-Music"])
        self.assertEqual("BA36", headers["X-Track"])

    def test_context_headers_stay_within_relay_limits(self):
        for index in range(12):
            self.memories.add(("🦀" * 130) + str(index))
        self.modules["alerts"].latest_needs = lambda: {
            "agent": "🦀" * 80, "project": "🦀" * 80, "kind": "needs",
            "message": "🦀" * 500, "at": "10:00"}
        headers = self.voice._headers("")
        self.assertLessEqual(len(headers["X-Memories"]), 2500)
        self.assertLessEqual(len(headers["X-Agent-Alert"]), 1800)

    def test_remote_page_builds_memory_rows_with_text_content(self):
        spec = importlib.util.spec_from_file_location("remote_under_test", os.path.join(BOARD, "remote.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        page = module.page()
        self.assertIn("<h2>MEMORY</h2>", page)
        self.assertIn("value.textContent=entry", page)
        self.assertIn("/memories/add", page)
        self.assertIn("/memories/delete", page)
        self.assertIn("/memories/clear", page)
        self.assertNotIn("innerHTML", page)

    def test_main_memory_command_and_route_handlers(self):
        with open(os.path.join(BOARD, "main.py")) as handle:
            source = ast.parse(handle.read())
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in ("run", "handle")]
        fake_time = types.SimpleNamespace(ticks_ms=lambda: 1000, ticks_add=lambda a, b: a + b)
        env = {"memories": self.memories, "alerts": self.modules["alerts"], "secrets": self.modules["secrets"],
               "json": json, "time": fake_time, "MESSAGE_MS": 8000,
               "screen": "pal", "SCREENS": ("pal",), "show": lambda name: shown.append(name),
               "redraw": lambda: None, "remote": self.modules["remote"]}
        shown = []
        exec(compile(ast.Module(body=functions, type_ignores=[]), "main.py", "exec"), env)
        self.assertTrue(env["run"]({"do": "memory_add", "text": "Focus for 40 minutes"}))
        self.assertEqual(["Focus for 40 minutes"], self.memories.list_all())
        self.assertEqual(["Focus for 40 minutes"], json.loads(env["handle"]("GET", "/memories", {}, b"")[2]))
        self.assertTrue(json.loads(env["handle"]("POST", "/memories/delete", {"index": "0"}, b"")[2])["ok"])
        self.assertEqual([], self.memories.list_all())
        self.assertTrue(json.loads(env["handle"]("POST", "/memories/add", {"text": "Keep mornings quiet"}, b"")[2])["ok"])
        self.assertTrue(env["run"]({"do": "memory_delete", "text": "keep mornings quiet"}))
        self.assertEqual([], self.memories.list_all())
        self.assertTrue(json.loads(env["handle"]("POST", "/memories/add", {"text": "Other"}, b"")[2])["ok"])
        self.assertTrue(json.loads(env["handle"]("POST", "/memories/clear", {}, b"")[2])["ok"])
        self.assertEqual([], self.memories.list_all())
        self.assertFalse(env["run"]({"do": "alert_show"}))
        self.modules["alerts"].latest_needs = lambda: {"kind": "needs", "message": "Approve"}
        self.assertTrue(env["run"]({"do": "alert_show"}))
        self.assertEqual("alert", shown[-1])

    def test_memory_mutation_routes_reject_get(self):
        with open(os.path.join(BOARD, "main.py")) as handle:
            source = ast.parse(handle.read())
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in ("run", "handle")]
        env = {"memories": self.memories, "alerts": self.modules["alerts"], "secrets": self.modules["secrets"],
               "json": json, "remote": self.modules["remote"]}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "main.py", "exec"), env)
        for path in ("/memories/add", "/memories/delete", "/memories/clear"):
            self.assertEqual(404, env["handle"]("GET", path, {"text": "Surprise", "index": "0"}, b"")[0])
        self.assertEqual([], self.memories.list_all())

    def test_accepted_agent_done_route_resolves_waiting_request(self):
        with open(os.path.join(BOARD, "main.py")) as handle:
            source = ast.parse(handle.read())
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "handle"]
        events = []
        alerts = self.modules["alerts"]
        alerts.queue = [{"agent": "Claude", "project": "Desk", "kind": "needs", "message": "Approve"}]

        def add(agent, project, kind, message, at):
            alerts.queue.append({"agent": agent, "project": project, "kind": kind, "message": message})
            return True

        alerts.add = add
        alerts.resolve = lambda agent, project, pending: events.append(("alert", agent, project))
        alerts.queue_pending = lambda pending, alert, focused=False: events.append(("pending", alert["kind"]))
        companion = types.SimpleNamespace(resolve_needs=lambda agent, project: events.append(("speech", agent, project)))
        env = {"alerts": alerts, "companion": companion, "pending_alert": [],
               "secrets": self.modules["secrets"], "json": json, "local_clock": lambda: "10:01",
               "_focused": lambda: False, "active_alert": None, "screen": "pal"}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "main.py", "exec"), env)
        result = env["handle"]("POST", "/agent", {"k": "test"},
                               b'{"agent":"Claude","project":"Desk","kind":"done","message":"Finished"}')
        self.assertEqual(200, result[0])
        self.assertEqual([("alert", "Claude", "Desk"), ("speech", "Claude", "Desk"),
                          ("pending", "done")], events)

    def test_board_reports_failed_memory_command_after_playback(self):
        self.assertEqual("Memory not saved", self.voice._run_board_commands(
            [{"do": "memory_add", "text": "No space"}], lambda cmd: False))
        self.assertEqual("Memory not removed", self.voice._run_board_commands(
            [{"do": "memory_delete", "text": "Missing"}], lambda cmd: False))
        self.assertIsNone(self.voice._run_board_commands(
            [{"do": "memory_clear"}], lambda cmd: True))


if __name__ == "__main__":
    unittest.main()
