# Agent babysitter: alerts pushed by the Mac's Claude Code / Codex hooks over the LAN.
import time, math, struct
import dashboard, font5, audio

queue = []            # newest last: {"agent", "project", "kind": "needs"|"done", "message", "at"}

def add(agent, project, kind, message, at):
    queue.append({"agent": agent or "Agent", "project": project or "", "kind": kind,
                  "message": message or "", "at": at})
    del queue[:-6]    # keep the last few

def clear():
    queue.clear()

def chime(kind):
    """'needs you': urgent two-tone; 'done': soft falling pair."""
    notes = (988, 740, 988, 740) if kind == "needs" else (880, 660)
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
    return "%s needs you" % a["agent"] if a["kind"] == "needs" else "%s is done" % a["agent"]

def draw():
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    if not queue:
        d.show()
        return
    a = queue[-1]
    c.fill_rect(0, 0, 400, 34, 1)
    d.text("AGENT", 10, 13, 0)
    d.text(a["at"], 392 - 8 * len(a["at"]), 13, 0)
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
