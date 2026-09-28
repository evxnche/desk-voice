# Follow one flight (the family's BA36 home) from take-off to landing: its own screen with a route
# bar and the plane on it, and the Pal says when it takes off, starts coming down and lands.
# Set from the remote page (deskpal.local) or by voice ("gee gee, track BA36"). Data: desk-voice
# /api/track (adsb.lol + adsbdb). Over oceans there are no receivers, so the flight can vanish for
# hours: the screen keeps the last position it saw.
import time, json, requests, _thread, math, framebuf
from array import array
import dashboard, battery, font5, secrets, room, flights

URL = secrets.VOICE_URL.replace("/api/voice", "/api/track") + "?k=" + secrets.VOICE_KEY
MAP_URL = secrets.VOICE_URL.replace("/api/voice", "/api/trackmap") + "?k=" + secrets.VOICE_KEY
MX, MY, MW, MH = 0, 34, 248, 250   # the map, left of the details column
KM_PER_DEG = 111.32
FILE = "track.json"
ON_SCREEN_MS = 30 * 1000       # fetch this often while the screen shows
OFF_SCREEN_MS = 2 * 60 * 1000  # and this often otherwise (take-off / landing lines)
KEEP_MS = 2 * 3600 * 1000      # stop following this long after it lands

flight = ""          # what's being followed, as typed ("BA36")
last = None          # latest /api/track answer that had a position
info = None          # latest answer (route, seen or not)
seen_at = None       # local "HH:MM" it was last seen
landed = False
fetched_ms = None    # ticks_ms of `last`, for gliding the plane between fetches
mapdata = None       # (meta, FrameBuffer) from /api/trackmap
version = 0          # bumped when new data arrives, so the screen redraws
_fetch_at = 0
_busy = False
_landed_ms = None
_said = set()        # "takeoff", "descent", "landed": each said once per flight
on_news = None       # companion's hook: on_news(text)

def _save():
    with open(FILE, "w") as f:
        json.dump({"f": flight, "said": list(_said)}, f)    # a restart doesn't repeat "it's landed"

try:
    _saved = json.load(open(FILE))
    flight = _saved.get("f", "")
    _said.update(_saved.get("said", []))
except Exception:
    pass

def start(f):
    """Follow flight `f` ('' stops)."""
    global flight, last, info, seen_at, landed, _fetch_at, _landed_ms, version, mapdata
    flight = "".join(f.split()).upper()[:8]
    last = info = seen_at = _landed_ms = mapdata = None
    landed = False
    _said.clear()
    _fetch_at = 0
    version += 1
    _save()

def headers():
    """X-Track for voice questions ("how's the flight doing?")."""
    return {"X-Track": flight} if flight else {}

def _clock(lt=None, add_min=0):
    lt = lt or room.local_time()
    if not lt:
        return ""
    m = lt[3] * 60 + lt[4] + add_min
    return "%02d:%02d" % (m // 60 % 24, m % 60)

def _news(key, text):
    if key not in _said:
        _said.add(key)
        _save()
        if on_news:
            on_news(text)

def _judge(d):
    """Take-off, descent and landing from successive answers."""
    global landed, _landed_ms
    name = d.get("flight") or flight
    dest = (d.get("to") or {}).get("city") or "its destination"
    origin = (d.get("from") or {}).get("city") or ""
    if d.get("seen"):
        left, total = d.get("km_left"), d.get("km_total")
        if d.get("on_ground") and left is not None and left < 40:
            landed = True
        elif not d.get("on_ground"):
            if total and left is not None and total - left < 150 and d.get("vrate", 0) > 300:
                _news("takeoff", "%s has taken off from %s." % (name, origin or "the airport"))
            if left is not None and left < 450 and d.get("vrate", 0) < -800:
                eta = d.get("eta_min")
                _news("descent", "%s has started coming down into %s%s." % (
                    name, dest, ", landing in about %d minutes" % eta if eta else ""))
    elif last and last.get("km_left") is not None and last["km_left"] < 40 and last.get("alt_ft", 99999) < 4000:
        landed = True                        # vanished low and close to the airport: it's down
    if landed and _landed_ms is None:
        _landed_ms = time.ticks_ms()
        _news("landed", "%s has landed in %s." % (name, dest))

def _worker():
    global last, info, seen_at, version, _busy, fetched_ms
    try:
        r = requests.get(URL + "&f=" + flight, timeout=15)
        if r.status_code == 200:
            d = r.json()
            _judge(d)
            info = d
            if d.get("seen"):
                last, seen_at, fetched_ms = d, _clock(), time.ticks_ms()
            version += 1
        r.close()
        if last and _map_due():
            _fetch_map()
            version += 1
    except Exception as e:
        print("track:", e)
    _busy = False

def _zoom():
    """km per map pixel: the whole of western Europe at cruise, closer in for the landing."""
    left = (last or {}).get("km_left")
    return 2 if left is not None and left < 250 else 5

def project(meta, lat, lon):
    kx = math.cos(math.radians(meta["lat"])) * KM_PER_DEG / meta["kmpx"]
    return (MX + meta["w"] // 2 + int((lon - meta["lon"]) * kx),
            MY + meta["h"] // 2 - int((lat - meta["lat"]) * KM_PER_DEG / meta["kmpx"]))

def _map_due():
    """A new map when there's none, the zoom changed, or the plane is near its edge."""
    if mapdata is None:
        return True
    meta = mapdata[0]
    if meta["kmpx"] != _zoom():
        return True
    x, y = project(meta, last["lat"], last["lon"])
    return not (MX + 45 < x < MX + MW - 45 and MY + 45 < y < MY + MH - 45)

def _fetch_map():
    """Centred a little ahead of the plane, so it flies across the map before the next one."""
    global mapdata
    kmpx = _zoom()
    ahead = 0 if landed or last.get("on_ground") else MW * 0.3 * kmpx
    t = math.radians(last.get("track", 0))
    lat = last["lat"] + ahead * math.cos(t) / KM_PER_DEG
    lon = last["lon"] + ahead * math.sin(t) / (KM_PER_DEG * math.cos(math.radians(last["lat"])))
    q = "&lat=%.4f&lon=%.4f&kmpx=%s&w=%d&h=%d" % (lat, lon, kmpx, MW, MH)
    a, b = last.get("from") or {}, last.get("to") or {}
    if "lat" in a and "lat" in b:
        q += "&route=%.4f,%.4f,%.4f,%.4f" % (a["lat"], a["lon"], b["lat"], b["lon"])
    r = requests.get(MAP_URL + q, timeout=15)
    body = r.content
    r.close()
    if r.status_code != 200:
        return
    nl = body.find(b"\n")
    meta = json.loads(body[:nl])
    bits = bytearray(body[nl + 1:])
    mapdata = (meta, framebuf.FrameBuffer(bits, meta["w"], meta["h"], framebuf.MONO_HLSB))

def tick(connect, showing):
    """Call often: fetches in the background when due."""
    global _fetch_at, _busy
    if not flight:
        return
    if _landed_ms is not None and time.ticks_diff(time.ticks_ms(), _landed_ms) > KEEP_MS:
        start("")
        return
    now = time.ticks_ms()
    if _busy or time.ticks_diff(now, _fetch_at) < 0 or not connect():
        return
    _fetch_at = time.ticks_add(now, ON_SCREEN_MS if showing else OFF_SCREEN_MS)
    _busy = True
    try:
        _thread.stack_size(20 * 1024)
        _thread.start_new_thread(_worker, ())
    except OSError:
        _worker()                            # no stack fits: fetch here

def refresh_now():
    global _fetch_at
    _fetch_at = time.ticks_ms()

def status():
    """One line for the remote page."""
    if not flight:
        return ""
    if landed:
        return "%s landed" % flight
    if last and last.get("eta_min"):
        return "%s lands ~%s" % (flight, _clock(add_min=last["eta_min"]))
    return "%s: %s" % (flight, "in the air" if last else "not seen yet")

# A small aeroplane pointing up (north), nose at y = -9; rotated to the plane's track.
PLANE = ((0, -9), (1, -7), (1, -2), (8, 2), (8, 4), (1, 2), (1, 6), (4, 8), (4, 9), (0, 8),
         (-4, 9), (-4, 8), (-1, 6), (-1, 2), (-8, 4), (-8, 2), (-1, -2), (-1, -7))

def _plane(c, x, y, track):
    t = math.radians(track)
    ct, st = math.cos(t), math.sin(t)
    pts = array("h")
    for px, py in PLANE:
        px, py = px * 1.4, py * 1.4
        pts.append(int(px * ct - py * st))
        pts.append(int(px * st + py * ct))
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        c.poly(x + dx, y + dy, pts, 0, True)          # white edge, so it reads over the borders
    c.poly(x, y, pts, 1, True)

def where():
    """Plane position on screen now, gliding along its track since the last fetch."""
    if not (last and mapdata):
        return None
    lat, lon = last["lat"], last["lon"]
    if info and info.get("seen") and not landed and fetched_ms is not None:
        dt = min(120, time.ticks_diff(time.ticks_ms(), fetched_ms) / 1000)
        km = last.get("speed_kmh", 0) * dt / 3600
        t = math.radians(last.get("track", 0))
        lat += km * math.cos(t) / KM_PER_DEG
        lon += km * math.sin(t) / (KM_PER_DEG * math.cos(math.radians(lat)))
    return project(mapdata[0], lat, lon)

def _row(d, label, value, y):
    font5.text(d.canvas, label, 256, y + 1)
    d.text(dashboard.ascii(value)[:12], 300, y, 1)

_static = None       # everything but the plane
_shown = None        # (version, plane x, y) on screen

def enter():
    global _static, _shown
    _static = _shown = None

def frame():
    """Call often while the screen shows: redraws when data arrives, moves the plane each pixel."""
    global _static, _shown
    pos = where()
    key = (version, pos)
    if key == _shown:
        return
    d = dashboard.display()
    if _static is None or _shown is None or _shown[0] != version:
        _draw_static(d)
        _static = bytearray(d.canvas_buffer)
    else:
        d.canvas_buffer[:] = _static
    if pos and MX < pos[0] < MX + MW and MY < pos[1] < MY + MH:
        _plane(d.canvas, pos[0], pos[1], last.get("track", 0))
    d.show()
    _shown = key

def draw():
    enter()
    frame()

def _draw_static(d):
    c = d.canvas
    d.clear(0)
    head = info or last or {}
    name = head.get("flight") or flight or "no flight"
    font5.lowercase = not flight               # flight numbers and airport codes in capitals
    d.text_large(dashboard.ascii(name)[:8], 10, 8, 2)
    a, b = head.get("from") or {}, head.get("to") or {}
    route = "%s > %s" % (a.get("code") or "?", b.get("code") or "?") if a or b else ""
    font5.lowercase = True
    x = 20 + 16 * min(8, len(name))
    if head.get("airline"):
        x = font5.text(c, dashboard.ascii(head["airline"])[:20], x, 13) + 12
    if route:
        font5.lowercase = False
        font5.text(c, dashboard.ascii(route), x, 13)
        font5.lowercase = True
    battery.draw_small(d, 392, 13)
    d.line(0, 32, 400, 32, 1)

    if not flight:
        d.text_large("no flight tracked", 16, 110, 2)
        d.text("say \"gee gee, track BA36\"", 16, 150, 1)
        d.text("or use deskpal.local", 16, 166, 1)
        return

    # Map on the left
    if mapdata:
        meta, fb = mapdata
        c.blit(fb, MX, MY)
        for label, lx, ly in meta["labels"]:
            w = 6 * len(label) + 3
            c.fill_rect(MX + lx - 2, MY + ly - 2, w, 12, 0)
            font5.text(c, dashboard.ascii(label), MX + lx, MY + ly)
    else:
        d.text("map loading..." if last else "waiting for it to", 20, 140, 1)
        if not last:
            d.text("show up on radar", 20, 156, 1)
    c.vline(MX + MW + 2, 33, 253, 1)

    # Details on the right
    if landed:
        font5.text(c, "landed in", 256, 42)
        d.text_large(dashboard.ascii(b.get("city") or "")[:9], 256, 56, 2)
    elif last and last.get("eta_min"):
        m = last["eta_min"]
        big = "%d min" % m if m < 100 else "%dh%02d" % (m // 60, m % 60)
        font5.text(c, "lands in", 256, 42)
        d.text_large(big, 256, 54, 3 if len(big) * 24 <= 142 else 2)
        font5.text(c, "about %s uk time" % _clock(add_min=m), 256, 82)
    elif last:
        d.text_large("in the air" if not last.get("on_ground") else "on ground", 256, 56, 2)
    else:
        font5.text(c, "not in the air yet", 256, 42)
    y = 102
    if last:
        rows = [("over", last.get("over") or "-")]
        if not landed:
            v = last.get("vrate", 0)
            rows += [("alt", "%s ft" % flights._commas(last.get("alt_ft", 0))),
                     ("", "climbing" if v > 300 else "descending" if v < -300 else "level"),
                     ("speed", "%d km/h" % last.get("speed_kmh", 0))]
            if last.get("km_left") is not None:
                rows.append(("to go", "%s km" % flights._commas(last["km_left"])))
        rows += [("plane", last.get("type") or "-"), ("reg", last.get("reg") or "-")]
        for label, value in rows:
            font5.lowercase = label != "reg"
            _row(d, label, value, y)
            font5.lowercase = True
            y += 18
        # progress bar, origin to destination
        frac = 1.0 if landed else 0.0
        if not landed and last.get("km_total") and last.get("km_left") is not None:
            frac = max(0.0, min(1.0, 1 - last["km_left"] / last["km_total"]))
        c.rect(256, 262, 136, 8, 1)
        c.fill_rect(258, 264, int(132 * frac), 4, 1)
        font5.text(c, "%d%% of the way" % int(frac * 100), 256, 250)
    stale = info is not None and not info.get("seen") and last is not None
    foot = ("no signal since %s" % seen_at) if stale else ("updated %s" % seen_at) if last else \
           ("checked %s" % _clock()) if info else "looking..."
    c.fill_rect(0, 286, 400, 14, 1)
    d.text(dashboard.ascii(foot + "   KEY: refresh")[:50], 4, 289, 0)
