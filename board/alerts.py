# Agent babysitter: alerts pushed by the Mac's Claude Code / Codex hooks over the LAN, plus WhatsApp
# messages from the iPhone (phone.py; kind "message", agent = sender, project = group).
import time, math, struct
import dashboard, font5, audio, palicon

queue = []            # newest last: {"agent", "project", "kind": "needs"|"done"|"message", "message", "at"}
DEDUP_MS = 2 * 60 * 1000
MAX_PENDING = 6
_recent = []          # (agent, project, kind, message), ticks_ms

def add(agent, project, kind, message, at):
    item = {"agent": agent or "Agent", "project": project or "", "kind": kind,
            "message": message or "", "at": at}
    now = time.ticks_ms()
    _recent[:] = [seen for seen in _recent if time.ticks_diff(now, seen[1]) < DEDUP_MS]
    key = (item["agent"], item["project"], item["kind"], item["message"])
    if any(seen[0] == key for seen in _recent):
        return False
    _recent.append((key, now))
    del _recent[:-12]
    queue.append(item)
    del queue[:-6]    # keep the last few
    return True

def latest_needs():
    for item in reversed(queue):
        if item["kind"] == "needs":
            return item.copy()
    return None

def resolve(agent, project, pending=None):
    """A later done event closes this agent/project request in every waiting alert queue."""
    agent, project = agent or "Agent", project or ""
    queue[:] = [item for item in queue if not (item["kind"] == "needs" and
               item["agent"] == agent and item["project"] == project)]
    _recent[:] = [seen for seen in _recent if not (seen[0][0] == agent and
                  seen[0][1] == project and seen[0][2] == "needs")]
    if pending is not None:
        pending[:] = [record for record in pending if not (record["alert"]["kind"] == "needs" and
                      record["alert"]["agent"] == agent and record["alert"]["project"] == project)]

def _compact_routine(pending):
    routine = [(index, record) for index, record in enumerate(pending)
               if record["alert"]["kind"] != "needs"]
    if len(routine) < 2:
        return
    total = sum(record["count"] for _, record in routine)
    first = routine[0][0]
    latest = routine[-1][1]["alert"]
    pending[:] = [record for record in pending if record["alert"]["kind"] == "needs"]
    pending.insert(first, {"alert": latest, "count": total})

def queue_pending(pending, alert, focused=False):
    """Hold an alert's own details; collapse routine updates while focus is active."""
    pending.append({"alert": alert.copy(), "count": 1})
    if focused or len(pending) > MAX_PENDING:
        _compact_routine(pending)
    while len(pending) > MAX_PENDING:
        oldest_urgent = next((i for i, record in enumerate(pending)
                              if record["alert"]["kind"] == "needs"), 0)
        pending.pop(oldest_urgent)

def next_pending(pending, focused=False):
    """Take an urgent alert first, or one routine alert once focus ends."""
    if not pending:
        return None
    for index, record in enumerate(pending):
        if record["alert"]["kind"] == "needs":
            return pending.pop(index)["alert"]
    if focused:
        _compact_routine(pending)
        return None
    record = pending.pop(0)
    alert = record["alert"]
    if record["count"] == 1:
        return alert
    latest = "%s%s: %s" % (alert["agent"], " in " + alert["project"] if alert["project"] else "", alert["message"])
    return {"agent": "Updates", "project": "", "kind": "summary", "count": record["count"],
            "message": "Latest: " + latest, "at": alert["at"]}

def clear():
    queue.clear()

def chime(kind):
    """'needs you': urgent two-tone; 'done': soft falling pair; 'message': quick rising pair."""
    notes = {"needs": (988, 740, 988, 740), "message": (1047, 1319)}.get(kind, (880, 660))
    n = audio.RATE // 6
    buf = bytearray(n * 2 * len(notes))
    i = 0
    for f in notes:
        step = 2 * math.pi * f / audio.RATE
        for k in range(n):
            fade = min(1, k / 300, (n - k) / 300)
            struct.pack_into("<h", buf, i, int(11000 * fade * math.sin(k * step)))
            i += 2
    audio.play(buf, volume=0xC8, mono=True)

def _title(a):
    if a["kind"] == "summary":
        return "%d updates" % a["count"]
    if a["kind"] == "message":
        return a["agent"]
    return "%s needs you" % a["agent"] if a["kind"] == "needs" else "%s is done" % a["agent"]

def draw(alert=None):
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    if not queue and alert is None:
        d.show()
        return
    a = alert if alert is not None else queue[-1]
    c.fill_rect(0, 0, 400, 34, 1)
    d.text("WHATSAPP" if a["kind"] == "message" else "AGENT", 10, 13, 0)
    d.text(a["at"], 392 - 8 * len(a["at"]), 13, 0)
    c.fill_rect(300, 3, palicon.WIDTH, palicon.HEIGHT, 0)
    palicon.draw(c, 300, 3, "done" if a["kind"] == "done" else "alert")
    title = dashboard.ascii(_title(a))
    scale = 3 if len(title) <= 16 else 2
    d.text_large(title[:24], 10, 52, scale)
    if a["project"]:
        d.text_large(dashboard.ascii(a["project"])[:24], 10, 52 + 8 * scale + 14, 2)
    y = 130
    msg = dashboard.ascii(a["message"])
    while msg and y < 200:                 # wrap at 64 chars in the small font
        cut = msg[:64]
        if len(msg) > 64 and " " in cut:
            cut = cut[:cut.rindex(" ")]
        font5.text(c, cut, 10, y)
        msg = msg[len(cut):].lstrip()
        y += 10
    if len(queue) > 1:
        c.hline(10, 212, 380, 1)
        y = 220
        for b in reversed(queue[:-1][-4:]):
            font5.text(c, dashboard.ascii("%s  %s - %s" % (b["at"], _title(b), b["project"]))[:64], 10, y)
            y += 11
    c.fill_rect(0, 286, 400, 14, 1)
    d.text("KEY or BOOT: dismiss", 4, 289, 0)
    d.show()
