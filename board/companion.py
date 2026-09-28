# Speaking up on its own: Claude or Codex needs you, an AI limit passes 90%, rain within the hour,
# and a morning hello the first time it hears you after 07:00. Silent in quiet hours (22:00-08:00,
# pal.quiet_hours) and at most one unprompted line every 10 minutes; "needs you" always gets through.
# main.py queues lines here and voice.say() speaks them when the board is free.
import time
import pal, room

GAP_MS = 10 * 60 * 1000       # at most one unprompted line this often ("needs you" excepted)
STALE_MS = 30 * 60 * 1000     # a line still waiting after this (quiet hours) is dropped
LIMIT_PCT = 90
MORNING_HELLO = True
HELLO_FROM, HELLO_UNTIL = 7, 12

queue = []                    # [(kind, text, queued at)]
_last_said = None
_limit_warned = None          # windows already warned about ("Claude 5-hr"), until they drop below LIMIT_PCT
_rain_warned = False
_hello_day = None

def _add(kind, text, first=False):
    item = (kind, text, time.ticks_ms())
    queue[:] = [q for q in queue if q[0] != kind or kind == "needs"]   # the newest of each kind
    if first:
        queue.insert(0, item)
    else:
        queue.append(item)

def _spoken(name):
    return name.replace("-", " ").replace("_", " ")

def needs_you(agent, project):
    _add("needs", "%s needs you%s." % (agent or "Your agent", " in " + _spoken(project) if project else ""), first=True)

def check_limits(data):
    """After each limits fetch. The first call only notes what's already over, so a restart doesn't
    repeat a warning."""
    global _limit_warned
    over = {}
    for p in (data or {}).get("providers", []):
        for w in p.get("windows", []):
            if int(w.get("used", 0)) >= LIMIT_PCT:
                over["%s %s" % (p.get("name", "?"), w.get("label", ""))] = (p, w)
    if _limit_warned is None:
        _limit_warned = set(over)
        return
    for key, (p, w) in over.items():
        if key not in _limit_warned:
            label = w.get("label", "").replace("-hr", " hour").lower()
            _add("limit", "Heads up: your %s %s limit is at %d%%. It resets in %s." % (
                p.get("name", "?"), label, int(w["used"]), w.get("resets", "a while")))
    _limit_warned = set(over)          # a window that dropped back under (it reset) can warn again

def check_rain(weather):
    """After new home weather arrives. Says it once per dry spell."""
    global _rain_warned
    at = (weather or {}).get("rain_soon")
    if at and not _rain_warned:
        _add("rain", "Rain's on the way, starting around %s." % at)
    _rain_warned = bool(at)

def heard_you(limits):
    """The Pal just heard someone talking: the first time after 07:00 each morning, say hello."""
    global _hello_day
    lt = room.local_time()
    if not MORNING_HELLO or not lt or not HELLO_FROM <= lt[3] < HELLO_UNTIL or _hello_day == lt[2]:
        return
    _hello_day = lt[2]
    parts = ["Good morning!"]
    w = room.weather
    if w:
        parts.append("It's %d degrees and %s." % (w["temp_c"], w["condition"].lower()))
        if w["today"]["rain_chance"] >= 50:
            parts.append("There's a %d%% chance of rain today." % w["today"]["rain_chance"])
    used = ["%s is at %d%%" % (p["name"], int(p["windows"][0].get("used", 0)))
            for p in (limits or {}).get("providers", [])[:2] if p.get("windows")]
    if used:
        parts.append(" and ".join(used) + ".")
    _add("hello", " ".join(parts))

def drop(kind):
    queue[:] = [q for q in queue if q[0] != kind]

def next_line(hearing):
    """(kind, text) to say now, or None. `hearing(ms)`: someone talked in the last ms."""
    global _last_said
    now = time.ticks_ms()
    queue[:] = [q for q in queue if q[0] == "needs" or time.ticks_diff(now, q[2]) < STALE_MS]
    for item in queue:
        kind, text, _ = item
        if kind != "needs":
            if hearing(2000):                                   # don't talk over you
                return None
            if kind != "hello" and pal.quiet_hours():           # the hello only comes when you're up
                continue
            if _last_said is not None and time.ticks_diff(now, _last_said) < GAP_MS:
                return None
            _last_said = now
        queue.remove(item)
        return kind, text
    return None
