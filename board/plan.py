# Plan screen: a task list, the project pipeline (idea > building > testing > shipped) and the
# calendar (schedule.py) on one page. Tasks and projects live on the board in plan.json; they're
# changed by voice ("gee gee, add call the bank to my tasks", "move ezwrite to testing") and on
# deskpal.local.
import json, binascii
import dashboard, font5, room, schedule

FILE = "plan.json"
STAGES = ("idea", "building", "testing", "shipped")
MAX_TASKS, MAX_PROJECTS, MAX_LEN = 30, 16, 60

tasks = []        # [{"t": text, "done": bool}], oldest first
projects = []     # [{"n": name, "s": stage}]
version = 0       # bumped on every change, so the screen redraws
SECTIONS = ("tasks", "projects", "calendar")
section = None    # one of SECTIONS: that part alone, full screen with every item's whole text

try:
    with open(FILE) as f:
        _saved = json.load(f)
    tasks, projects = _saved.get("tasks", []), _saved.get("projects", [])
except Exception:
    pass

def _save():
    global version
    version += 1
    with open(FILE, "w") as f:
        json.dump({"tasks": tasks, "projects": projects}, f)

def _clean(text):
    return " ".join(dashboard.ascii(text).split())[:MAX_LEN]

def _find(items, key, text):
    """The item whose `key` matches `text`: exactly (any case), else the first that contains it."""
    text = _clean(text).lower()
    if not text:
        return None
    for item in items:
        if item[key].lower() == text:
            return item
    for item in items:
        if text in item[key].lower():
            return item
    return None

def add_task(text):
    text = _clean(text)
    if not text or any(t["t"].lower() == text.lower() for t in tasks):
        return False
    tasks.append({"t": text, "done": False})
    while len(tasks) > MAX_TASKS:         # full: the oldest finished task goes first, else the oldest
        old = [t for t in tasks if t["done"]] or tasks
        tasks.remove(old[0])
    _save()
    return True

def finish_task(text, done=True):
    task = _find(tasks, "t", text)
    if not task:
        return False
    task["done"] = done
    _save()
    return True

def remove_task(text):
    task = _find(tasks, "t", text)
    if not task:
        return False
    tasks.remove(task)
    _save()
    return True

def clear_done():
    tasks[:] = [t for t in tasks if not t["done"]]
    _save()
    return True

def set_project(name, stage):
    """Add a project, or move it to another stage."""
    name, stage = _clean(name), str(stage or "idea").lower()
    if not name or stage not in STAGES:
        return False
    p = _find(projects, "n", name)
    if p:
        p["s"] = stage
    elif len(projects) < MAX_PROJECTS:
        projects.append({"n": name, "s": stage})
    else:
        return False
    _save()
    return True

def remove_project(name):
    p = _find(projects, "n", name)
    if not p:
        return False
    projects.remove(p)
    _save()
    return True

def headers():
    """X-Plan for voice questions ("what's on my list?", "what am I building?")."""
    if not tasks and not projects:
        return {}
    data = {"todo": [t["t"] for t in tasks if not t["done"]],
            "done": [t["t"] for t in tasks if t["done"]][-5:],
            "projects": [[p["n"], p["s"]] for p in projects]}
    while True:
        enc = binascii.b2a_base64(json.dumps(data).encode()).decode().strip()
        if len(enc) <= 2500 or not (data["done"] or data["todo"]):
            return {"X-Plan": enc} if len(enc) <= 2500 else {}
        (data["done"] or data["todo"]).pop(0)

def state():
    """For the remote page."""
    return {"tasks": tasks, "projects": projects, "stages": STAGES}

# ---- The screen ----

_shown = None

def enter():
    global _shown
    _shown = None

def frame():
    """Call often while the screen shows: redraws when the plan, the calendar or the minute changes."""
    global _shown
    lt = room.local_time()
    key = (version, section, lt and lt[4], schedule.status(), len(schedule.upcoming))
    if key != _shown:
        _shown = key
        draw(lt)

def _when(e):
    return "all day" if e.get("all_day") else room.clock(e["s"] // 60, e["s"] % 60)

def _event_lines(lt):
    """Rows for the calendar column: (day label,) or (time, title). Today's date and what's left of
    today (or "no events today"), then the next events coming up, under their day."""
    now = lt[3] * 60 + lt[4] if lt else 0
    rows = [("%s %d %s" % (room.DAYS[lt[6]], lt[2], room.MONTHS[lt[1] - 1]) if lt else "today",)]
    left = [e for e in schedule.today if e.get("all_day") or e["e"] > now]
    for e in left:
        rows.append((_when(e), e["t"]))
    if not left:
        rows.append(("", "no events today"))
    day = None
    for e in schedule.upcoming:
        if e["day"] != day:
            day = e["day"]
            rows.append((day,))
        rows.append((_when(e), e["t"]))
    return rows

def _wrap(text, width):
    """`text` as lines of at most `width` chars, broken between words (a too-long word is cut)."""
    lines, line = [], ""
    for word in text.split():
        while len(word) > width:
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:width])
            word = word[width:]
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = line + " " + word if line else word
    return lines + [line] if line else lines or [""]

def _section_rows(lt):
    """Rows for the full-screen section: ("head", "", text), ("task", done, text), ("item", "", text)
    or ("event", time, text)."""
    if section == "tasks":
        todo = [t["t"] for t in tasks if not t["done"]]
        done = [t["t"] for t in tasks if t["done"]]
        rows = [("head", "", "to do (%d)" % len(todo))] + [("task", False, t) for t in todo]
        if not todo:
            rows.append(("item", "", "nothing to do"))
        if done:
            rows += [("head", "", "done (%d)" % len(done))] + [("task", True, t) for t in done]
        return rows
    if section == "projects":
        rows = []
        for stage in STAGES:
            names = [p["n"] for p in projects if p["s"] == stage]
            if names:
                rows += [("head", "", "%s (%d)" % (stage, len(names)))] + [("item", "", n) for n in names]
        return rows or [("item", "", "no projects yet")]
    if not schedule.link:
        return [("item", "", "add your calendars on deskpal.local")]
    return [("head", "", r[0]) if len(r) == 1 else ("event", r[0], r[1]) for r in _event_lines(lt)]

def _draw_section(d, lt):
    c = d.canvas
    dashboard.header(d, section, "boot = back")
    rows, y = _section_rows(lt), 30
    for i, (kind, mark, text) in enumerate(rows):
        x = 10 if kind == "head" else 72 if kind == "event" else 22
        lines = [text] if kind == "head" else _wrap(text, (392 - x) // 8)
        left = sum(1 for r in rows[i:] if r[0] != "head")
        if y + 15 * len(lines) > (298 if left <= 1 else 283):    # keep a row for "+n more"
            if left:
                font5.text(c, "+%d more" % left, 22, y + 2)
            break
        if kind == "head":
            font5.text(c, text, 10, y + 3)
        elif kind == "task":
            c.rect(10, y + 1, 8, 8, 1)
            if mark:
                c.fill_rect(12, y + 3, 4, 4, 1)
        elif kind == "event":
            font5.text(c, mark, 10, y + 2)
        if kind != "head":
            for line in lines:
                d.text(line, x, y, 1)
                y += 15
        else:
            y += 15
    d.show()

def draw(lt=None):
    lt = lt or room.local_time()
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    if section:
        return _draw_section(d, lt)
    dashboard.header(d, "plan")

    # To do (left)
    todo = [t for t in tasks if not t["done"]]
    font5.text(c, "to do (%d)" % len(todo), 10, 31)
    y = 45
    for i, t in enumerate(todo):
        if i == 8 and len(todo) > 9:
            font5.text(c, "+%d more" % (len(todo) - 8), 22, y + 2)
            break
        c.rect(10, y + 1, 8, 8, 1)
        d.text(t["t"][:21], 22, y, 1)
        y += 16
    if not todo:
        font5.text(c, "nothing to do", 10, y)
    d.line(202, 28, 202, 190, 1)

    # Calendar (right)
    font5.text(c, "calendar", 210, 31)
    y = 45
    if not schedule.link:
        for line in ("add your calendars", "on deskpal.local"):
            font5.text(c, line, 210, y)
            y += 12
    else:
        for row in _event_lines(lt):
            if y > 178:
                break
            if len(row) == 1:
                font5.text(c, row[0], 210, y + 4)
                y += 16
                continue
            font5.text(c, row[0], 210, y + 2)
            d.text(row[1][:(392 - 262) // 8], 262, y, 1)
            y += 16
    d.line(0, 196, 400, 196, 1)

    # Pipeline (bottom): one column per stage
    for i, stage in enumerate(STAGES):
        x = i * 100
        if i:
            d.line(x, 196, x, 300, 1)
        names = [p["n"] for p in projects if p["s"] == stage]
        font5.text(c, "%s %d" % (stage, len(names)), x + 6, 202)
        yy = 216
        for j, n in enumerate(names):
            if j == 4 and len(names) > 5:
                font5.text(c, "+%d more" % (len(names) - 4), x + 6, yy + 2)
                break
            d.text(n[:11], x + 6, yy, 1)
            yy += 16
    d.show()
