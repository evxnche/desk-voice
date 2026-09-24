import network, time, json, requests, ntptime
from machine import Pin
import dashboard, secrets, room, critter, voice, flights

URL = "https://agent-limits.vercel.app/api/limits?k=" + secrets.READ_KEY
REFRESH_MS = 5 * 60 * 1000   # auto refresh; KEY refreshes on demand

key = Pin(18, Pin.IN, Pin.PULL_UP)
boot = Pin(0, Pin.IN, Pin.PULL_UP)

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(pm=wlan.PM_NONE)  # power save cuts HTTPS throughput ~3x; the board is on USB power

def connect():
    if wlan.isconnected():
        return True
    dashboard.message("Joining Wi-Fi", secrets.WIFI_SSID)
    wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
    for _ in range(40):
        if wlan.isconnected():
            return True
        time.sleep(0.5)
    return False

def sync_clock():
    try:
        ntptime.settime()
        return True
    except Exception:
        return False

last = None
try:
    last = json.load(open("limits.json"))
except Exception:
    pass

def fetch():
    """Update `last` from the relay; return a footer message ('' when fresh)."""
    global last
    if not connect():
        return "no Wi-Fi - showing last known"
    try:
        r = requests.get(URL, timeout=15)
        ok = r.status_code == 200
        if ok:
            last = r.json()
            with open("limits.json", "w") as f:
                json.dump(last, f)
        code = r.status_code
        r.close()
        return "" if ok else "relay error %d" % code
    except Exception as e:
        return "fetch failed: %s" % e

def show_limits(footer):
    if last:
        dashboard.draw(last, footer)
    else:
        dashboard.message("No data yet", footer)

def key_action():
    """'tap' for a short KEY press, 'hold' once KEY has been down 0.4 s, else None."""
    if key.value():
        return None
    t0 = time.ticks_ms()
    while not key.value():
        if time.ticks_diff(time.ticks_ms(), t0) > 400:
            return "hold"
        time.sleep_ms(10)
    return "tap" if time.ticks_diff(time.ticks_ms(), t0) > 30 else None

def pixel_key():
    """KEY on the pixel screen: jump the instant it goes down; 'hold' after 0.4 s (voice)."""
    global key_down_at
    if key.value():
        key_down_at = None
        return None
    now = time.ticks_ms()
    if key_down_at is None:
        key_down_at = now
        critter.scene.press()
    elif time.ticks_diff(now, key_down_at) > 400:
        key_down_at = None
        return "hold"
    return None

key_down_at = None
flights_next = 0

def redraw():
    global shown_minute, flights_next
    shown_minute = None
    flights_next = time.ticks_ms()
    if screen == "pixel":
        critter.scene.demo()
    if screen == "limits":
        show_limits(footer)

SCREENS = ("limits", "room", "pixel", "flights")
FLIGHTS_MS = 15000   # radar refresh while that screen is showing

def pressed(pin):
    """Debounced press: True once per press, returns after release."""
    if pin.value():
        return False
    time.sleep_ms(30)
    if pin.value():
        return False
    while not pin.value():
        time.sleep_ms(10)
    return True

screen = "limits"
footer = fetch()
clock_ok = sync_clock()
show_limits(footer)
next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
shown_minute = None

while True:
    action = pixel_key() if screen == "pixel" else key_action()
    if action == "tap" and screen == "flights":
        flights_next = time.ticks_ms()
    elif action == "tap":
        screen = "limits"
        show_limits("refreshing...")
        footer = fetch()
        show_limits(footer)
        next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
    elif action == "hold":
        try:
            if voice.ask(key, boot, connect) != "back":
                end = time.ticks_add(time.ticks_ms(), 20000)   # leave the answer up for a bit
                while time.ticks_diff(end, time.ticks_ms()) > 0 and key.value() and boot.value():
                    time.sleep_ms(50)
        except Exception as e:
            dashboard.message("Voice failed", str(e))
            time.sleep(5)
        while not boot.value():          # BOOT here means "back", not "next screen"
            time.sleep_ms(10)
        redraw()
    elif pressed(boot):
        screen = SCREENS[(SCREENS.index(screen) + 1) % len(SCREENS)]
        redraw()
    if time.ticks_diff(time.ticks_ms(), next_fetch) >= 0:
        footer = fetch()
        if not clock_ok:
            clock_ok = sync_clock()
        if screen == "limits":
            show_limits(footer)
        next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
    if screen == "room":
        lt = room.local_time()
        minute = lt[4] if lt else -1
        if minute != shown_minute:
            room.draw()
            shown_minute = minute
    if screen == "flights" and time.ticks_diff(time.ticks_ms(), flights_next) >= 0:
        if flights.last is None:
            flights.draw()                   # "loading..." while the first fetch runs
        flights.draw(flights.fetch() if connect() else "no Wi-Fi")
        flights_next = time.ticks_add(time.ticks_ms(), FLIGHTS_MS)
    if screen == "pixel":
        critter.scene.step()
        critter.scene.draw()
    else:
        time.sleep_ms(50)
