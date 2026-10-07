# Today screen: an animation of the weather (sun, clouds, rain, snow, fog, storm, a moon at night) with
# the details beside it and today's + tomorrow's forecast below; date and time small in the header.
# Local time (TZ) from NTP, weather from desk-voice /api/weather (Open-Meteo).
import time, requests, _thread, math
from array import array
import dashboard, font5, secrets, home, palicon

WEATHER_URL = secrets.VOICE_URL.replace("/api/voice", "/api/weather") + "?k=" + secrets.VOICE_KEY
WEATHER_MS = 10 * 60 * 1000

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

weather = None
weather_is_home = True                        # False while another place's weather is shown
_weather_at = None
version = 0                                     # bumped when new weather arrives, so the screen redraws

def weather_due():
    return _weather_at is None or time.ticks_diff(time.ticks_ms(), _weather_at) >= WEATHER_MS

def set_weather(w, is_home=True):
    """Weather the voice assistant just looked up, shown while it speaks. Somewhere else's weather
    is swapped back for home's a minute later."""
    global weather, _weather_at, version, weather_is_home
    weather, weather_is_home = w, is_home
    version += 1
    _weather_at = time.ticks_add(time.ticks_ms(), 0 if is_home else 60000 - WEATHER_MS)

def fetch_weather():
    global weather, _weather_at, version, weather_is_home
    _weather_at = time.ticks_ms()               # also paces retries after a failure
    try:
        r = requests.get(WEATHER_URL + home.query(), timeout=15)
        if r.status_code == 200:
            weather, weather_is_home = r.json(), True
            version += 1
        r.close()
    except Exception:
        pass

def fetch_weather_soon():
    """fetch_weather() in the background: on this thread it held up the screen and buttons ~1.3 s."""
    global _weather_at
    _weather_at = time.ticks_ms()               # not due again while this one runs
    try:
        _thread.stack_size(20 * 1024)
        _thread.start_new_thread(fetch_weather, ())
    except OSError:
        fetch_weather()                         # no stack free: fetch here instead

# The owner's time zone; must match the server's (desk-voice lib/calendar.js TZ).
# "India": IST, UTC+5:30 all year. "UK": GMT, and BST in summer.
TZ = "India"

def _offset(t):
    """Seconds ahead of UTC at UTC time t. UK: BST (+1h) from 01:00 UTC on the last Sunday of March
    to the last Sunday of October."""
    if TZ == "India":
        return 19800
    y = time.localtime(t)[0]
    def last_sunday(month):
        ts = time.mktime((y, month, 31, 1, 0, 0, 0, 0))
        return ts - ((time.localtime(ts)[6] + 1) % 7) * 86400
    return 3600 if last_sunday(3) <= t < last_sunday(10) else 0

def clock(h, m):
    """12-hour time, as everywhere on the board: 9:05am, 12:30pm."""
    h %= 24
    return "%d:%02d%s" % ((h - 1) % 12 + 1, m, "am" if h < 12 else "pm")

def local_time():
    t = time.time()
    if time.localtime(t)[0] < 2025:              # clock never synced
        return None
    return time.localtime(t + _offset(t))

def _degrees(c, x, y, r):
    c.ellipse(x + r, y + r, r, r, 1)

# ---- The animation (left half, above the forecast) ----

AX, AY, AW, AH = 0, 26, 206, 170     # its box
CX, CY = AX + AW // 2, AY + AH // 2
FRAME_MS = 150

def kind(condition, is_day=True):
    """The animation for an Open-Meteo condition name (lib/weather.js)."""
    s = condition.lower()
    if "thunder" in s:
        return "storm"
    if "snow" in s:
        return "snow"
    if "rain" in s or "shower" in s or "drizzle" in s:
        return "heavy rain" if "heavy" in s or "violent" in s else "rain"
    if "fog" in s:
        return "fog"
    if s == "cloudy":
        return "cloudy"
    if "partly" in s or "mostly" in s:
        return "partly" if is_day else "partly night"
    return "sun" if is_day else "moon"

def _cloud(c, x, y, k=1.0):
    """White cloud with a black outline, centred on (x, y)."""
    bumps = ((-22, 4, 15), (0, -8, 21), (22, 2, 16))
    w, top = int(40 * k), int(4 * k)
    for col, grow in ((1, 2), (0, 0)):
        for bx, by, r in bumps:
            rr = int(r * k) + grow
            c.ellipse(x + int(bx * k), y + int(by * k), rr, rr, col, True)
        c.fill_rect(x - w - grow, y + top - grow, 2 * w + 2 * grow, int(15 * k) + 2 * grow, col)

def _sun(c, x, y, r, t):
    c.ellipse(x, y, r, r, 1, True)
    a0 = t * 0.4
    for i in range(12):
        a = a0 + i * math.pi / 6
        ca, sa = math.cos(a), math.sin(a)
        r1, r2 = r + 8, r + 8 + (14 if i % 2 else 9)
        for d in (-1, 0, 1):
            c.line(x + int(ca * r1 - sa * d), y + int(sa * r1 + ca * d), x + int(ca * r2 - sa * d), y + int(sa * r2 + ca * d), 1)

def _moon(c, x, y, r, t):
    c.ellipse(x, y, r, r, 1, True)
    c.ellipse(x + r // 2, y - r // 3, r, r, 0, True)
    for i, (sx, sy) in enumerate(((-58, -40), (52, -48), (60, 30), (-64, 38), (20, 58), (-20, -62))):
        if (int(t * 2) + i) % 3:
            n = 3 if i % 2 else 2
            c.hline(x + sx - n, y + sy, 2 * n + 1, 1)
            c.vline(x + sx, y + sy - n, 2 * n + 1, 1)

def _drops(c, x, y, t, n, speed):
    for i in range(n):
        dx = x - 44 + (i * 37) % 88
        dy = y + int(t * speed + i * 23) % 66
        c.line(dx, dy, dx - 3, dy + 8, 1)
        c.line(dx + 1, dy, dx - 2, dy + 8, 1)

def _flakes(c, x, y, t, n):
    for i in range(n):
        fx = x - 46 + (i * 29) % 92 + int(math.sin(t * 1.5 + i) * 4)
        fy = y + int(t * 14 + i * 17) % 70
        c.hline(fx - 2, fy, 5, 1)
        c.vline(fx, fy - 2, 5, 1)
        c.pixel(fx - 2, fy - 2, 1); c.pixel(fx + 2, fy + 2, 1); c.pixel(fx + 2, fy - 2, 1); c.pixel(fx - 2, fy + 2, 1)

BOLT = array("h", (4, 0, -10, 22, 0, 22, -6, 42, 14, 14, 3, 14, 10, 0))

def animate(c, k, t):
    """Draw one frame of animation `k` at time t (seconds) into the box (already white)."""
    drift = int(math.sin(t * 0.6) * 8)
    if k == "sun":
        _sun(c, CX, CY, 30, t)
    elif k == "moon":
        _moon(c, CX, CY, 32, t)
    elif k in ("partly", "partly night"):
        if k == "partly":
            _sun(c, CX - 22, CY - 22, 22, t)
        else:
            _moon(c, CX - 22, CY - 22, 24, t)
        _cloud(c, CX + 18 + drift, CY + 22)
    elif k == "cloudy":
        _cloud(c, CX - 22 + drift, CY - 18, 1.1)
        _cloud(c, CX + 26 - drift, CY + 26, 0.9)
    elif k == "fog":
        for row in range(6):
            y = CY - 50 + row * 20
            off = int(t * (10 if row % 2 else -10)) % 30
            for x in range(AX - 30 + off, AX + AW, 30):
                c.fill_rect(max(AX + 10, x), y, max(0, min(20, AX + AW - 10 - max(AX + 10, x))), 3, 1)
    elif k in ("rain", "heavy rain", "storm"):
        heavy = k != "rain"
        _drops(c, CX + drift // 2, CY + 14, t, 14 if heavy else 8, 70 if heavy else 50)
        if k == "storm" and (t % 2.6) < 0.35:
            c.poly(CX + 6, CY + 12, BOLT, 1, True)
        _cloud(c, CX + drift // 2, CY - 18, 1.15)
    elif k == "snow":
        _flakes(c, CX, CY + 12, t, 12)
        _cloud(c, CX + drift // 2, CY - 18, 1.15)

# ---- The screen ----

_static = None      # everything but the animation
_shown = None       # (minute, weather version) the static part shows
_next_frame = 0

def enter():
    global _static, _shown
    _static = _shown = None

def _row(d, label, value, y):
    font5.text(d.canvas, label, 216, y + 1)
    d.text(dashboard.ascii(value)[:12], 290, y, 1)

def _draw_static(d, lt):
    c = d.canvas
    d.clear(0)
    dashboard.header(d, "weather")
    w = weather
    if not w:
        d.text_large("weather loading...", 16, 130, 2)
        return
    place = dashboard.ascii(w.get("place", "") or "here")
    d.text(place[:22], 216, 34, 1)
    temp = "%d" % w["temp_c"]
    d.text_large(temp, 214, 56, 5)
    x = 214 + 40 * len(temp)
    _degrees(c, x + 2, 57, 4)
    d.text_large("c", x + 14, 57, 2)
    d.text(dashboard.ascii(w["condition"])[:22], 216, 110, 1)   # "partly cloudy", "thunderstorm, hail"
    _row(d, "feels", "%dc" % w["feels_c"], 134)
    _row(d, "humidity", "%d%%" % w["humidity"], 152)
    _row(d, "wind", "%d km/h" % w["wind_kmh"], 170)
    c.hline(10, 200, 380, 1)
    for i, (name, day) in enumerate((("today", w["today"]), ("tomorrow", w["tomorrow"]))):
        y = 214 + 40 * i
        d.text(name, 12, y + 2, 1)
        font5.text(c, dashboard.ascii(day["condition"])[:20], 110, y + 3)
        d.text("%d-%dc" % (day["low_c"], day["high_c"]), 290, y + 2, 1)
        font5.text(c, "rain %d%%" % day["rain_chance"], 110, y + 17)
    palicon.draw(c, 366, 212, "today")

def frame():
    """Call often while the screen shows: redraws the rest each minute / new weather, animates ~7 fps."""
    global _static, _shown, _next_frame
    now = time.ticks_ms()
    lt = local_time()
    key = (lt[4] if lt else -1, version)
    d = dashboard.display()
    if key != _shown or _static is None:
        _draw_static(d, lt)
        _static = bytearray(d.canvas_buffer)
        _shown = key
        _next_frame = now
    if time.ticks_diff(now, _next_frame) < 0:
        return
    _next_frame = time.ticks_add(now, FRAME_MS)
    d.canvas_buffer[:] = _static
    if weather:
        animate(d.canvas, kind(weather["condition"], weather.get("is_day", True)), now / 1000)
    d.show()

def draw():
    enter()
    frame()
