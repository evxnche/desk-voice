# Menu screen: everything Desk Pal can do, and how to get at it, over a few pages. Opened by voice
# ("gee gee, menu", "what can you do?") or from deskpal.local; KEY tap = next page, BOOT = back.
# Not in the BOOT cycle. Add a line here whenever a feature is added, so nothing gets forgotten.
import dashboard, font5, room

SECTIONS = (
    ('screens: say "gee gee, show me ..."', (
        "plan: tasks, projects, calendar",
        "pal: the crab. key tap = fresh limits",
        "limits: ai usage. key tap = refresh",
        "today: weather + clock. key tap = refresh",
        "game: key tap = jump",
        "radar: planes nearby. key tap = refresh",
        "music: spotify. key tap = play/pause",
        "my flight: only while tracking a flight",
    )),
    ("talking", (
        'say "gee gee" or hold key, then ask',
        "anything: news, facts, sums, the web",
        'reply within 6 s, no "gee gee" needed',
        '"forget that" / "start over"',
        '"louder" / "quieter" / "volume 5"',
        '"remember i like ..." / "forget my ..."',
        '"what does claude need?" = latest alert',
        '"menu" / "what can you do?" = this list',
    )),
    ("plan", (
        '"remind me to call the bank"',
        '"mark call the bank done" / "remove ..."',
        '"add ezwrite to my projects"',
        '"move ezwrite to testing"',
        '"expand my tasks" (or projects, calendar)',
        '"what\'s on my calendar tomorrow?"',
    )),
    ("timer + music", (
        '"25 minute focus timer" / "5 min break"',
        "timer: key = pause, boot = cancel",
        '"play something chill" / "play <song>"',
        '"pause" / "skip" / "previous song"',
    )),
    ("flights", (
        '"track ba36": map, take-off + landing',
        '"what planes are overhead?"',
        '"show flights over heathrow"',
        '"zoom the radar out to 100 km"',
    )),
    ("speaks up by itself", (
        "claude or codex needs you",
        "an ai limit passes 90%",
        "rain within the hour",
        "morning hello; 10 min before meetings",
        "weekdays 10:30am: offers deep work",
        "your tracked flight takes off / lands",
        "whatsapp messages pop up (iphone bt)",
        "asleep and quiet 10pm-8am",
    )),
    ("buttons", (
        "boot: next screen, or back",
        "key tap: the screen's action (above)",
        "key hold: talk",
        "key on an alert: dismiss it",
    )),
    ("phone: deskpal.local", (
        "screens, volume, timer, music",
        "tasks, projects, calendar links",
        "track a flight, location, wi-fi",
        "connect claude/codex/grok + api keys",
        "memories, dismiss alerts, spotify login",
    )),
)

TOP, ROW, BOTTOM = 30, 15, 282     # rows from TOP, ROW px each, clear of the hint line at the bottom
PER_PAGE = (BOTTOM - TOP) // ROW

def _pages():
    """Rows ("head" or "item", text) split into pages. A section starts a new page if it won't fit on
    this one; one too long for any page carries on onto the next under its heading again."""
    pages, page = [], []
    for head, items in SECTIONS:
        if page and len(page) + 1 + len(items) > PER_PAGE:
            pages.append(page)
            page = []
        page.append(("head", head))
        for item in items:
            if len(page) == PER_PAGE:
                pages.append(page)
                page = [("head", head + " (cont.)")]
            page.append(("item", item))
    return pages + [page]

PAGES = _pages()
page = 0
_shown = None

def enter():
    global page, _shown
    page, _shown = 0, None

def next_page():
    global page, _shown
    page, _shown = (page + 1) % len(PAGES), None

def frame():
    """Call often while the screen shows: redraws on a new page or minute (the header clock)."""
    global _shown
    lt = room.local_time()
    key = (page, lt and lt[4])
    if key != _shown:
        _shown = key
        draw()

def draw():
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    dashboard.header(d, "menu", "page %d/%d" % (page + 1, len(PAGES)))
    y = TOP
    for kind, text in PAGES[page]:
        if kind == "head":
            font5.text(c, text, 10, y + 3)
        else:
            d.text(text, 14, y, 1)
        y += ROW
    d.line(0, BOTTOM + 2, 400, BOTTOM + 2, 1)
    font5.text(c, "key tap: next page   boot: back   hold key: talk", 10, BOTTOM + 6)
    d.show()
