# The owner's calendar (private iCal link pasted on deskpal.local), for companion.py: heads-ups
# before meetings, and whether there's time for a focus session. desk-voice /api/calendar reads the
# link (sent as X-Calendar) and returns today's and tomorrow's events in UK time.
import time, json, requests, _thread
import secrets

URL = secrets.VOICE_URL.replace("/api/voice", "/api/calendar") + "?k=" + secrets.VOICE_KEY
FILE = "calendar.json"
REFRESH_MS = 10 * 60 * 1000

link = ""
today = []          # [{"s": start min, "e": end min, "t": title[, "all_day": True]}], UK time
tomorrow = []
error = ""
_day = None         # day of month `today` is for
_fetch_at = 0
_busy = False

try:
    link = json.load(open(FILE)).get("ics", "")
except Exception:
    pass

def set_link(url):
    global link, today, tomorrow, _fetch_at, error
    link, today, tomorrow, error = url.strip(), [], [], ""
    _fetch_at = 0
    with open(FILE, "w") as f:
        json.dump({"ics": link}, f)

def headers():
    """X-Calendar for voice questions ("what's on today?")."""
    return {"X-Calendar": link} if link else {}

def _worker(day):
    global today, tomorrow, error, _day, _busy
    try:
        r = requests.get(URL, headers={"X-Calendar": link}, timeout=15)
        if r.status_code == 200:
            d = r.json()
            today, tomorrow, _day, error = d["today"], d["tomorrow"], day, ""
        else:
            error = "calendar error %d" % r.status_code
        r.close()
    except Exception as e:
        error = "calendar: %s" % e
    _busy = False

def tick(connect, lt):
    """Call often; `lt` = room.local_time(). Refetches every 10 minutes and at midnight."""
    global _fetch_at, _busy
    if not link or not lt or _busy:
        return
    now = time.ticks_ms()
    if _day == lt[2] and time.ticks_diff(now, _fetch_at) < 0:
        return
    if not connect():
        return
    _fetch_at = time.ticks_add(now, REFRESH_MS)
    _busy = True
    try:
        _thread.stack_size(20 * 1024)
        _thread.start_new_thread(_worker, (lt[2],))
    except OSError:
        _worker(lt[2])

def timed(events):
    return [e for e in events if not e.get("all_day")]

def now_in(minute):
    """The meeting on right now, or None."""
    for e in timed(today):
        if e["s"] <= minute < e["e"]:
            return e
    return None

def next_after(minute):
    """The next meeting starting after `minute` today, or None."""
    for e in timed(today):
        if e["s"] > minute:
            return e
    return None

def status():
    if not link:
        return ""
    if error:
        return error
    n = len(timed(today))
    return "%d meeting%s today" % (n, "" if n == 1 else "s")
