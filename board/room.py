# Today screen: UK local time (from NTP) + outside weather (desk-voice /api/weather -> Open-Meteo).
import time, requests, _thread
import dashboard, battery, font5, secrets, home

WEATHER_URL = secrets.VOICE_URL.replace("/api/voice", "/api/weather") + "?k=" + secrets.VOICE_KEY
WEATHER_MS = 10 * 60 * 1000

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

weather = None
_weather_at = None
version = 0                                     # bumped when new weather arrives, so the screen redraws

def weather_due():
    return _weather_at is None or time.ticks_diff(time.ticks_ms(), _weather_at) >= WEATHER_MS

def set_weather(w, is_home=True):
    """Weather the voice assistant just looked up, shown while it speaks. Somewhere else's weather
    is swapped back for home's a minute later."""
    global weather, _weather_at, version
    weather = w
    version += 1
    _weather_at = time.ticks_add(time.ticks_ms(), 0 if is_home else 60000 - WEATHER_MS)

def fetch_weather():
    global weather, _weather_at, version
    _weather_at = time.ticks_ms()               # also paces retries after a failure
    try:
        r = requests.get(WEATHER_URL + home.query(), timeout=15)
        if r.status_code == 200:
            weather = r.json()
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

def _uk_offset(t):
    """BST (+1h) from 01:00 UTC on the last Sunday of March to the last Sunday of October."""
    y = time.localtime(t)[0]
    def last_sunday(month):
        ts = time.mktime((y, month, 31, 1, 0, 0, 0, 0))
        return ts - ((time.localtime(ts)[6] + 1) % 7) * 86400
    return 3600 if last_sunday(3) <= t < last_sunday(10) else 0

def local_time():
    t = time.time()
    if time.localtime(t)[0] < 2025:              # clock never synced
        return None
    return time.localtime(t + _uk_offset(t))

def _degrees(c, x, y, r):
    c.ellipse(x + r, y + r, r, r, 1)

def draw():
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    d.text_large("TODAY", 10, 8, 2)
    battery.draw(d, 212, 8)
    lt = local_time()
    if lt:
        date = "%s %d %s" % (DAYS[lt[6]], lt[2], MONTHS[lt[1] - 1])
        d.text_large(date, 390 - 16 * len(date), 8, 2)
        d.text_large("%02d:%02d" % (lt[3], lt[4]), 40, 50, 8)
    else:
        d.text_large("--:--", 40, 50, 8)
    d.line(0, 32, 400, 32, 1)
    d.line(0, 128, 400, 128, 1)

    w = weather
    if w:
        temp = "%d" % w["temp_c"]
        d.text_large(temp, 16, 142, 6)
        x = 16 + 48 * len(temp)
        _degrees(c, x + 2, 142, 5)
        d.text_large("C", x + 16, 142, 4)
        d.text_large(dashboard.ascii(w["condition"])[:14], 170, 142, 2)
        font5.text(c, dashboard.ascii("%s  feels like %dC" % (w.get("place", ""), w["feels_c"])), 170, 166)
        font5.text(c, "humidity %d%%   wind %d km/h" % (w["humidity"], w["wind_kmh"]), 170, 177)
        c.hline(16, 204, 368, 1)
        for i, (name, day) in enumerate((("Today", w["today"]), ("Tomorrow", w["tomorrow"]))):
            y = 216 + 26 * i
            d.text(name, 16, y, 1)
            font5.text(c, dashboard.ascii(day["condition"])[:18], 100, y)
            font5.text(c, "%d-%dC" % (day["low_c"], day["high_c"]), 222, y)
            font5.text(c, "rain %d%%" % day["rain_chance"], 300, y)
    else:
        d.text_large("weather loading...", 16, 180, 2)

    c.fill_rect(0, 286, 400, 14, 1)
    d.text("BOOT: next screen   KEY: refresh / hold to talk", 4, 289, 0)
    d.show()
