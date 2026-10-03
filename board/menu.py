# Menu screen: everything Desk Pal can do, and how to get at it, as tables over a few pages. Opened by
# voice ("gee gee, menu", "what can you do?") or from deskpal.local; KEY tap = next page, BOOT = back.
# Not in the BOOT cycle. Add a row here whenever a feature is added, so nothing gets forgotten.
import dashboard, font5, room, plan

# Each table: column headings with their widths in px (they add up to the 392 px table), then rows.
# Text too long for its cell wraps onto more lines.
TABLES = (
    ((("screen", 80), ("shows", 208), ("key tap", 104)), (
        ("plan", "tasks, projects, calendar", "-"),
        ("pal", "the crab", "fresh limits"),
        ("limits", "ai usage", "refresh"),
        ("today", "weather + clock", "refresh"),
        ("game", "pixel runner", "jump"),
        ("radar", "planes nearby", "refresh"),
        ("music", "spotify", "play/pause"),
        ("my flight", "only while tracking one", "refresh"),
        ("menu", "this list", "next page"),
    )),
    ((("voice", 104), ('say "gee gee" or hold key, then', 288)), (
        ("anything", "news, facts, sums, the web"),
        ("follow-up", 'reply within 6 s, no "gee gee"'),
        ("reset chat", '"forget that" / "start over"'),
        ("volume", '"louder" / "quieter" / "volume 5"'),
        ("memory", '"remember ..." / "forget ..."'),
        ("agent alert", '"what does claude need?"'),
        ("screens", '"show me the radar" (any screen)'),
        ("menu", '"menu" / "what can you do?"'),
        ("add task", '"remind me to call the bank"'),
        ("finish task", '"mark ... done" / "remove ..."'),
        ("add project", '"add ezwrite to my projects"'),
        ("move project", '"move ezwrite to testing"'),
        ("full screen", '"expand my tasks" (or projects, calendar)'),
        ("calendar", '"what\'s on my calendar tomorrow?"'),
        ("timer", '"25 minute focus timer" / "5 min break"'),
        ("music", '"play something chill" / "play <song>" / "pause" / "skip" / "previous song"'),
        ("track flight", '"track ba36"'),
        ("mac", '"lock my mac" / "open ezwrite"'),
        ("claude", '"what\'s claude doing?"'),
        ("radar", '"what planes are overhead?" / "show flights over heathrow" / "zoom out to 100 km"'),
        ("spanish", '"let\'s practice spanish" (15 s to reply) / "stop practicing"'),
    )),
    ((("speaks up when", 256), ("it", 136)), (
        ("claude or codex needs you", "says why"),
        ("an ai limit passes 90%", "warns you"),
        ("rain within the hour", "warns you"),
        ("it first hears you each morning", "says hello"),
        ("10 min before a meeting", "heads-up"),
        ("weekdays 10:30am", "offers deep work"),
        ("tracked flight takes off/lands", "tells you"),
        ("a whatsapp message (iphone bt)", "pops up"),
        ("10pm-8am", "asleep and quiet"),
    )),
    ((("button", 120), ("does", 272)), (
        ("boot", "next screen, or back"),
        ("key tap", "that screen's action (page 1)"),
        ("key hold", "talk"),
        ("key on alert", "dismiss it"),
        ("key on timer", "pause / resume (boot cancels)"),
    )),
    ((("deskpal.local", 120), ("on your phone", 272)), (
        ("controls", "screens, volume, timer, music"),
        ("plan", "tasks, projects, calendar links"),
        ("flights, setup", "track a flight, location, wi-fi"),
        ("accounts", "agent logins, api keys, spotify"),
        ("other", "memories, dismiss alerts"),
    )),
)

X0, TOP, BOTTOM = 4, 30, 282     # tables from TOP down to BOTTOM, clear of the hint line under it
LINE, HEAD, GAP = 13, 16, 8       # px per text line, the heading row's height, space between tables

def _cells(cols, row):
    """The row's cells as lists of lines, each wrapped to its column."""
    return [plan._wrap(text, (w - 6) // 8) for (_, w), text in zip(cols, row)]

def _height(cells):
    return LINE * max(len(c) for c in cells) + 4

def _pages():
    """Pages of blocks (cols, [cells, ...]): a table that won't fit on the rest of a page starts a new
    one, and a table too long for any page carries on onto the next under its heading row again."""
    pages, page, y = [], [], TOP
    for cols, rows in TABLES:
        cells = [_cells(cols, r) for r in rows]
        if page and y + HEAD + sum(_height(c) for c in cells) > BOTTOM:
            pages.append(page)
            page, y = [], TOP
        block = (cols, [])
        page.append(block)
        y += HEAD
        for c in cells:
            if y + _height(c) > BOTTOM:
                pages.append(page)
                block = (cols, [])
                page, y = [block], TOP + HEAD
            block[1].append(c)
            y += _height(c)
        y += GAP
    return pages + [page]

PAGES = _pages()
page = 0
_shown = None

def enter():
    global _shown
    _shown = None

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

def _table(d, cols, rows, y):
    """One table at y: a black heading row, then the rows with lines between them. Returns the y under it."""
    top, width = y, sum(w for _, w in cols)
    d.fill_rect(X0, y, width, HEAD, 1)
    x = X0
    for title, w in cols:
        d.text(title[:(w - 6) // 8], x + 4, y + 3, 0)
        x += w
    y += HEAD
    for cells in rows:
        x = X0
        for (_, w), lines in zip(cols, cells):
            for i, line in enumerate(lines):
                d.text(line, x + 4, y + 3 + i * LINE, 1)
            x += w
        y += _height(cells)
        d.line(X0, y - 1, X0 + width - 1, y - 1, 1)
    d.rect(X0, top, width, y - top, 1)
    x = X0
    for _, w in cols[:-1]:
        x += w
        d.line(x, top + HEAD, x, y - 1, 1)
    return y

def draw():
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    dashboard.header(d, "menu", "page %d/%d" % (page + 1, len(PAGES)))
    y = TOP
    for cols, rows in PAGES[page]:
        y = _table(d, cols, rows, y) + GAP
    d.line(0, BOTTOM + 2, 400, BOTTOM + 2, 1)
    font5.text(c, "key tap: next page   boot: back   hold key: talk", 10, BOTTOM + 6)
    d.show()
