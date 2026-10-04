# Plan screen: a task list, the project pipeline (idea > building > testing > shipped) and the
# calendar (schedule.py) on one page. Tasks and projects live on the board in plan.json; they're
# changed by voice ("gee gee, add call the bank to my tasks", "move ezwrite to testing") and on
# deskpal.local.
import json, binascii, os, errno
import dashboard, font5, room, schedule

FILE = "plan.json"
STAGES = ("idea", "building", "testing", "shipped")
MAX_TASKS, MAX_PROJECTS, MAX_LEN = 30, 16, 60

tasks = []        # [{"t": text, "done": bool}], oldest first
projects = []     # [{"n": name, "s": stage}]
version = 0       # bumped on every change, so the screen redraws
on_change = None  # optional task-sync notification after a successful save
view_data = None  # optional Desk Pal document projection; stored legacy caches remain intact
edit_project = None  # full-note project edits, persisted separately from plan.json
_task_edits = {}  # immediate local display until the note/task bridge catches up
SECTIONS = ("tasks", "projects", "calendar")
section = None    # one of SECTIONS: that part alone, full screen with every item's whole text

storage_error = ""
_read_failed = False
for _path in (FILE, FILE + ".bak"):
    try:
        with open(_path) as f:
            _saved = json.load(f)
        if (not isinstance(_saved, dict) or not isinstance(_saved.get("tasks"), list)
                or not isinstance(_saved.get("projects"), list)
                or any(not isinstance(t, dict) or not isinstance(t.get("t"), str)
                       or not isinstance(t.get("done"), bool) for t in _saved["tasks"])
                or any(not isinstance(p, dict) or not isinstance(p.get("n"), str)
                       or p.get("s") not in STAGES for p in _saved["projects"])):
            raise ValueError("invalid plan data")
        tasks, projects = _saved["tasks"], _saved["projects"]
        break
    except OSError as _error:
        if not _error.args or _error.args[0] != errno.ENOENT:
            _read_failed = True
    except (ValueError, TypeError):
        _read_failed = True
else:
    if _read_failed:
        storage_error = "Task storage needs recovery; no task changes will be saved."

def _save():
    global version
    if storage_error:
        raise OSError(storage_error)
    data = {"tasks": tasks, "projects": projects}
    temporary, backup = FILE + ".tmp", FILE + ".bak"
    with open(temporary, "w") as f:
        json.dump(data, f)
    with open(temporary) as f:
        if json.load(f) != data:
            raise ValueError("plan write did not validate")
    try:
        os.rename(temporary, FILE)
    except OSError as error:
        if not error.args or error.args[0] != errno.EEXIST:
            raise
        try:
            os.remove(backup)
        except OSError:
            pass
        os.rename(FILE, backup)
        try:
            os.rename(temporary, FILE)
        except OSError:
            os.rename(backup, FILE)
            raise
    version += 1
    if on_change:
        try:
            on_change()
        except Exception:
            print("plan: sync notification failed; task data is saved")

def apply_tasks(incoming):
    """Persist a synced list without truncation, eviction or project changes."""
    if incoming == tasks:
        return True
    previous = tasks[:]
    tasks[:] = incoming
    try:
        _save()
    except Exception:
        tasks[:] = previous
        raise
    return True

def _clean(text):
    return str(text or "").strip()[:MAX_LEN]

def _find(items, key, text):
    """The item whose `key` matches `text`: exactly (any case), else the first that contains it."""
    text = str(text or "").strip().lower()
    if not text:
        return None
    for item in items:
        if item[key].lower() == text:
            return item
    for item in items:
        if text in item[key].lower():
            return item
    return None

def visible_tasks():
    data = view_data() if view_data else None
    rows = data["tasks"] if data else tasks
    if not view_data:
        return rows
    if not data.get("editable", True):
        return []
    rows = [dict(row) for row in rows]
    for task_id, desired in list(_task_edits.items()):
        actual = next((row for row in rows if row.get("id") == task_id), None)
        if desired is None:
            if actual:
                rows.remove(actual)
            else:
                _task_edits.pop(task_id, None)
        elif actual and actual["t"] == desired["t"] and actual["done"] == desired["done"]:
            if not actual.get("_pending"):
                _task_edits.pop(task_id, None)
        elif actual:
            rows[rows.index(actual)] = dict(desired)
        else:
            rows.append(dict(desired))
    # New local tasks are assigned stable IDs by the legacy ledger on its next tick.
    rows.extend(dict(row) for row in tasks if not row.get("id"))
    return rows

def visible_projects():
    return view_data()["projects"] if view_data else projects

def _visible_task(text, task_id):
    shown = visible_tasks()
    selected = next((task for task in shown if task.get("id") == task_id), None) if task_id else _find(shown, "t", text)
    if selected is None:
        return None
    return next((task for task in tasks if task.get("id") == selected.get("id")), None) if selected.get("id") else selected if selected in tasks else None

def _save_tasks(previous):
    try:
        _save()
    except Exception:
        tasks[:] = previous
        raise

def add_task(text):
    text = _clean(text)
    shown = visible_tasks()
    if not text or len(shown) >= MAX_TASKS or any(t["t"].lower() == text.lower() for t in shown):
        return False
    if view_data:
        selected = view_data()
        if not selected.get("note_id") or not selected.get("editable", True):
            return False
    previous = [dict(task) for task in tasks]
    if view_data:
        import noty_sync
        selected = view_data()
        added = noty_sync.new_task(text, selected["note_id"], selected.get("note_title", "Desk Pal"))
    else:
        added = {"t": text, "done": False}
    tasks.append(added)
    _save_tasks(previous)
    if view_data and added.get("id"):
        _task_edits[added["id"]] = dict(added)
    return True

def finish_task(text, done=True, task_id=None):
    task = _visible_task(text, task_id)
    if not task:
        return False
    previous = [dict(row) for row in tasks]
    displayed = next((dict(row) for row in visible_tasks() if row.get("id") == task.get("id")), dict(task))
    task["done"] = done
    _save_tasks(previous)
    if view_data and task.get("id"):
        displayed["done"] = done
        _task_edits[task["id"]] = displayed
    return True

def remove_task(text, task_id=None):
    task = _visible_task(text, task_id)
    if not task:
        return False
    previous = [dict(row) for row in tasks]
    tasks.remove(task)
    _save_tasks(previous)
    if view_data and task.get("id"):
        _task_edits[task["id"]] = None
    return True

def clear_done():
    shown = visible_tasks()
    previous = [dict(row) for row in tasks]
    remove = [task for task in tasks if any(
        row["done"] and (row.get("id") == task.get("id") if task.get("id") else row == task) for row in shown)]
    tasks[:] = [task for task in tasks if task not in remove]
    _save_tasks(previous)
    if view_data:
        for task in remove:
            if task.get("id"):
                _task_edits[task["id"]] = None
    return True

def set_project(name, stage):
    """Add a project, or move it to another stage."""
    name, stage = str(name or "").strip(), str(stage or "idea").lower()
    stage = "shipped" if stage == "shift" else stage
    if not name or stage not in STAGES:
        return False
    if view_data:
        return bool(edit_project and edit_project(name, stage))
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
    if view_data:
        return bool(edit_project and edit_project(str(name or "").strip(), None))
    p = _find(projects, "n", name)
    if not p:
        return False
    projects.remove(p)
    _save()
    return True

def headers():
    """X-Plan for voice questions ("what's on my list?", "what am I building?")."""
    shown_tasks, shown_projects = visible_tasks(), visible_projects()
    if not shown_tasks and not shown_projects:
        return {}
    data = {"todo": [t["t"] for t in shown_tasks if not t["done"]],
            "done": [t["t"] for t in shown_tasks if t["done"]][-5:],
            "projects": [[p["n"], p["s"]] for p in shown_projects]}
    while True:
        enc = binascii.b2a_base64(json.dumps(data).encode()).decode().strip()
        if len(enc) <= 2500 or not (data["done"] or data["todo"]):
            return {"X-Plan": enc} if len(enc) <= 2500 else {}
        (data["done"] or data["todo"]).pop(0)

def state():
    """For the remote page."""
    return {"tasks": visible_tasks(), "projects": visible_projects(), "stages": STAGES}

# ---- The screen ----

_shown = None

def enter():
    global _shown
    _shown = None

def frame():
    """Call often while the screen shows: redraws when the plan, the calendar or the minute changes."""
    global _shown
    lt = room.local_time()
    key = (version, section, lt and lt[4], schedule.status(), len(schedule.upcoming),
           visible_tasks(), visible_projects())
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
        shown = visible_tasks()
        todo = [t["t"] for t in shown if not t["done"]]
        done = [t["t"] for t in shown if t["done"]]
        rows = [("head", "", "to do (%d)" % len(todo))] + [("task", False, t) for t in todo]
        if not todo:
            rows.append(("item", "", "nothing to do"))
        if done:
            rows += [("head", "", "done (%d)" % len(done))] + [("task", True, t) for t in done]
        return rows
    if section == "projects":
        rows = []
        for stage in STAGES:
            names = [p["n"] for p in visible_projects() if p["s"] == stage]
            if names:
                rows += [("head", "", "%s (%d)" % (stage, len(names)))] + [("item", "", n) for n in names]
        return rows or [("item", "", "no projects yet")]
    if not schedule.link:
        return [("item", "", "add your calendars on deskpal.local")]
    return [("head", "", r[0]) if len(r) == 1 else ("event", r[0], r[1]) for r in _event_lines(lt)]

def _draw_section(d, lt):
    c = d.canvas
    dashboard.header(d, section)
    rows, y = _section_rows(lt), 30
    for i, (kind, mark, text) in enumerate(rows):
        x = 10 if kind == "head" else 72 if kind == "event" else 22
        text = dashboard.ascii(text)
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
    todo = [t for t in visible_tasks() if not t["done"]]
    font5.text(c, "to do (%d)" % len(todo), 10, 31)
    y = 45
    for i, t in enumerate(todo):
        if i == 8 and len(todo) > 9:
            font5.text(c, "+%d more" % (len(todo) - 8), 22, y + 2)
            break
        c.rect(10, y + 1, 8, 8, 1)
        d.text(dashboard.ascii(t["t"])[:21], 22, y, 1)
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
        names = [p["n"] for p in visible_projects() if p["s"] == stage]
        font5.text(c, "%s %d" % (stage, len(names)), x + 6, 202)
        yy = 216
        for j, n in enumerate(names):
            if j == 4 and len(names) > 5:
                font5.text(c, "+%d more" % (len(names) - 4), x + 6, yy + 2)
                break
            d.text(dashboard.ascii(n)[:11], x + 6, yy, 1)
            yy += 16
    d.show()
