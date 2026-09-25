import network, time, json, requests, ntptime
from machine import Pin
import dashboard, secrets, room, critter, voice, flights, timer, alerts, music, remote, webserver, home, audio

URL = "https://agent-limits.vercel.app/api/limits?k=" + secrets.READ_KEY
REFRESH_MS = 5 * 60 * 1000   # auto refresh; KEY refreshes on demand

key = Pin(18, Pin.IN, Pin.PULL_UP)
boot = Pin(0, Pin.IN, Pin.PULL_UP)

network.hostname("deskpal")    # reachable as http://deskpal.local on the home Wi-Fi
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(pm=wlan.PM_NONE)  # power save cuts HTTPS throughput ~3x; the board is on USB power

WIFI_FILE = "wifi.json"   # extra networks added from the remote page, e.g. the phone's hotspot

def saved_networks():
    try:
        return json.load(open(WIFI_FILE))
    except Exception:
        return []

def save_networks(nets):
    with open(WIFI_FILE, "w") as f:
        json.dump(nets, f)

def _scan(known):
    """Known networks in range, home first, then the rest by signal strength."""
    for attempt in (0, 1):
        try:
            wlan.disconnect()                      # a stuck auto-reconnect makes scans come back empty
        except Exception:
            pass
        try:
            found = {}
            for n in wlan.scan():
                name = n[0].decode()
                if name and n[3] > found.get(name.lower(), ("", -999))[1]:
                    found[name.lower()] = (name, n[3])
        except Exception:
            found = {}
        if found or attempt:
            break
        wlan.active(False)                         # radio wedged ("no AP found", empty scans): restart it
        time.sleep_ms(500)
        wlan.active(True)
        time.sleep_ms(500)
    # Names match case-insensitively ("eatPizza" saved, "eatPIZZA" broadcast); join with the broadcast spelling.
    hits = [(found[s.lower()][0], known[s], s == secrets.WIFI_SSID, found[s.lower()][1]) for s in known if s.lower() in found]
    return [(name, pw) for name, pw, is_home, rssi in sorted(hits, key=lambda h: (not h[2], -h[3]))]

def connect():
    """Join home Wi-Fi if it's in range, else the strongest saved network (the hotspot on the move)."""
    if wlan.isconnected():
        return True
    known = {secrets.WIFI_SSID: secrets.WIFI_PASSWORD}
    for n in saved_networks():
        known[n["ssid"]] = n["password"]
    for ssid, password in _scan(known) or [(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)]:
        dashboard.message("Joining Wi-Fi", ssid)
        wlan.connect(ssid, password)
        for _ in range(24):
            if wlan.isconnected():
                return True
            time.sleep(0.5)
        try:
            wlan.disconnect()
        except Exception:
            pass
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

def redraw():
    global shown_minute, timer_second
    shown_minute = None
    timer_second = None
    if screen == "flights":
        flights.enter()
    if screen == "music":
        music.enter()
    if screen == "alert":
        alerts.draw()
    if screen == "timer_done":
        timer.draw_done()
    if screen == "pixel":
        critter.scene.demo()
    if screen == "limits":
        show_limits(footer)

SCREENS = ("limits", "room", "pixel", "flights", "music")
# Takeover screens (not in the BOOT cycle): "timer", "timer_done", "alert". `home_screen` is where
# BOOT/dismiss returns to.
home_screen = "limits"

def show(name):
    """Switch to a screen (from BOOT, the remote page or a voice command)."""
    global screen, home_screen
    if name in SCREENS:
        home_screen = name
    screen = name
    redraw()

def leave_takeover():
    show(home_screen)

def run(cmd):
    """One command from the remote page or the voice assistant."""
    do = cmd.get("do")
    if do == "screen" and cmd.get("name") in SCREENS + ("timer",):
        show(cmd["name"])
    elif do == "timer":
        timer.start(float(cmd.get("minutes") or 25), cmd.get("label") or "Focus")
        show("timer")
    elif do == "timer_pause":
        timer.toggle_pause()
        if timer.active:
            show("timer")
    elif do == "timer_cancel":
        timer.cancel()
        if screen in ("timer", "timer_done"):
            leave_takeover()
    elif do == "music":
        music.control(cmd.get("what") or "toggle")
        show("music")
    elif do == "alerts_clear":
        alerts.clear()
        if screen == "alert":
            leave_takeover()

def local_clock():
    lt = room.local_time()
    return "%02d:%02d" % (lt[3], lt[4]) if lt else ""

def handle(method, path, q, body):
    """LAN requests: the remote page, the Mac's agent hooks and the Spotify sign-in hand-off."""
    # The remote page and its buttons are open to anyone on the home Wi-Fi; only the Mac's agent
    # alerts and the Spotify token hand-off need the key.
    if path in ("/agent", "/spotify-token") and q.get("k") != secrets.VOICE_KEY:
        return 401, "text/plain", "wrong or missing key"
    if path == "/spotify-login":
        return 200, "text/html", "<meta http-equiv=refresh content='0;url=%s&board=%s'>" % (remote.SPOTIFY_LOGIN, wlan.ifconfig()[0])
    if path == "/":
        return 200, "text/html", remote.page()
    if path == "/location":
        try:
            lat, lon = float(q["lat"]), float(q["lon"])
        except Exception:
            return 400, "text/plain", "bad location"
        home.save(lat, lon, q.get("place", ""))
        room.fetch_weather()                     # weather and radar re-centre on the new spot
        flights.last = None
        flights.refresh_now()
        redraw()
        return 200, "text/html", ("<meta name=viewport content='width=device-width'><body style='font:17px ui-monospace,monospace;padding:24px'>"
                                  "<h2>Location saved</h2><p>%s</p><p><a href='/'>Back to Desk Pal</a></p>") % (q.get("place") or "%.4f, %.4f" % (lat, lon))
    if path == "/wifi":
        loc = home.current()
        return 200, "application/json", json.dumps({
            "location": (loc.get("place") or "phone location") if loc else "",
            "connected": wlan.config("ssid") if wlan.isconnected() else "",
            "home": secrets.WIFI_SSID, "saved": [n["ssid"] for n in saved_networks()]})
    if path == "/wifi/add" and q.get("ssid"):
        nets = [n for n in saved_networks() if n["ssid"] != q["ssid"]]
        nets.append({"ssid": q["ssid"], "password": q.get("password", "")})
        save_networks(nets)
        return 200, "application/json", '{"ok":true}'
    if path == "/wifi/remove" and q.get("ssid"):
        save_networks([n for n in saved_networks() if n["ssid"] != q["ssid"]])
        return 200, "application/json", '{"ok":true}'
    if path == "/state":
        return 200, "application/json", json.dumps({
            "screen": screen, "timer": timer.status(), "music": music.status(),
            "alert": ("%d agent alert(s)" % len(alerts.queue)) if alerts.queue else ""})
    if path == "/agent":
        a = json.loads(body or b"{}")
        alerts.add(a.get("agent"), a.get("project"), "needs" if a.get("kind") == "needs" else "done",
                   a.get("message"), local_clock())
        pending_alert.append(alerts.queue[-1]["kind"])
        return 200, "application/json", '{"ok":true}'
    if path == "/spotify-token" and q.get("refresh"):
        music.save_token(q["refresh"])
        show("music")
        return 200, "text/html", "<meta name=viewport content='width=device-width'><h2>Spotify connected.</h2><p>You can close this page.</p>"
    routes = {"/screen": {"do": "screen", "name": q.get("name")},
              "/timer": {"do": "timer", "minutes": q.get("minutes"), "label": q.get("label")},
              "/timer/pause": {"do": "timer_pause"}, "/timer/cancel": {"do": "timer_cancel"},
              "/music": {"do": "music", "what": q.get("do")}, "/alerts/clear": {"do": "alerts_clear"}}
    if path in routes:
        run(routes[path])
        return 200, "application/json", '{"ok":true}'
    return 404, "text/plain", "not found"

pending_alert = []    # alert kinds waiting to chime (the HTTP handler must answer fast)
ALERT_MS = 3000       # agent alerts dismiss themselves after this
alert_until = 0

# The radar's background fetch can hold the interpreter for ~0.5 s during the TLS handshake,
# long enough to miss a quick tap if BOOT were only polled; an edge interrupt latches it instead.
boot_hit = False

def _on_boot(pin):
    global boot_hit
    boot_hit = True

boot.irq(trigger=Pin.IRQ_FALLING, handler=_on_boot)

def boot_tapped():
    """True once per BOOT press (latched by the IRQ); returns after release."""
    global boot_hit
    if not boot_hit and boot.value():
        return False
    while not boot.value():
        time.sleep_ms(10)
    time.sleep_ms(30)
    boot_hit = False                     # swallow release bounce
    return True

screen = "limits"
timer_second = None
next_wifi_try = 0
web = webserver.Server()
footer = fetch()
clock_ok = sync_clock()
show_limits(footer)
next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
shown_minute = None

while True:
    web.poll(handle)
    if pending_alert:
        kind = pending_alert.pop(0)
        if screen != "alert":
            screen = "alert"
            redraw()
        else:
            alerts.draw()
        alerts.chime(kind)
        alert_until = time.ticks_add(time.ticks_ms(), ALERT_MS)
    if screen == "alert" and time.ticks_diff(time.ticks_ms(), alert_until) >= 0:
        alerts.clear()                           # gone after a glance; the chime already got your attention
        leave_takeover()
    if timer.finished():
        timer.cancel()                           # label/total stay set for the done screen
        screen = "timer_done"
        redraw()
        timer.chime()

    audio.listen()                       # the wake phrase works on every screen
    action = pixel_key() if screen == "pixel" else key_action()
    heard = audio.woke() if action is None else None
    if heard:
        action = "hold"                  # same as holding KEY, but it records until you stop talking
    if action == "tap" and screen in ("alert", "timer_done"):
        if screen == "alert":
            alerts.clear()
        leave_takeover()
    elif action == "tap" and screen == "timer":
        timer.toggle_pause()
        timer_second = None
    elif action == "tap" and screen == "music":
        music.control("toggle")
    elif action == "tap" and screen == "flights":
        flights.refresh_now()
    elif action == "tap" and screen == "room":
        room.fetch_weather()
        shown_minute = None
    elif action == "tap":
        screen = "limits"
        show_limits("refreshing...")
        footer = fetch()
        show_limits(footer)
        next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
    elif action == "hold":
        try:
            result = voice.ask(key, boot, connect, heard)
            cmds = result.get("board", []) if isinstance(result, dict) else []
            if isinstance(result, dict) and result.get("radar"):
                cmds.append({"do": "screen", "name": "flights"})   # "show flights near London": go look
            if cmds:
                for cmd in cmds:
                    run(cmd)
                result = "handled"
            elif result != "back":
                end = time.ticks_add(time.ticks_ms(), 20000)   # leave the answer up for a bit
                while time.ticks_diff(end, time.ticks_ms()) > 0 and key.value() and boot.value():
                    time.sleep_ms(50)
        except Exception as e:
            dashboard.message("Voice failed", str(e))
            time.sleep(5)
        while not boot.value():          # BOOT here means "back", not "next screen"
            time.sleep_ms(10)
        time.sleep_ms(30)
        boot_hit = False
        if result != "handled":
            redraw()
    elif boot_tapped():
        if screen == "timer":
            timer.cancel()
            leave_takeover()
        elif screen in ("alert", "timer_done"):
            if screen == "alert":
                alerts.clear()
            leave_takeover()
        else:
            show(SCREENS[(SCREENS.index(screen) + 1) % len(SCREENS)])
    if not wlan.isconnected() and time.ticks_diff(time.ticks_ms(), next_wifi_try) >= 0:
        # Offline (left home, router restart...): try the known networks every 30 s, then put the
        # current screen back since connect() draws "joining wi-fi".
        next_wifi_try = time.ticks_add(time.ticks_ms(), 30000)
        if connect():
            redraw()
    if time.ticks_diff(time.ticks_ms(), next_fetch) >= 0:
        footer = fetch()
        if not clock_ok:
            clock_ok = sync_clock()
        if screen == "limits":
            show_limits(footer)
        next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
    if screen == "room":
        if room.weather_due() and connect():
            room.fetch_weather()
            shown_minute = None
        lt = room.local_time()
        minute = lt[4] if lt else -1
        if minute != shown_minute:
            room.draw()
            shown_minute = minute
    if screen == "flights":
        flights.tick(connect)
    if screen == "music":
        music.tick(connect)
    if screen == "timer":
        sec = timer.remaining() // 1000
        if sec != timer_second:
            timer.draw()
            timer_second = sec
    if screen == "pixel":
        critter.scene.step()
        critter.scene.draw()
    else:
        time.sleep_ms(50)
