# The Pal: Claude's pixel crab. Desk Pal's home screen, and the face of the voice assistant.
# Drawn only from rectangles on a 10 x 8 grid of 18 px blocks: body cols 1-8 rows 0-5, arms cols 0
# and 9 rows 2-3, legs cols 1, 3, 6, 8 rows 6-7, square eyes cut out at cols 2 and 7 of row 2
# (the same geometry as the "Meet the Pal" mock-up page).
# Moods: idle, hears, sleep (on the Pal screen, from how loud the mic hears the room; nothing is
# recorded) and listen, think, speak, huh, alert, waiting (drawn by voice.py while it works).
import time, math
import dashboard, room, audio

U = 18
X0 = 200 - 5 * U
Y0 = 66

CAPTIONS = True          # the answer's words under the Pal while it speaks
QUIET_FROM, QUIET_TO = 22, 8    # asleep (and no speaking up) from 22:00 to 08:00, local time

def _eye(c, ex, ey, e):
    shape = e[0]
    if shape == "closed":
        c.fill_rect(ex - 9, ey + 2, 18, 4, 0)
        return
    scale, opened, gx, gy = e[1], e[2], e[3], e[4]
    w = int(U * scale + 0.5)
    h = max(3, int(U * scale * opened + 0.5))
    c.fill_rect(ex - w // 2 + gx, ey - h // 2 + gy, w, h, 0)

OPEN = ("open", 1.0, 1.0, 0, 0)
WIDE = ("open", 1.2, 1.0, 0, 0)
CLOSED = ("closed",)
HUH_L, HUH_R = ("open", 1.0, 1.0, -3, -3), ("open", 1.0, 0.35, -3, -3)

def crab(c, bob=0, la=0.0, ra=0.0, sit=False, step=None, left=OPEN, right=OPEN, mouth=None, opened=0.0):
    """Draw the crab; la/ra lift an arm by that many blocks (2 = up by its head). Returns (x0, y0)."""
    x0, y0 = X0, Y0 + bob + (U if sit else 0)
    c.fill_rect(x0 + U, y0, 8 * U, 6 * U, 1)
    c.fill_rect(x0, y0 + 2 * U - int(la * U), U, 2 * U, 1)
    c.fill_rect(x0 + 9 * U, y0 + 2 * U - int(ra * U), U, 2 * U, 1)
    for i, col in enumerate((1, 3, 6, 8)):
        short = U + 6 if sit else (5 if step is not None and i % 2 == step else 0)
        c.fill_rect(x0 + col * U, y0 + 6 * U, U, 2 * U - short, 1)
    _eye(c, x0 + 45, y0 + 45, left)
    _eye(c, x0 + 135, y0 + 45, right)
    _mouth(c, x0 + 5 * U, y0 + 81, mouth, opened)
    return x0, y0

def _mouth(c, mx, my, mouth, opened=0.0):
    if mouth == "talk":
        h = 3 + int(15 * opened)
        c.fill_rect(mx - 14, my - h // 2, 28, h, 0)
    elif mouth == "o":
        c.fill_rect(mx - 6, my - 6, 12, 12, 0)
    elif mouth == "flat":
        c.fill_rect(mx - 12, my - 2, 24, 4, 0)
    elif mouth == "wavy":
        for k in range(6):
            c.fill_rect(mx - 18 + k * 6, my + (1 if k % 2 else -3), 6, 4, 0)

def _wave(c, y0, side, i):
    """A pixel ")" (side 1, right of the crab) or "(" (side -1): three steps of 3 px bars."""
    h = 24 + i * 14
    top, q = y0 + 3 * U - h // 2, h // 4
    x = X0 + 10 * U + 10 + i * 12 if side > 0 else X0 - 13 - i * 12
    c.fill_rect(x, top, 3, q, 1)
    c.fill_rect(x + 3 * side, top + q, 3, h - 2 * q, 1)
    c.fill_rect(x, top + h - q, 3, q, 1)

def _centred(d, s, y):
    s = dashboard.ascii(s)[:50]
    d.text(s, 200 - 4 * len(s), y, 1)

def wrap(text, width=23):
    lines, line = [], ""
    for word in dashboard.ascii(text).split():
        if len(word) > width:
            if line:
                lines.append(line)
                line = ""
            while len(word) > width:
                lines.append(word[:width])
                word = word[width:]
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines

def draw(mood, level=0.0, caption=(), status="", bars=None, t=None, hint=""):
    """One frame of a voice/alert mood. `level` 0-1 is your voice (listen) or its own (speak);
    `caption` is a list of lines under the crab; `bars` a list of recent levels (listen)."""
    t = time.ticks_ms() / 1000 if t is None else t
    d = dashboard.display()
    c = d.canvas
    c.fill(0)
    if mood == "listen":
        x0, y0 = crab(c, bob=-int(level * 3), la=2.5, ra=2.5, left=WIDE, right=WIDE, mouth="o")
        for i in range(3):
            if level > i * 0.28:
                _wave(c, y0, 1, i)
                _wave(c, y0, -1, i)
        for i, lv in enumerate((bars or [])[-25:]):
            h = 2 + int(22 * lv * (1 - abs(i - 12) / 16))
            c.fill_rect(128 + i * 6, 290 - h, 4, h, 1)
    elif mood == "think":
        e = ("open", 1.0, 0.8, 5, -5)
        x0, y0 = crab(c, bob=2 * round(math.sin(t * 2.2)), ra=2.5, left=e, right=e, mouth="flat")
        k = int(t * 3) % 4
        right = X0 + 10 * U
        for i, (x, y, r) in enumerate(((right + 4, y0 - 4, 6), (right + 16, y0 - 20, 9), (right + 32, y0 - 42, 12))):
            if i < k:
                c.fill_rect(x, y, r, r, 1)
    elif mood in ("speak", "huh"):
        huh = mood == "huh"
        # No bob or blink here: speak_update() redraws only the mouth while the voice plays.
        x0, y0 = crab(c, la=1 if huh else 0.3, ra=1 if huh else 0.3,
                      left=HUH_L if huh else OPEN, right=HUH_R if huh else OPEN,
                      mouth="wavy" if huh and level < 0.15 else "talk", opened=level)
        if huh:
            d.text_large("?", X0 + 10 * U + 10, y0 - 50 + int(math.sin(t * 3) * 3), 5)
    elif mood == "alert":
        hop = abs(math.sin(t * 6))
        flip = int(t * 4) % 2
        x0, y0 = crab(c, bob=-int(hop * 10), la=2.5 if flip else 1, ra=1 if flip else 2.5, left=WIDE, right=WIDE,
                      mouth="talk", opened=level)
        d.text_large("!", X0 + 10 * U + 10, y0 - 50, 5)
    elif mood == "waiting":
        # After an answer: still listening for a reply, no "gee gee" needed
        e = ("open", 1.1, 1.0, 0, 2)
        x0, y0 = crab(c, la=1, ra=1, left=e, right=e)
        _reply_cue(d, level)
    y = 218
    for line in caption[:3]:
        line = dashboard.ascii(line)[:23]
        d.text_large(line, 200 - 8 * len(line), y, 2)
        y += 20
    if status:
        c.hline(0, 266, 400, 1)
        _centred(d, status, 274)
    if hint:
        _centred(d, hint, 288)
    d.show()

def speak_update(level, huh=False):
    """Speaking frame on top of the last draw("speak"/"huh"): only the mouth changes, ~40 ms, so it
    keeps up with the voice (a full frame with captions takes ~85 ms)."""
    d = dashboard.display()
    c = d.canvas
    mx, my = X0 + 5 * U, Y0 + 81
    c.fill_rect(mx - 20, my - 12, 40, 24, 1)
    _mouth(c, mx, my, "wavy" if huh and level < 0.15 else "talk", level)
    d.show()

def _reply_cue(d, left):
    c = d.canvas
    c.fill_rect(0, 272, 400, 28, 0)
    c.hline(0, 272, 400, 1)
    d.text_large("SAY YOUR REPLY", 88, 274, 2)
    c.fill_rect(50, 296, 300, 3, 0)
    if left > 0:
        c.fill_rect(50, 296, int(300 * min(1, left)), 3, 1)

def reply_strip(left):
    """Temporary follow-up cue over a utility screen; its next normal redraw restores the footer."""
    d = dashboard.display()
    _reply_cue(d, left)
    d.show()

def caption_page(lines, done_fraction, per_page=3):
    """The page of caption lines that goes with how much of the answer has played."""
    if len(lines) <= per_page:
        return lines
    pages = (len(lines) + per_page - 1) // per_page
    p = min(pages - 1, int(done_fraction * pages))
    return lines[p * per_page:(p + 1) * per_page]


# ---- The Pal screen (ambient) ----

LOUD = 30          # audio.level_now() that counts as talking nearby (quiet room 6-18, Mac speech 40-240)
AWAKE_MS = 60000   # during quiet hours, stays awake this long after it last heard you

def quiet_hours(lt=None):
    lt = lt or room.local_time()
    return bool(lt) and (lt[3] >= QUIET_FROM or lt[3] < QUIET_TO)

class Ambient:
    """Samples the room's loudness (the wake-phrase listener's level, nothing recorded) and draws the
    Pal screen: idle, perking up when it hears talking, asleep in quiet hours."""
    def __init__(self):
        self.heard_at = None     # ticks_ms when it last heard talking
        self.loud = 0            # consecutive loud samples
        self.level = 0.0
        self.next_sample = 0
        self.shown = None
        self.on_hear = None      # called once each time talking starts (companion.py's morning hello)

    def sense(self):
        """Call often, on any screen: 10 samples a second."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.next_sample) < 0:
            return
        self.next_sample = time.ticks_add(now, 100)
        lvl = audio.level_now()
        if lvl is None:
            return
        self.level = min(1.0, lvl / 120)
        self.loud = self.loud + 1 if lvl >= LOUD else 0
        if self.loud >= 3:                       # ~0.3 s of sound: talking, not a click
            first = self.heard_at is None or time.ticks_diff(now, self.heard_at) > 5000
            self.heard_at = now
            if first and self.on_hear:
                self.on_hear()

    def hearing(self, ms=1500):
        return self.heard_at is not None and time.ticks_diff(time.ticks_ms(), self.heard_at) < ms

    def enter(self):
        self.shown = None

    def tick(self, status):
        """Redraw the Pal screen if anything visible changed (idle moves come in whole steps)."""
        t = time.ticks_ms() / 1000
        lt = room.local_time()
        if self.hearing():
            lv = self.level
            key = ("hears", sum(1 for i in range(3) if lv > i * 0.3), status)
        elif quiet_hours(lt) and not self.hearing(AWAKE_MS):
            key = ("sleep", int(t * 4), lt and lt[4])
        else:
            blink = (t % 3.7) < 0.14
            key = ("idle", blink, 3 * round(math.sin(t * 0.7) * 2), 3 * round(math.sin(t * 0.43)),
                   2 * round(math.sin(t * 1.6)), int(t * 1.6) % 2, status)
        if key == self.shown:
            return
        self.shown = key
        d = dashboard.display()
        c = d.canvas
        c.fill(0)
        if key[0] == "hears":
            x0, y0 = crab(c, bob=-2, ra=1, left=("open", 1.2, 1.0, 0, 2), right=("open", 1.2, 1.0, 0, 2))
            for i in range(key[1]):
                _wave(c, y0, 1, i)
        elif key[0] == "sleep":
            x0, y0 = crab(c, bob=round(math.sin(t * 0.9) * 1.5), sit=True, left=CLOSED, right=CLOSED)
            for i in range(3):
                f = (t * 0.35 + i / 3) % 1
                d.text_large("Z" if i == 1 else "z", X0 + 10 * U + 6 + int(f * 40), y0 - 4 - int(f * 56) - 16, 2 + i)
            if lt:
                _centred(d, "%02d:%02d" % (lt[3], lt[4]), 274)
            d.show()
            return
        else:
            _, blink, gx, gy, bob, step, _ = key
            e = ("open", 1.0, 0.15 if blink else 1.0, gx, gy)
            crab(c, bob=bob, step=step, left=e, right=e)
        c.hline(0, 266, 400, 1)
        _centred(d, status, 274)
        d.show()

ambient = Ambient()

def status_line(limits, phase=None):
    """Time plus alternating weather/agent usage; phase is injectable for host tests."""
    parts = []
    lt = room.local_time()
    parts.append("%02d:%02d" % (lt[3], lt[4]) if lt else "--:--")
    if phase is None:
        phase = int(time.ticks_ms() / 6000)
    if phase % 2 == 0:
        w = room.weather
        if w:
            parts.append("%dc %s" % (w["temp_c"], w["condition"].lower()))
    else:
        for p in (limits or {}).get("providers", [])[:2]:
            wins = p.get("windows") or []
            if wins:
                parts.append("%s %d%%" % (p.get("name", "?").lower(), int(wins[0].get("used", 0))))
    return "  ".join(parts)[:50]
