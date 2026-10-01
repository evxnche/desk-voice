# Radar screen: aircraft near home (desk-voice /api/flights). The nearest few are numbered on
# the radar and described in plain English in the list on the right. Between fetches each plane
# glides along its track at its ground speed; fetches run in a background thread.
import math, requests, time, _thread, json
from array import array
import dashboard, secrets, font5, home, palicon

URL = secrets.VOICE_URL.replace("/api/voice", "/api/flights") + "?k=" + secrets.VOICE_KEY
VIEW_FILE = "radar.json"

def _quote(s):
    return "".join(c if c.isalpha() or c.isdigit() or c in "-_." else "%%%02X" % ord(c) for c in s)

# Where the radar looks: {"r": nm} follows the board's own location (IP-based);
# adding lat/lon/place pins it somewhere else. Set by voice ("show flights near London").
try:
    view = json.load(open(VIEW_FILE))
except Exception:
    view = {}                   # follow the board's own location at the default 50 km range

def params():
    """Query-string suffix describing the current view (shared with the voice request)."""
    q = "&r=%s" % view["r"] if "r" in view else ""
    if "lat" in view:
        q += "&lat=%s&lon=%s&place=%s" % (view["lat"], view["lon"], _quote(view.get("place", "")))
    return q

def set_view(radar):
    """Apply a voice command: {"home": true, "r": nm} or {"lat", "lon", "place", "r"}."""
    global view, last, _static, _next_fetch
    view = {"r": radar["r"]} if radar.get("home") else {
        "lat": radar["lat"], "lon": radar["lon"], "place": radar.get("place", ""), "r": radar["r"]}
    with open(VIEW_FILE, "w") as f:
        json.dump(view, f)
    last, _static = None, None            # old planes are in the wrong place/scale now
    _next_fetch = time.ticks_ms()

CX, CY, R = 98, 164, 94         # radar centre and radius in pixels
LIST_X = 202                    # table: 7 planes, 3 lines each, in the small font
ROWS = 7

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
        r = requests.get(URL + params() + home.query(), timeout=15)
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
    try:
        _thread.stack_size(20 * 1024)      # plenty for TLS; bigger stacks didn't fit beside Bluetooth
        _thread.start_new_thread(_worker, ())
    except OSError:
        _worker()                          # no stack fits with Bluetooth on: fetch here (~0.5 s pause)

def _adopt(data):
    for a in data["aircraft"]:
        b, t = math.radians(a["bearing"]), math.radians(a["track"])
        v = a.get("speed", 0) / 3600       # knots -> nm per second
        a["e"], a["n"] = a["dist"] * math.sin(b), a["dist"] * math.cos(b)
        a["ve"], a["vn"] = v * math.sin(t), v * math.cos(t)

def enter():
    """Called when the screen is shown: draw what we have, then fetch."""
    global _next_fetch, _next_frame
    _next_frame = time.ticks_ms()
    _next_fetch = time.ticks_add(_next_frame, 100)  # draw first, so switching here shows at once

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
    font5.lowercase = False              # the radar keeps its capitals (flight numbers, types)
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    label = ""
    if last:
        n = len(last["aircraft"])
        label = "%d plane%s" % (n, "" if n == 1 else "s")
        near = "%s near %s" % (label, last.get("place", "") or "you")
        label = near if len(near) <= 14 else label
    dashboard.header(d, "flights", label)

    for rr in (R, R // 2):
        c.ellipse(CX, CY, rr, rr, 1)
    font5.text(c, "N", CX - 2, CY - R - 10)
    c.hline(CX - 4, CY, 9, 1)
    c.vline(CX, CY - 4, 9, 1)
    if last:
        km = last.get("km", 50)
        font5.text(c, "%dkm" % km, CX - R + 4, CY + R - 26)
        font5.text(c, "%dkm" % (km // 2), CX - R // 2 + 6, CY + R // 2 - 20)

        # table: three lines per plane
        #   1  EZY93ZW A320    25,450  9 SW ^     (DIR = which way it's flying)
        #      easyJet                            (airline, else the operator)
        #      London > Gran Canaria              (from > to, when known)
        c.vline(LIST_X - 5, 36, 248, 1)
        x = LIST_X
        font5.text(c, "%-2s %-7s %-7s %6s %2s" % ("#", "FLIGHT", "TYPE", "ALT FT", "KM") + " DIR", x, 37)
        c.hline(x, 46, 400 - x - 2, 1)
        y = 50
        for i, a in enumerate(last["aircraft"][:ROWS]):
            if "who" not in a:
                break
            alt = _commas(a["alt"]) if a["alt"] >= 100 else "low"
            font5.text(c, "%-2d %-7s %-7s %6s %2d %s" % (
                i + 1, dashboard.ascii(a["flight"])[:7], dashboard.ascii(a["type"])[:7], alt, a["km"], a.get("heading", a["dir"])), x, y)
            if a.get("trend"):
                _arrow(c, 393, y, a["trend"] == "up")
            route = "%s > %s" % (a["from"], a["to"]) if a.get("from") else "route unknown"
            font5.text(c, "   " + dashboard.ascii(a["who"])[:30], x, y + 10)
            font5.text(c, "   " + dashboard.ascii(route)[:30], x, y + 20)
            y += 33
        if not last["aircraft"]:
            font5.text(c, "no aircraft nearby", x, 52)
    else:
        d.text_large("loading...", CX - 76, CY - 8, 2)

    palicon.draw(c, 10, 258, "flights")

    c.fill_rect(0, 286, 400, 14, 1)
    d.text(dashboard.ascii(_footer)[:50] if _footer else "BOOT: next screen   KEY: refresh / hold to talk", 4, 289, 0)
    _static = bytearray(d.canvas_buffer)
    font5.lowercase = True

def _draw_planes():
    font5.lowercase = False
    d = dashboard.display()
    c = d.canvas
    d.canvas_buffer[:] = _static
    if last:
        scale = R / last["radius"]
        dt = min(60, time.ticks_diff(time.ticks_ms(), _fetched_at) / 1000)
        numbered = []
        for i, a in enumerate(last["aircraft"]):
            px = CX + int((a["e"] + a["ve"] * dt) * scale)
            py = CY - int((a["n"] + a["vn"] * dt) * scale)
            if px > LIST_X - 12:               # glided off the radar into the list
                continue
            if "who" in a and i < ROWS:        # numbered = listed in the table
                numbered.append((i + 1, px, py))
                _plane(c, px, py, a["track"], 8, True)
            else:
                _plane(c, px, py, a["track"], 6, False)
        for n, px, py in numbered:             # numbers last so planes never cover them
            w = 6 * len(str(n))
            c.fill_rect(px + 5, py - 11, w + 2, 10, 0)
            font5.text(c, str(n), px + 6, py - 10)
    d.show()
    font5.lowercase = True
