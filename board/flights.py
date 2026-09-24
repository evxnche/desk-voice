# Radar screen: aircraft near home (desk-voice /api/flights). The nearest few are numbered on
# the radar and described in plain English in the list on the right. Between fetches each plane
# glides along its track at its ground speed; fetches run in a background thread.
import math, requests, time, _thread
from array import array
import dashboard, secrets

URL = secrets.VOICE_URL.replace("/api/voice", "/api/flights") + "?k=" + secrets.VOICE_KEY
if hasattr(secrets, "HOME_LAT"):
    URL += "&lat=%s&lon=%s" % (secrets.HOME_LAT, secrets.HOME_LON)

CX, CY, R = 106, 164, 100       # radar centre and radius in pixels
LIST_X = 216

FETCH_MS = 15000
FRAME_MS = 1000         # a 400 kt jet moves ~0.4 px/s at this scale, so 1 fps looks continuous

last = None             # latest data; planes carry e/n (nm east/north of home) and ve/vn (nm/s)
_fetched_at = 0
_static = None          # canvas snapshot of everything except the planes
_incoming = None        # (data, footer) handed over by the fetch thread
_busy = False
_next_fetch = 0
_next_frame = 0
_footer = ""

def _worker():
    global _incoming, _busy
    try:
        r = requests.get(URL, timeout=15)
        if r.status_code == 200:
            _incoming = (r.json(), "")
        else:
            _incoming = (None, "flight data error %d" % r.status_code)
        r.close()
    except Exception as e:
        _incoming = (None, "flight fetch failed: %s" % e)
    _busy = False

def _start_fetch(connect):
    global _busy, _incoming
    if _busy:
        return
    if not connect():
        _incoming = (None, "no Wi-Fi")
        return
    _busy = True
    _thread.stack_size(32 * 1024)          # TLS needs more than the default stack
    _thread.start_new_thread(_worker, ())

def _adopt(data):
    for a in data["aircraft"]:
        b, t = math.radians(a["bearing"]), math.radians(a["track"])
        v = a.get("speed", 0) / 3600       # knots -> nm per second
        a["e"], a["n"] = a["dist"] * math.sin(b), a["dist"] * math.cos(b)
        a["ve"], a["vn"] = v * math.sin(t), v * math.cos(t)

def enter():
    """Called when the screen is shown: draw what we have and fetch now."""
    global _next_fetch, _next_frame
    _next_fetch = _next_frame = time.ticks_ms()

def refresh_now():
    global _next_fetch
    _next_fetch = time.ticks_ms()

def tick(connect):
    """Call often while the screen is showing."""
    global last, _fetched_at, _incoming, _footer, _next_fetch, _next_frame, _static
    now = time.ticks_ms()
    if time.ticks_diff(now, _next_fetch) >= 0:
        _start_fetch(connect)
        _next_fetch = time.ticks_add(now, FETCH_MS)
    if _incoming is not None:
        data, _footer = _incoming
        _incoming = None
        if data:
            _adopt(data)
            last, _fetched_at = data, now
        _static = None
        _next_frame = now
    if time.ticks_diff(now, _next_frame) >= 0:
        if _static is None:
            _draw_static()
        _draw_planes()
        _next_frame = time.ticks_add(now, FRAME_MS)

def _commas(n):
    s = str(abs(int(n)))
    out = ""
    while len(s) > 3:
        out = "," + s[-3:] + out
        s = s[:-3]
    return ("-" if n < 0 else "") + s + out

def _plane(c, x, y, track, size, filled):
    """Arrowhead pointing along `track` (degrees)."""
    t = math.radians(track)
    pts = []
    for ang, rad in ((0, size), (140, size * 0.8), (180, size * 0.3), (220, size * 0.8)):
        a = t + math.radians(ang)
        pts += (int(rad * math.sin(a)), -int(rad * math.cos(a)))
    c.poly(x, y, array("h", pts), 1, filled)

def _arrow(c, x, y, up):
    """Tiny climbing/descending triangle, 7 px wide."""
    for i in range(4):
        row = y + (i if not up else 3 - i)
        c.hline(x + i, row + 1, 7 - 2 * i, 1)

def _draw_static():
    global _static
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    d.text_large("FLIGHTS", 10, 8, 2)
    if last:
        n = len(last["aircraft"])
        label = dashboard.ascii("%d plane%s near %s" % (n, "" if n == 1 else "s", last.get("place", "") or "you"))[:30]
        c.text(label, 392 - 8 * len(label), 13, 1)
    d.line(0, 32, 400, 32, 1)

    for rr in (R, R // 2):
        c.ellipse(CX, CY, rr, rr, 1)
    c.text("N", CX - 3, CY - R - 10, 1)
    c.hline(CX - 4, CY, 9, 1)
    c.vline(CX, CY - 4, 9, 1)
    c.text("you", CX - 11, CY + 7, 1)
    if last:
        miles = last.get("miles", 30)
        c.text("%dmi" % miles, CX - R + 2, CY + R - 30, 1)
        c.text("%dmi" % (miles // 2), CX - R // 2 + 4, CY + R // 2 - 22, 1)

        c.vline(LIST_X - 6, 38, 246, 1)
        y = 38
        for i, a in enumerate(last["aircraft"]):
            if "who" not in a:
                break
            d.text_large(str(i + 1), LIST_X, y + 6, 2)
            tx = LIST_X + 20
            c.text(dashboard.ascii(a["who"])[:20], tx, y, 1)
            c.text(dashboard.ascii(a["where"])[:20], tx, y + 10, 1)
            info = "%sft %dmi %s" % (_commas(a["alt"]), a["miles"], a["dir"]) if a["alt"] >= 100 else "low %dmi %s" % (a["miles"], a["dir"])
            c.text(info, tx, y + 20, 1)
            if a.get("trend"):
                _arrow(c, tx + 8 * len(info) + 4, y + 20, a["trend"] == "up")
            if y > 38:
                c.hline(LIST_X, y - 4, 400 - LIST_X - 4, 1)
            y += 41
        if not last["aircraft"]:
            c.text("no aircraft nearby", LIST_X, 44, 1)
    else:
        d.text_large("loading...", CX - 76, CY - 8, 2)

    c.fill_rect(0, 286, 400, 14, 1)
    c.text(dashboard.ascii(_footer)[:50] if _footer else "BOOT: next screen   KEY: refresh / hold to talk", 4, 289, 0)
    _static = bytearray(d.canvas_buffer)

def _draw_planes():
    d = dashboard.display()
    c = d.canvas
    d.canvas_buffer[:] = _static
    if last:
        scale = R / last.get("radius", 26)
        dt = min(60, time.ticks_diff(time.ticks_ms(), _fetched_at) / 1000)
        numbered = []
        for i, a in enumerate(last["aircraft"]):
            px = CX + int((a["e"] + a["ve"] * dt) * scale)
            py = CY - int((a["n"] + a["vn"] * dt) * scale)
            if px > LIST_X - 12:               # glided off the radar into the list
                continue
            if "who" in a:
                numbered.append((i + 1, px, py))
                _plane(c, px, py, a["track"], 8, True)
            else:
                _plane(c, px, py, a["track"], 6, False)
        for n, px, py in numbered:             # numbers last so planes never cover them
            c.fill_rect(px + 5, py - 12, 10, 11, 0)
            c.text(str(n), px + 6, py - 10, 1)
    d.show()
