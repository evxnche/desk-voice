# Spotify now-playing screen. The board keeps its own Spotify refresh token (spotify.json, saved
# when you sign in from the remote page); desk-voice /api/spotify swaps it for access tokens.
import json, time, requests, _thread, framebuf
import dashboard, font5, secrets

API = secrets.VOICE_URL.replace("/api/voice", "/api/spotify") + "?k=" + secrets.VOICE_KEY
TOKEN_FILE = "spotify.json"
POLL_MS = 5000
ART = 152             # cover size in px (dithered to 1-bit by desk-voice)

try:
    refresh = json.load(open(TOKEN_FILE))["refresh"]
except Exception:
    refresh = None

cover = None          # FrameBuffer of the current album cover
_cover_url = ""
now = None            # latest /now result
_now_at = 0           # ticks when `now` arrived (progress glides from here)
_busy = False
_incoming = None
_next_poll = 0
_next_frame = 0

def save_token(token):
    global refresh, _next_poll
    refresh = token
    with open(TOKEN_FILE, "w") as f:
        json.dump({"refresh": token}, f)
    _next_poll = time.ticks_ms()

def headers():
    return {"X-Spotify-Refresh": refresh} if refresh else {}

def _quote(s):
    return "".join(c if c.isalpha() or c.isdigit() or c in "-_.~" else "%%%02X" % ord(c) for c in s)

def _fetch_cover(art_url):
    """Download the dithered cover once per album (runs in the worker thread)."""
    global cover, _cover_url
    if art_url == _cover_url:
        return
    fb = None
    if art_url:
        r = requests.get(API + "&action=art&size=%d&url=%s" % (ART, _quote(art_url)), timeout=15)
        if r.status_code == 200:
            buf = bytearray(r.content)
            if len(buf) == ART * ART // 8:
                fb = framebuf.FrameBuffer(buf, ART, ART, framebuf.MONO_HLSB)
        r.close()
    cover, _cover_url = fb, art_url

def _worker(url, method):
    global _incoming, _busy
    try:
        r = requests.request(method, url, headers=headers(), timeout=15)
        data = r.json() if r.status_code == 200 else {"error": "spotify %d" % r.status_code}
        r.close()
        if data.get("title"):
            try:
                _fetch_cover(data.get("art_url", ""))
            except Exception:
                pass                      # no cover is fine; the text still shows
        _incoming = data
    except Exception as e:
        _incoming = {"error": str(e)}
    _busy = False

def _start(action, method="GET", extra=""):
    global _busy
    if _busy or not refresh:
        return
    _busy = True
    job = (API + "&action=" + action + extra, method)
    try:
        _thread.stack_size(20 * 1024)     # plenty for TLS; bigger stacks didn't fit beside Bluetooth
        _thread.start_new_thread(_worker, job)
    except OSError:
        _worker(*job)                     # no stack fits with Bluetooth on: fetch here instead

def control(what):
    """play / pause / toggle / next / previous. The reply is fresh now-playing state."""
    global _next_poll
    _start("control", "POST", "&do=" + what)
    _next_poll = time.ticks_add(time.ticks_ms(), POLL_MS)

def enter():
    global _next_poll, _next_frame
    _next_frame = time.ticks_ms()
    _next_poll = time.ticks_add(_next_frame, 100)   # draw first, so switching here shows at once

def status():
    if not now or not now.get("title"):
        return ""
    return "%s %s - %s" % ("Playing" if now.get("playing") else "Paused", now["title"], now.get("artist", ""))

def tick(connect):
    global now, _now_at, _incoming, _next_poll, _next_frame
    t = time.ticks_ms()
    if time.ticks_diff(t, _next_poll) >= 0:
        if connect():
            _start("now")
        _next_poll = time.ticks_add(t, POLL_MS)
    if _incoming is not None:
        now, _now_at, _incoming = _incoming, t, None
        _next_frame = t
    if time.ticks_diff(t, _next_frame) >= 0:
        draw()
        _next_frame = time.ticks_add(t, 1000)

def _mmss(ms):
    s = max(0, ms) // 1000
    return "%d:%02d" % (s // 60, s % 60)

def _wrap(text, width, lines):
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    out.append(line)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][:width - 3] + "..."
    return out

def draw():
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    d.text_large("MUSIC", 10, 8, 2)
    d.line(0, 32, 400, 32, 1)
    if not refresh:
        d.text_large("Spotify not connected", 10, 100, 2)
        font5.text(c, "Open http://deskpal.local on your phone or Mac", 10, 140)
        font5.text(c, "and tap 'Connect Spotify'.", 10, 152)
    elif now is None:
        d.text_large("loading...", 10, 120, 2)
    elif now.get("error"):
        d.text_large("Spotify error", 10, 100, 2)
        font5.text(c, dashboard.ascii(now["error"])[:64], 10, 130)
    elif not now.get("title"):
        d.text_large("Nothing playing", 10, 110, 3)
        font5.text(c, "Start Spotify on any device, or hold KEY and say", 10, 160)
        font5.text(c, "\"play something chill\".", 10, 172)
    else:
        if now.get("device"):
            dev = dashboard.ascii("on " + now["device"])[:30]
            font5.text(c, dev, 392 - 6 * len(dev), 13)
        # cover (or an empty frame) on the left
        c.rect(9, 41, ART + 2, ART + 2, 1)
        if cover:
            c.blit(cover, 10, 42)
        else:
            font5.text(c, "no cover", 10 + ART // 2 - 24, 42 + ART // 2 - 4)
        # title / artist / album on the right
        x = ART + 24
        y = 46
        for line in _wrap(dashboard.ascii(now["title"]), 13, 3):
            d.text_large(line, x, y, 2)
            y += 20
        y += 6
        for line in _wrap(dashboard.ascii(now.get("artist", "")), 36, 2):
            font5.text(c, line, x, y)
            y += 10
        y += 4
        for line in _wrap(dashboard.ascii(now.get("album", "")), 36, 2):
            font5.text(c, line, x, y)
            y += 10
        state = "playing" if now.get("playing") else "paused"
        d.text_large(state, x, 176, 2)
        # progress glides between polls while playing
        pos = now.get("progress_ms", 0)
        if now.get("playing"):
            pos += time.ticks_diff(time.ticks_ms(), _now_at)
        dur = max(1, now.get("duration_ms", 1))
        pos = min(pos, dur)
        c.rect(10, 206, 380, 12, 1)
        c.fill_rect(12, 208, 376 * pos // dur, 8, 1)
        font5.text(c, _mmss(pos), 10, 224)
        font5.text(c, _mmss(dur), 390 - 6 * len(_mmss(dur)), 224)
    c.fill_rect(0, 286, 400, 14, 1)
    d.text("KEY: play/pause   BOOT: next   hold: talk", 4, 289, 0)
    d.show()
