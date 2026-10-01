"""Host checks for the small Pal and voice-screen drawing contracts."""
import importlib
import sys
import types
import unittest


class Canvas:
    def __init__(self):
        self.ops = []

    def fill_rect(self, x, y, w, h, color):
        assert x >= 0 and y >= 0 and w > 0 and h > 0
        self.ops.append((x, y, w, h, color))

    def fill(self, color):
        self.ops.append((0, 0, 400, 300, color))

    def hline(self, x, y, width, color):
        self.fill_rect(x, y, width, 1, color)

    def rect(self, x, y, w, h, color):
        self.fill_rect(x, y, w, 1, color)
        self.fill_rect(x, y + h - 1, w, 1, color)
        self.fill_rect(x, y, 1, h, color)
        self.fill_rect(x + w - 1, y, 1, h, color)


class Display:
    def __init__(self):
        self.canvas = Canvas()
        self.canvas_buffer = bytearray(400 * 300 // 8)
        self.texts = []

    def text(self, value, x, y, color=1):
        self.texts.append((value, x, y, 1, color))

    def text_large(self, value, x, y, scale=2, color=1):
        self.texts.append((value, x, y, scale, color))

    def show(self):
        pass


def load_pal():
    display = Display()
    dashboard = types.ModuleType("dashboard")
    dashboard.display = lambda: display
    dashboard.ascii = str
    room = types.ModuleType("room")
    room.local_time = lambda: (2026, 9, 28, 9, 41, 0, 0, 0)
    room.weather = {"temp_c": 16, "condition": "Cloudy"}
    room.clock = lambda h, m: "%d:%02d%s" % ((h % 24 - 1) % 12 + 1, m, "am" if h % 24 < 12 else "pm")
    audio = types.ModuleType("audio")
    font5 = types.ModuleType("font5")
    font5.text = lambda fb, s, x, y: display.texts.append((s, x, y, 0, 1))
    old = {name: sys.modules.get(name) for name in ("dashboard", "room", "audio", "font5", "pal")}
    sys.modules.update(dashboard=dashboard, room=room, audio=audio, font5=font5)
    try:
        sys.path.insert(0, "board")
        sys.modules.pop("pal", None)
        pal = importlib.import_module("pal")
    finally:
        sys.path.remove("board")
        for name, value in old.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
    return pal, display


class SmallPalTests(unittest.TestCase):
    def test_every_pose_stays_inside_exported_box_and_differs(self):
        sys.path.insert(0, "board")
        try:
            icon = importlib.import_module("palicon")
        finally:
            sys.path.remove("board")
        drawings = []
        for pose in ("limits", "today", "focus", "music", "flights", "tracking", "alert", "done"):
            canvas = Canvas()
            icon.draw(canvas, 0, 0, pose, phase=0)
            self.assertTrue(canvas.ops, pose)
            for x, y, w, h, _ in canvas.ops:
                self.assertLessEqual(x + w, icon.WIDTH, pose)
                self.assertLessEqual(y + h, icon.HEIGHT, pose)
            drawings.append(tuple(canvas.ops))
        self.assertEqual(len(drawings), len(set(drawings)))

    def test_motion_is_restrained_to_two_frames(self):
        icon = importlib.import_module("palicon")
        frames = []
        for phase in (0, 1, 2):
            canvas = Canvas()
            icon.draw(canvas, 0, 0, "music", phase)
            frames.append(canvas.ops)
        self.assertNotEqual(frames[0], frames[1])
        self.assertEqual(frames[0], frames[2])


class PalScreenTests(unittest.TestCase):
    def test_captions_fit_three_large_lines_and_paginate(self):
        pal, display = load_pal()
        lines = pal.wrap(" ".join("interesting" for _ in range(14)))
        self.assertGreater(len(lines), 3)
        self.assertTrue(all(len(line) <= 23 for line in lines))
        first = pal.caption_page(lines, 0)
        last = pal.caption_page(lines, 0.99)
        self.assertEqual(len(first), 3)
        self.assertNotEqual(first, last)
        pal.draw("speak", caption=first, t=0)
        rendered = [item for item in display.texts if item[0] in first]
        self.assertEqual(len(rendered), 3)
        self.assertTrue(all(scale == 2 and x >= 0 and x + len(text) * 16 <= 400
                            for text, x, _, scale, _ in rendered))

    def test_long_unbroken_caption_paginates_without_clipping(self):
        pal, _ = load_pal()
        word = "x" * 80
        lines = pal.wrap(word)
        self.assertEqual("".join(lines), word)
        self.assertTrue(all(len(line) <= 23 for line in lines))

    def test_reply_cue_on_full_screen_and_header_pal_over_a_screen(self):
        pal, display = load_pal()
        pal.draw("waiting", 0.5, t=0)
        self.assertIn("SAY YOUR REPLY", [text for text, *_ in display.texts])
        self.assertTrue(any(w > 0 and y >= 286 for _, y, w, _, _ in display.canvas.ops))
        buf = display.canvas_buffer
        buf[24 * 50:25 * 50] = b"\xff" * 50          # the header rule
        for y in range(4, 20):                       # header text on the right half (x 200-399)
            buf[y * 50 + 25:y * 50 + 50] = b"\x01" * 25
        for mood, label in (("wait", "your turn"), ("listen", "listening"), ("think", "thinking"), ("talk", "talking")):
            display.texts.clear()
            display.canvas.ops.clear()
            pal.header(mood, level=0.5, left=0.5, t=0)
            self.assertEqual([label], [text for text, *_ in display.texts])
            # only in the header, and only where nothing was drawn, so no text is covered
            self.assertTrue(all(x + w <= 192 and y + h <= 24 for x, y, w, h, _ in display.canvas.ops))
        for y in range(4, 20):                       # a header with no room: nothing drawn
            buf[y * 50:y * 50 + 50] = b"\x01" * 50
        display.canvas.ops.clear()
        pal.header("talk", t=0)
        self.assertEqual(display.canvas.ops, [])

    def test_status_rotates_weather_and_agent_usage_every_six_seconds(self):
        pal, _ = load_pal()
        limits = {"providers": [{"name": "Claude", "windows": [{"used": 34}]},
                                {"name": "Codex", "windows": [{"used": 12}]}]}
        weather = pal.status_line(limits, phase=0)
        usage = pal.status_line(limits, phase=1)
        self.assertIn("9:41am", weather)
        self.assertIn("16c cloudy", weather)
        self.assertNotIn("claude", weather)
        self.assertIn("9:41am", usage)
        self.assertIn("claude 34%", usage)
        self.assertNotIn("cloudy", usage)
        self.assertEqual(weather, pal.status_line(limits, phase=2))

    def test_status_has_clock_placeholder_before_sync(self):
        pal, _ = load_pal()
        pal.room.local_time = lambda: None
        self.assertTrue(pal.status_line({}, phase=0).startswith("--:--"))


if __name__ == "__main__":
    unittest.main()
