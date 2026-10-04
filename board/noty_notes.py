"""Full-note cache and Desk Pal projection; networking never changes UI state directly."""
import io, json, os, hashlib, _thread
import noty_sync

STATE_FILE = "noty-notes-state.json"
STAGES = ("idea", "building", "testing", "shipped")
FIELDS = ("title", "body", "archived", "deleted")
POLL_MS = 15 * 60 * 1000   # safety net only, as noty_sync.POLL_MS
RETRY_MS = 15000           # after a failed sync: try again soon
MAX_NOTES = 128


def _document(value, remote=False):
    keys = ("id", "title", "body", "archived", "deleted", "version", "taskIds")
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Invalid note fields")
    if not noty_sync._identifier(value["id"]):
        raise ValueError("Invalid note identity")
    if (not isinstance(value["title"], str) or noty_sync._units(value["title"]) > 120
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value["title"])
            or not isinstance(value["body"], str) or noty_sync._units(value["body"]) > 65536):
        raise ValueError("Invalid note text")
    if type(value["archived"]) is not bool or type(value["deleted"]) is not bool:
        raise ValueError("Invalid note flags")
    if type(value["version"]) is not int or not (1 if remote else 0) <= value["version"] <= 9007199254740991:
        raise ValueError("Invalid note version")
    ids = value["taskIds"]
    if (not isinstance(ids, list) or len(ids) > noty_sync.MAX_RECORDS
            or any(not noty_sync._identifier(item) for item in ids)
            or len(set(item.lower() for item in ids)) != len(ids)):
        raise ValueError("Invalid note task identities")
    return dict(value, taskIds=ids[:])


def _entry(value):
    if not isinstance(value, dict) or set(value) != {"note", "base"}:
        raise ValueError("Invalid cached note")
    note = _document(value["note"])
    base = None if value["base"] is None else _document(value["base"], True)
    if base and note["id"].lower() != base["id"].lower():
        raise ValueError("Mismatched cached note identity")
    return {"note": note, "base": base}


def _equal(left, right):
    return all(left[field] == right[field] for field in FIELDS)


def _copy_note(note):
    return dict(note, taskIds=note["taskIds"][:])


def _copy_entry(entry):
    """A copy of an entry that's already been checked (checking a long note again took up to 0.9 s)."""
    return {"note": _copy_note(entry["note"]), "base": None if entry["base"] is None else _copy_note(entry["base"])}


def _digest(response):
    """Fingerprint of the parts of a reply that matter: the same again means nothing to merge or save."""
    return hashlib.sha256(json.dumps([response.get("notes"), response.get("conflicts"),
                                      response.get("deskPalId")]).encode()).digest()


def _heading(text):
    count = 0
    while count < len(text) and text[count] == "#":
        count += 1
    if not 1 <= count <= 6 or count < len(text) and not text[count].isspace():
        return None
    return count, text[count:].strip().rstrip("#").strip().lower()


def _rows(body):
    """Item spans into the unmodified body. Any heading ends the previous section."""
    section, fence = None, None
    for index, raw in enumerate(body.split("\n")):
        text = raw.strip()
        if text.startswith(("```", "~~~")):
            marker = text[:3]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence:
            continue
        header = _heading(text)
        if header:
            section = None
            if header[0] == 1:
                heading = header[1]
                section = "todo" if heading in ("todo", "to-do", "to do") else "shipped" if heading == "shift" else heading
            continue
        if not text or section not in ("todo",) + STAGES:
            continue
        if len(text) > 1 and text[0] in "-*+" and text[1].isspace():
            text = text[1:].lstrip()
        done = False
        if text.startswith(("☐", "☑")):
            done, text = text[0] == "☑", text[1:].strip()
        elif len(text) >= 3 and text[:3].lower() in ("[ ]", "[x]") and (len(text) == 3 or text[3].isspace()):
            done, text = text[1].lower() == "x", text[3:].strip()
        if text:
            yield {"line": index, "raw": raw, "text": text, "done": done, "section": section}


def project(note):
    """Display data only. Full text and other notes remain untouched in the cache."""
    tasks, projects = [], []
    if note and not note["deleted"] and not note["archived"]:
        for item in _rows(note["body"]):
            if item["section"] == "todo":
                index = len(tasks)
                task = {"t": item["text"], "done": item["done"], "noteId": note["id"], "listTitle": note["title"]}
                if index < len(note["taskIds"]):
                    task["id"] = note["taskIds"][index]
                tasks.append(task)
            else:
                projects.append({"n": item["text"], "s": item["section"]})
    return {"tasks": tasks, "projects": projects, "note_id": note["id"] if note else None,
            "note_title": note["title"] if note else "Desk Pal",
            "editable": bool(note and not note["archived"] and not note["deleted"])}


def _move_project(body, name, stage):
    rows = [row for row in _rows(body) if row["section"] in STAGES]
    exact = [row for row in rows if row["text"].lower() == name.lower()]
    matches = exact or [row for row in rows if name.lower() in row["text"].lower()]
    if len(matches) > 1 or stage is None and not matches:
        return None
    selected = matches[0] if matches else None
    if selected and selected["section"] == stage:
        return body
    lines = body.split("\n")
    newline = "\r" if "\r\n" in body else ""
    raw = selected["raw"] if selected else "- " + name + newline
    if selected:
        lines.pop(selected["line"])
    if stage is None:
        return "\n".join(lines)
    # Insert before the next heading, keeping every unrelated line byte-for-byte.
    heading, fenced = None, None
    for index, line in enumerate(lines):
        text = line.strip()
        if text.startswith(("```", "~~~")):
            marker = text[:3]
            if fenced is None:
                fenced = marker
            elif fenced == marker:
                fenced = None
            continue
        header = _heading(text)
        if fenced or not header:
            continue
        if heading is not None:
            lines.insert(index, raw)
            return "\n".join(lines)
        if header[0] == 1:
            title = header[1]
            if title == stage or stage == "shipped" and title == "shift":
                heading = index
    if heading is None:
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.extend(["# " + stage + newline, raw, ""])
    else:
        index = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
        lines.insert(index, raw)
    return "\n".join(lines)


class Ledger:
    def __init__(self, saved=None):
        self.entries, self.sent, self.conflicts, self.desk_pal_id = {}, None, {}, None
        if saved is None:
            return
        if not isinstance(saved, dict) or saved.get("schema") != 1:
            raise ValueError("Invalid note cache")
        identity = saved.get("desk_pal_id")
        if identity is not None and not noty_sync._identifier(identity):
            raise ValueError("Invalid selected note")
        self.desk_pal_id = identity
        entries = saved.get("entries")
        if not isinstance(entries, dict) or len(entries) > MAX_NOTES:
            raise ValueError("Invalid note cache entries")
        for key, value in entries.items():
            entry = _entry(value)
            if key != entry["note"]["id"].lower():
                raise ValueError("Invalid cached note key")
            self.entries[key] = entry
        sent = saved.get("sent")
        if sent is not None:
            if not isinstance(sent, list):
                raise ValueError("Invalid pending notes")
            self.sent = [_entry(value) for value in sent]
        conflicts = saved.get("conflicts", {})
        if not isinstance(conflicts, dict):
            raise ValueError("Invalid note conflicts")
        for key, value in conflicts.items():
            note = _document(value, True)
            if key != note["id"].lower() or key not in self.entries:
                raise ValueError("Invalid note conflict identity")
            self.conflicts[key] = note

    def data(self):
        # Plain copies: everything in a Ledger was checked on the way in, and _save_state checks again.
        return {"schema": 1, "desk_pal_id": self.desk_pal_id,
                "entries": {key: _copy_entry(value) for key, value in self.entries.items()},
                "sent": None if self.sent is None else [_copy_entry(value) for value in self.sent],
                "conflicts": {key: _copy_note(value) for key, value in self.conflicts.items()}}

    def copy(self):
        """A working copy to stage changes in (rebuilding one from data() rechecked every note: ~3 s)."""
        other = Ledger()
        other.desk_pal_id = self.desk_pal_id
        other.entries = {key: _copy_entry(value) for key, value in self.entries.items()}
        other.sent = None if self.sent is None else [_copy_entry(value) for value in self.sent]
        other.conflicts = {key: _copy_note(value) for key, value in self.conflicts.items()}
        return other

    def pending(self):
        """Anything to send: a request kept for a retry, or a note edited here (outside a conflict)."""
        return bool(self.sent) or any(key not in self.conflicts and (entry["base"] is None or not _equal(entry["note"], entry["base"]))
                                      for key, entry in self.entries.items())

    def get(self, note_id):
        entry = self.entries.get(str(note_id or "").lower())
        return entry["note"] if entry and not entry["note"]["deleted"] else None

    def selected(self):
        """The Desk Pal note; if Noty deleted it, the live note now titled "Desk Pal"."""
        note = self.get(self.desk_pal_id)
        if note:
            return note
        return next((entry["note"] for entry in self.entries.values()
                     if not entry["note"]["deleted"] and not entry["note"]["archived"]
                     and entry["note"]["title"].strip().lower() == "desk pal"), None)

    def view(self):
        return project(self.selected())

    def set_project(self, name, stage):
        note = self.selected()
        if not note or note["archived"] or note["id"].lower() in self.conflicts:
            return False
        name = str(name or "").strip()
        stage = "shipped" if stage == "shift" else stage
        if not name or "\n" in name or "\r" in name or stage is not None and stage not in STAGES:
            return False
        body = _move_project(note["body"], name, stage)
        if body is None or noty_sync._units(body) > 65536:
            return False
        note["body"] = body
        return True

    def prepare(self):
        if self.sent is None:
            batch, size = [], len('{"changes":[]}')
            for key, entry in self.entries.items():
                if key in self.conflicts or entry["base"] is not None and _equal(entry["note"], entry["base"]):
                    continue
                value = _entry(entry)
                added = len(json.dumps(value).encode()) + 2
                if size + added > noty_sync.MAX_BYTES:
                    break
                batch.append(value)
                size += added
            if not batch and any(key not in self.conflicts and (entry["base"] is None or not _equal(entry["note"], entry["base"]))
                                 for key, entry in self.entries.items()):
                raise ValueError("Note edit exceeds request capacity; draft retained")
            self.sent = batch
        return [_entry(value) for value in self.sent]

    def receive(self, response, sent=None):
        if (not isinstance(response, dict) or not isinstance(response.get("notes"), list)
                or not isinstance(response.get("conflicts"), list)):
            raise ValueError("Invalid notes response")
        role = response.get("deskPalId")
        if role is not None and not noty_sync._identifier(role):
            raise ValueError("Invalid Desk Pal identity")
        remote = {}
        for value in response["notes"]:
            note = _document(value, True)
            key = note["id"].lower()
            if key in remote:
                raise ValueError("Duplicate remote note")
            remote[key] = note
        if len(remote) > MAX_NOTES or role is not None and role.lower() not in remote:
            raise ValueError("Missing selected note")
        sent = self.sent or [] if sent is None else [_entry(value) for value in sent]
        snapshots = {value["note"]["id"].lower(): value for value in sent}
        failed = set()
        for conflict in response["conflicts"]:
            if not isinstance(conflict, dict) or not noty_sync._identifier(conflict.get("id")):
                raise ValueError("Invalid note conflict")
            key = conflict["id"].lower()
            note = _document(conflict.get("note"), True)
            if key not in remote or note != remote[key] or key not in snapshots:
                raise ValueError("Unexpected note conflict")
            failed.add(key)
        entries = {key: _entry(value) for key, value in self.entries.items()}
        conflicts = {key: _document(value, True) for key, value in self.conflicts.items()}
        for key, entry in entries.items():
            if entry["base"] is not None and key not in remote:
                raise ValueError("Server omitted an acknowledged note")
        for key, server in remote.items():
            previous = entries.get(key)
            if previous is None:
                entries[key] = {"note": _document(server), "base": _document(server, True)}
                continue
            local, base = previous["note"], previous["base"]
            if base is not None and server["version"] < base["version"]:
                raise ValueError("Remote note version moved backwards")
            reference = snapshots[key]["note"] if key in snapshots and key not in failed else base
            changed = list(FIELDS) if reference is None else [field for field in FIELDS if local[field] != reference[field]]
            collision = key in failed or reference is None and not _equal(local, server)
            if reference is not None:
                collision = collision or any(server[field] != reference[field] and server[field] != local[field] for field in changed)
            if server["deleted"] and not local["deleted"] and changed:
                collision = True
            if key in conflicts and not _equal(local, server):
                collision = True
            if collision:
                conflicts[key] = _document(server, True)
                # Keep the old base with the local draft; never auto-publish it over a conflict.
                continue
            desired = _document(server)
            for field in changed:
                desired[field] = local[field]
            entries[key] = {"note": desired, "base": _document(server, True)}
            conflicts.pop(key, None)
        if len(entries) > MAX_NOTES:
            raise ValueError("Note cache capacity reached")
        self.entries, self.conflicts, self.sent = entries, conflicts, None
        self.desk_pal_id = role or self.desk_pal_id


def _load_state():
    found = False
    for path in (STATE_FILE, STATE_FILE + ".tmp", STATE_FILE + ".bak"):
        if not noty_sync._exists(path):
            continue
        found = True
        try:
            with open(path) as source:
                saved = json.load(source)
            Ledger(saved)
            return saved
        except (ValueError, KeyError, TypeError):
            pass
    if found:
        raise ValueError("Note cache needs recovery")
    return None


def _save_state(saved):
    Ledger(saved)
    temporary, backup = STATE_FILE + ".tmp", STATE_FILE + ".bak"
    text = io.StringIO()
    json.dump(saved, text)                        # in memory, then one write: dumped straight to the file it
    with open(temporary, "w") as target:          # went out in hundreds of small writes
        target.write(text.getvalue())
        target.flush()
    with open(temporary) as source:
        Ledger(json.load(source))
    if noty_sync._exists(STATE_FILE):
        os.rename(STATE_FILE, backup)             # replaces the old backup: no separate remove (~0.8 s)
    try:
        os.rename(temporary, STATE_FILE)
    except OSError:
        if noty_sync._exists(backup) and not noty_sync._exists(STATE_FILE):
            os.rename(backup, STATE_FILE)
        raise


_ledger = None
_settings = None
_busy = False
_result = None
_blocked = False
_error = "Notes sync disabled"
_last_attempt = None
_last_success = None
_force = False
_version = 0
_applied = None       # _digest of the last reply merged in
viewing_id = None
page = 0
_shown = None


def start():
    global _ledger, _settings, _error, _blocked
    if _ledger is not None:
        return not _blocked
    try:
        if not noty_sync._exists(noty_sync.CONFIG_FILE):
            return False
        with open(noty_sync.CONFIG_FILE) as source:
            settings = noty_sync._config(json.load(source))
        if not settings:
            return False
        host, path = noty_sync._endpoint(settings["url"])
        settings["url"] = "https://" + host + "/api/notes"
        ledger = Ledger(_load_state())
        if ledger.desk_pal_id is None:
            ledger.desk_pal_id = noty_sync.device_note_id()
        _settings, _ledger, _error = settings, ledger, ""
        return True
    except Exception:
        _blocked, _error = True, "Notes cache needs recovery; documents retained"
        return False


def view_data():
    note = _ledger.selected() if _ledger else None
    selected = note["id"] if note else _ledger.desk_pal_id if _ledger else noty_sync.device_note_id()
    if note:
        data = project(note)
    else:
        import plan
        data = {"tasks": [dict(task) for task in plan.tasks if selected and task.get("noteId", "").lower() == selected.lower()],
                "projects": [], "note_id": selected, "note_title": "Desk Pal", "editable": bool(selected)}
    # Pending local task actions are visible while the document bridge catches up.
    if selected and data["editable"]:
        rows = data["tasks"]
        for pending in noty_sync.pending_tasks():
            if pending["noteId"].lower() != selected.lower():
                continue
            match = next((task for task in rows if task.get("id", "").lower() == pending["id"].lower()), None)
            if pending["deleted"]:
                if match:
                    rows.remove(match)
            else:
                value = {"t": pending["text"], "done": pending["completed"], "id": pending["id"],
                         "noteId": pending["noteId"], "listTitle": pending["listTitle"], "_pending": True}
                if match:
                    rows[rows.index(match)] = value
                else:
                    rows.append(value)
    return data


def edit_project(name, stage):
    global _ledger, _force, _version
    if _ledger is None or _blocked:
        return False
    staged = _ledger.copy()
    if not staged.set_project(name, stage):
        return False
    try:
        _save_state(staged.data())
    except Exception:
        return False
    _ledger, _force = staged, True
    _version += 1
    return True


def refresh_now():
    global _force
    _force = True


def refresh_if_older(ms):
    """refresh_now() unless a sync started in the last `ms` (see noty_sync.refresh_if_older)."""
    if _last_attempt is None or noty_sync._diff(noty_sync._now(), _last_attempt) >= ms:
        refresh_now()


def info():
    ledger = _ledger
    pending = sum(1 for entry in ledger.entries.values() if entry["base"] is None or not _equal(entry["note"], entry["base"])) if ledger else 0
    status = _error
    if not status:
        if ledger and ledger.conflicts:
            status = "Notes have conflicts; drafts retained"
        elif _busy:
            status = "Syncing notes"
        elif pending:
            status = "Note changes waiting to sync"
        else:
            status = "Notes up to date" if ledger and _last_success is not None else "Waiting for notes"
    titles = [{"id": entry["note"]["id"], "title": entry["note"]["title"]} for entry in ledger.entries.values()
              if not entry["note"]["deleted"]] if ledger else []
    return {"enabled": _settings is not None, "status": status, "busy": _busy, "pending": pending,
            "last_success_ms": _last_success, "conflicts": len(ledger.conflicts) if ledger else 0,
            "desk_pal_id": ledger.desk_pal_id if ledger else None, "notes": titles, "error": _error}


def _worker(settings, sent):
    global _result
    try:
        response = noty_sync._request(settings, sent)
        _result = {"response": response, "sent": sent, "digest": _digest(response)}
    except Exception:
        _result = {"error": "Note sync unavailable; retrying", "sent": sent}


def tick(connect):
    global _ledger, _busy, _result, _error, _last_attempt, _last_success, _force, _version, _applied
    if _ledger is None or _settings is None or _blocked:
        return
    now = noty_sync._now()
    if _result is not None:
        result, _result, _busy = _result, None, False
        if "error" in result:
            _error = result["error"]
        elif result.get("digest") is not None and result["digest"] == _applied and not result["sent"]:
            _last_success, _error = now, ""       # the same reply as last time, nothing sent: nothing to do
        else:
            try:
                staged = _ledger.copy()
                staged.receive(result["response"], result["sent"])
                _save_state(staged.data())
                _ledger, _last_success, _error, _applied = staged, now, "", result.get("digest")
                _version += 1
                import plan
                cached_ids = set(task.get("id", "").lower() for task in plan.tasks)
                if any(task.get("id", "").lower() not in cached_ids for task in staged.view()["tasks"]):
                    noty_sync.refresh_now()
            except Exception:
                _error = "Note sync response/storage needs attention; documents retained"
    if _busy or noty_sync.info()["busy"]:
        return
    if _last_attempt is not None:
        elapsed = noty_sync._diff(now, _last_attempt)
        if elapsed < noty_sync.DEBOUNCE_MS or not _force and elapsed < (RETRY_MS if _error else POLL_MS):
            return
    if not connect():
        return
    try:
        if _ledger.pending():
            staged = _ledger.copy()
            sent = staged.prepare()
            _save_state(staged.data())
            _ledger.sent = staged.sent
        else:
            sent = []                             # just asking for changes: nothing to keep for a retry
        # The board's MicroPython build requires a 20 KB worker stack.
        _thread.stack_size(20 * 1024)
        _busy, _last_attempt, _force = True, now, False
        _thread.start_new_thread(_worker, (dict(_settings), sent))
    except Exception:
        _busy, _last_attempt, _error = False, now, "Note sync could not start; retrying"


def show_note(note_id):
    global viewing_id, page, _shown
    if not noty_sync._identifier(note_id) or _ledger is None or _ledger.get(note_id) is None:
        refresh_now()
        return False
    viewing_id, page, _shown = note_id.lower(), 0, None
    return True


def viewer_pages(convert):
    import plan
    note = _ledger.get(viewing_id) if _ledger else None
    lines = []
    for line in (note["body"] if note else "Note no longer available").split("\n"):
        lines.extend(plan._wrap(convert(line), 47))
    return [lines[index:index + 16] for index in range(0, len(lines), 16)] or [[""]]


def next_page():
    global page, _shown
    import dashboard
    page = (page + 1) % len(viewer_pages(dashboard.ascii))
    _shown = None


def enter():
    global _shown
    _shown = None


def frame():
    global _shown
    import dashboard, font5, room
    minute = room.local_time()
    key = (_version, viewing_id, page, minute and minute[4])
    if key == _shown:
        return
    _shown = key
    note = _ledger.get(viewing_id) if _ledger else None
    pages = viewer_pages(dashboard.ascii)
    index = min(page, len(pages) - 1)
    display = dashboard.display()
    display.clear(0)
    dashboard.header(display, dashboard.ascii(note["title"] if note else "note")[:25],
                     "%d/%d" % (index + 1, len(pages)))
    for row, line in enumerate(pages[index]):
        display.text(line, 10, 31 + row * 15, 1)
    display.line(0, 282, 400, 282, 1)
    font5.text(display.canvas, "key: next page   boot: plan   hold key: talk", 10, 290)
    display.show()
