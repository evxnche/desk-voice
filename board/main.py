import network, time, json, requests, ntptime, esp32
from machine import Pin
import dashboard, secrets, room, critter, voice, flights, timer, alerts, music, remote, webserver, home, audio, phone, usage
import pal, companion

# The firmware has rollback on: an OTA update not confirmed here reverts to the old slot on the next reboot.
esp32.Partition.mark_app_valid_cancel_rollback()

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
    """Update `last` straight from Anthropic/OpenAI once signed in on the remote page, else from the
    relay; return a footer message ('' when fresh)."""
    global last
    if not connect():
        return "no Wi-Fi - showing last known"
    try:
        if usage.connected():
            data = usage.fetch(last)
        else:
            r = requests.get(URL, timeout=15)
            code = r.status_code
            data = r.json() if code == 200 else None
            r.close()
        if data:
            last = data
            with open("limits.json", "w") as f:
                json.dump(last, f)
        return "" if data else "relay error %d" % code
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

# A KEY tap made while the loop was busy (drawing, a fetch on this thread) used to be missed
# entirely: an edge interrupt latches it, and key_action() counts it as a tap.
key_hit = False

def _on_key(pin):
    global key_hit
    key_hit = True

key.irq(trigger=Pin.IRQ_FALLING, handler=_on_key)

def key_press():
    """key_action(), plus a tap latched while the loop couldn't look."""
    global key_hit
    action = key_action()
    if action is None and key_hit and key.value():
        action = "tap"
    if action is not None or key.value():
        time.sleep_ms(30 if action == "tap" else 0)
        key_hit = False                  # this press (and its release bounce) is handled
    return action

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
    if screen == "pal":
        pal.ambient.enter()
    if screen == "limits":
        show_limits(footer)

SCREENS = ("pal", "limits", "room", "pixel", "flights", "music")
# Takeover screens (not in the BOOT cycle): "timer", "timer_done", "alert". `home_screen` is where
# BOOT/dismiss returns to.
home_screen = "pal"

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
    elif do == "weather":                  # what the voice assistant just looked up
        room.set_weather(cmd["data"], cmd.get("home", True))
    elif do == "alerts_clear":
        alerts.clear()
        if screen == "alert":
            leave_takeover()

def local_clock():
    lt = room.local_time()
    return "%02d:%02d" % (lt[3], lt[4]) if lt else ""

def handle(method, path, q, body):
    """LAN requests: the remote page, the Mac's agent hooks and the Spotify sign-in hand-off."""
    # The remote page and its buttons are open to anyone on the home Wi-Fi. Mac agent alerts use the
    # shared key; Spotify token hand-offs use a token-specific signature so the key stays private.
    if path == "/agent" and q.get("k") != secrets.VOICE_KEY:
        return 401, "text/plain", "wrong or missing key"
    if path == "/spotify-token" and not music.verify_handoff(q.get("refresh"), q.get("sig")):
        return 401, "text/plain", "invalid Spotify handoff"
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
            "alert": ("%d alert(s)" % len(alerts.queue)) if alerts.queue else "", "phone": phone.status(),
            "limits": usage.connected()})
    if path.startswith("/connect/"):
        return 200, "application/json", json.dumps(connect_agent(path, q))
    if path == "/agent":
        a = json.loads(body or b"{}")
        alerts.add(a.get("agent"), a.get("project"), "needs" if a.get("kind") == "needs" else "done",
                   a.get("message"), local_clock())
        pending_alert.append(alerts.queue[-1]["kind"])
        if a.get("kind") == "needs":
            companion.needs_you(a.get("agent"), a.get("project"))   # the Pal says it after the chime
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

def connect_agent(path, q):
    """Sign-in steps from the remote page's Connect Claude / Connect Codex buttons."""
    global next_fetch
    try:
        if path == "/connect/claude" and q.get("code"):
            usage.claude_finish(q["code"])
        elif path == "/connect/claude":
            return {"url": usage.claude_login_url()}
        elif path == "/connect/codex":
            return {"code": usage.codex_start(), "url": usage.CODEX_DEVICE_PAGE}
        elif path == "/connect/codex/check":
            if not usage.codex_poll():
                return {"waiting": True}
        else:
            return {"error": "unknown step"}
    except Exception as e:
        return {"error": str(e)}
    next_fetch = time.ticks_ms()          # show the new numbers right away
    return {"ok": True}

pending_alert = []    # alert kinds waiting to chime (the HTTP handler must answer fast)
ALERT_MS = 3000       # agent alerts dismiss themselves after this
MESSAGE_MS = 8000     # WhatsApp messages stay long enough to read
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

screen = "pal"
timer_second = None
def tick_screen(speaking=False):
    """Keep the current screen up to date; call often. While `speaking` (an answer playing over the
    screen) only the radar keeps going (~80 ms a frame): the other screens take 0.3-1 s to redraw,
    long enough to break up the voice, so they catch up once it's done."""
    global shown_minute, timer_second
    if speaking and screen != "flights":
        return
    if screen == "room":
        lt = room.local_time()
        minute = (lt[4] if lt else -1, room.version)   # redraw each minute and when new weather lands
        if minute != shown_minute:
            room.draw()
            shown_minute = minute
        elif room.weather_due() and connect():   # after drawing, so switching here shows at once
            room.fetch_weather_soon()
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
    if screen == "pal":
        pal.ambient.tick(pal.status_line(last))

next_wifi_try = 0
web = webserver.Server()
try:
    phone.start()                        # iPhone notifications over Bluetooth
except Exception as e:
    print("bluetooth failed:", e)
footer = fetch()
clock_ok = sync_clock()
companion.check_limits(last)
pal.ambient.on_hear = lambda: companion.heard_you(last)
redraw()
next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
shown_minute = None
weather_seen = room.version

while True:
    web.poll(handle)
    phone.tick()
    while phone.inbox:
        m = phone.inbox.pop(0)
        alerts.add(m["title"] or "WhatsApp", m["subtitle"], "message", m["message"], local_clock())
        pending_alert.append("message")
    if pending_alert and pending_alert[0] == "needs":
        pending_alert.pop(0)
        alerts.chime("needs")                    # the Pal then says who needs you (companion queue)
    elif pending_alert:
        kind = pending_alert.pop(0)
        if screen != "alert":
            screen = "alert"
            redraw()
        else:
            alerts.draw()
        alerts.chime(kind)
        alert_until = time.ticks_add(time.ticks_ms(), MESSAGE_MS if kind == "message" else ALERT_MS)
    if screen == "alert" and time.ticks_diff(time.ticks_ms(), alert_until) >= 0:
        alerts.clear()                           # gone after a glance; the chime already got your attention
        leave_takeover()
    if timer.finished():
        timer.cancel()                           # label/total stay set for the done screen
        screen = "timer_done"
        redraw()
        timer.chime()

    audio.listen()                       # the wake phrase works on every screen
    pal.ambient.sense()                  # how loud the room is (the Pal perks up; morning hello)
    if screen == "pixel":
        action = pixel_key()
        key_hit = False                  # the game reacts to every press itself
    else:
        action = key_press()
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
        room.fetch_weather_soon()
    elif action == "tap" and screen == "pal":
        footer = fetch()                         # fresh limits on the status line
        companion.check_limits(last)
        next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
        pal.ambient.enter()
    elif action == "tap":
        screen = "limits"
        show_limits("refreshing...")
        footer = fetch()
        show_limits(footer)
        next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
    elif action == "hold":
        result, on_screen = None, False
        try:
            result = voice.ask(key, boot, connect, run, tick_screen, heard)
            while isinstance(result, dict):
                # Listen a few seconds for a reply, no "gee gee" needed; an answer that opened a
                # screen (weather, radar, music) stays up meanwhile.
                on_screen = bool(result["board"])
                result = voice.ask(key, boot, connect, run, tick_screen, followup=True, keep_screen=on_screen)
        except Exception as e:
            dashboard.message("Voice failed", str(e))
            time.sleep(5)
        companion.drop("hello")                  # you're clearly up: no hello after this
        while not boot.value():          # BOOT here means "back", not "next screen"
            time.sleep_ms(10)
        time.sleep_ms(30)
        boot_hit = key_hit = False
        if not (on_screen and result == "quiet"):
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
        companion.check_limits(last)
        if not clock_ok:
            clock_ok = sync_clock()
        if screen == "limits":
            show_limits(footer)
        next_fetch = time.ticks_add(time.ticks_ms(), REFRESH_MS)
    # Weather for every screen (the Pal's status line, rain warnings), not just "today"; the today
    # screen fetches its own after drawing, so switching there stays instant.
    if screen != "room" and room.weather_due() and wlan.isconnected():
        room.fetch_weather_soon()
    if room.version != weather_seen:
        weather_seen = room.version
        if room.weather_is_home:
            companion.check_rain(room.weather)
    if action is None and not heard and screen not in ("alert", "timer_done"):
        line = companion.next_line(pal.ambient.hearing)
        if line:
            said = False
            try:
                said = voice.say(line[1], boot, connect)
            except Exception as e:
                print("say failed:", e)
            while not boot.value():
                time.sleep_ms(10)
            boot_hit = key_hit = False
            if not said and line[0] == "needs":  # couldn't say it: show it instead
                screen = "alert"
                alert_until = time.ticks_add(time.ticks_ms(), ALERT_MS)
            redraw()
    try:
        tick_screen()
    except Exception as e:               # one screen's error mustn't stop the whole app
        print("screen error:", e)
    if screen != "pixel":
        time.sleep_ms(50)
