"""Private task sync. Network workers publish results; only the main loop changes plan."""
import json, os, time, binascii, _thread

CONFIG_FILE = "noty-sync.json"
STATE_FILE = "noty-sync-state.json"
CA_FILE = "noty-sync-ca.der"
MAX_BYTES = 128 * 1024
MAX_RECORDS = 512
POLL_MS = 30000
DEBOUNCE_MS = 2000
FIELDS = ("noteId", "listTitle", "text", "completed", "position", "deleted")
KEYS = ("id",) + FIELDS + ("version",)


def _uuid():
    data = bytearray(os.urandom(16))
    data[6] = (data[6] & 15) | 64
    data[8] = (data[8] & 63) | 128
    value = binascii.hexlify(data).decode()
    return "%s-%s-%s-%s-%s" % (value[:8], value[8:12], value[12:16], value[16:20], value[20:])


def _identifier(value):
    return (isinstance(value, str) and len(value) == 36
            and all(value[i] == "-" for i in (8, 13, 18, 23))
            and all(c.lower() in "0123456789abcdef" for c in value.replace("-", ""))
            and len(value.replace("-", "")) == 32)


def _units(value):
    return sum(2 if ord(c) > 65535 else 1 for c in value)


def _record(value, remote=False):
    if not isinstance(value, dict) or len(value) != len(KEYS) or any(k not in value for k in KEYS):
        raise ValueError("Invalid task fields")
    if not _identifier(value["id"]) or not _identifier(value["noteId"]):
        raise ValueError("Invalid task identity")
    text, title = value["text"], value["listTitle"]
    if not isinstance(text, str) or not text.strip() or _units(text) > 2000 or "\r" in text or "\n" in text:
        raise ValueError("Invalid task text")
    if (not isinstance(title, str) or not title.strip() or _units(title) > 120
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in title)):
        raise ValueError("Invalid list title")
    if type(value["completed"]) is not bool or type(value["deleted"]) is not bool:
        raise ValueError("Invalid task flags")
    position, version = value["position"], value["version"]
    if type(position) not in (int, float) or position != position or abs(position) == float("inf"):
        raise ValueError("Invalid task position")
    if type(version) is not int or not (1 if remote else 0) <= version <= 9007199254740991:
        raise ValueError("Invalid task version")
    return dict(value)


def _same(field, left, right):
    return left.lower() == right.lower() if field == "noteId" else left == right


def _equal(left, right):
    return all(_same(field, left[field], right[field]) for field in FIELDS)


def _entry(value):
    if not isinstance(value, dict) or set(value) != {"task", "base"}:
        raise ValueError("Invalid state entry")
    task = _record(value["task"])
    base = None if value["base"] is None else _record(value["base"], True)
    if base is not None and base["id"].lower() != task["id"].lower():
        raise ValueError("Mismatched state identity")
    return {"task": task, "base": base}


def _changes(values):
    if not isinstance(values, list) or len(values) > 250:
        raise ValueError("Invalid pending request")
    result, seen = [], set()
    for value in values:
        entry = _entry(value)
        key = entry["task"]["id"].lower()
        if key in seen:
            raise ValueError("Duplicate pending identity")
        seen.add(key)
        result.append(entry)
    return result


def _board_tasks(values):
    if not isinstance(values, list):
        raise ValueError("Invalid board tasks")
    result, seen = [], set()
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("t"), str) or type(item.get("done")) is not bool:
            raise ValueError("Invalid board task")
        if item.get("id") is not None:
            if not _identifier(item["id"]) or not _identifier(item.get("noteId")):
                raise ValueError("Invalid board identity")
            key = item["id"].lower()
            if key in seen:
                raise ValueError("Duplicate board identity")
            seen.add(key)
        result.append(dict(item))
    return result


class Ledger:
    """Desired records and unchanged server bases; no hardware or I/O dependencies."""
    def __init__(self, saved=None):
        self.device_note_id = _uuid() if saved is None else saved.get("device_note_id") if isinstance(saved, dict) else None
        self.entries, self.sent, self.conflicts = {}, None, 0
        if saved is None:
            return
        if not isinstance(saved, dict):
            raise ValueError("Invalid sync state")
        if saved.get("schema") != 1 or not _identifier(self.device_note_id) or not isinstance(saved.get("entries"), dict):
            raise ValueError("Invalid sync state")
        if len(saved["entries"]) > MAX_RECORDS:
            raise ValueError("Sync state capacity reached")
        for key, value in saved["entries"].items():
            entry = _entry(value)
            if key != entry["task"]["id"].lower():
                raise ValueError("Invalid state key")
            self.entries[key] = entry
        self.sent = None if saved.get("sent") is None else _changes(saved["sent"])
        if self.sent and any(c["task"]["id"].lower() not in self.entries for c in self.sent):
            raise ValueError("Pending task missing from state")
        self.conflicts = saved.get("conflicts", 0)
        if type(self.conflicts) is not int or self.conflicts < 0:
            raise ValueError("Invalid conflict count")
        if saved.get("pending_plan") is not None:
            _board_tasks(saved["pending_plan"])
            _board_tasks(saved.get("pending_before"))

    def data(self):
        return {"schema": 1, "device_note_id": self.device_note_id,
                "entries": {k: _entry(v) for k, v in self.entries.items()},
                "sent": None if self.sent is None else _changes(self.sent), "conflicts": self.conflicts}

    def reconcile(self, local):
        candidate = _board_tasks(local)
        entries = {k: _entry(v) for k, v in self.entries.items()}
        seen = set()
        for position, item in enumerate(candidate):
            key = item.get("id", "").lower()
            entry = entries.get(key)
            if not key or entry and entry["task"]["deleted"]:
                item["id"] = _uuid()
                item["noteId"] = self.device_note_id
                item["listTitle"] = "Desk Pal"
                key, entry = item["id"].lower(), None
            if entry is None:
                desired = {"id": item["id"], "noteId": item["noteId"],
                           "listTitle": item.get("listTitle", "Desk Pal"), "text": item["t"],
                           "completed": item["done"], "position": position, "deleted": False, "version": 0}
                entry = {"task": desired, "base": None}
            else:
                desired = dict(entry["task"])
                desired["text"], desired["completed"] = item["t"], item["done"]
                item["noteId"], item["listTitle"] = desired["noteId"], desired["listTitle"]
                entry["task"] = desired
            _record(desired)
            entries[key] = entry
            seen.add(key)
        for key, entry in entries.items():
            if key not in seen and not entry["task"]["deleted"]:
                entry["task"]["deleted"] = True
        if len(entries) > MAX_RECORDS:
            raise ValueError("Sync state capacity reached")
        self.entries = entries
        return candidate

    def prepare(self):
        # Keep the exact first POST across lost acknowledgements and restarts.
        if self.sent is None:
            batch, size = [], len(json.dumps({"changes": []}).encode())
            for entry in self.entries.values():
                if entry["base"] is not None and _equal(entry["task"], entry["base"]):
                    continue
                copied = _entry(entry)
                added = len(json.dumps(copied).encode()) + (2 if batch else 0)
                if len(batch) == 250 or size + added > MAX_BYTES:
                    break
                batch.append(copied)
                size += added
            if not batch and any(e["base"] is None or not _equal(e["task"], e["base"]) for e in self.entries.values()):
                raise ValueError("Individual task exceeds request capacity")
            self.sent = batch
        return _changes(self.sent)

    def visible(self, entries=None):
        entries = self.entries if entries is None else entries
        rows = []
        for entry in entries.values():
            task = entry["task"]
            if task["deleted"]:
                continue
            rows.append(task)
        own_list = self.device_note_id.lower()
        rows.sort(key=lambda t: (t["noteId"].lower() != own_list, t["noteId"].lower(), t["position"], t["id"].lower()))
        return [{"t": t["text"], "done": t["completed"], "id": t["id"],
                 "noteId": t["noteId"], "listTitle": t["listTitle"]} for t in rows]

    def receive(self, response, sent=None, capacity=None):
        if not isinstance(response, dict) or not isinstance(response.get("tasks"), list) or not isinstance(response.get("conflicts"), list):
            raise ValueError("Invalid sync response")
        remote, conflicts = {}, set()
        for value in response["tasks"]:
            task = _record(value, True)
            key = task["id"].lower()
            if key in remote:
                raise ValueError("Duplicate remote identity")
            remote[key] = task
        if len(remote) > MAX_RECORDS:
            raise ValueError("Sync state capacity reached")
        for item in response["conflicts"]:
            if not isinstance(item, dict) or not _identifier(item.get("id")):
                raise ValueError("Invalid conflict")
            task = _record(item.get("task"), True)
            key = task["id"].lower()
            if item["id"].lower() != key or key not in remote or task != remote[key]:
                raise ValueError("Invalid conflict identity")
            conflicts.add(key)
        sent = self.sent or [] if sent is None else _changes(sent)
        snapshots = {entry["task"]["id"].lower(): entry for entry in sent}
        if conflicts - set(snapshots):
            raise ValueError("Unexpected conflict")
        entries = {k: _entry(v) for k, v in self.entries.items()}
        recovered = 0
        for key, entry in entries.items():
            if entry["base"] is not None and key not in remote:
                raise ValueError("Server omitted acknowledged task")
        for key, server in remote.items():
            existing = entries.get(key)
            if existing is None:
                entries[key] = {"task": dict(server), "base": dict(server)}
                continue
            local, base = existing["task"], existing["base"]
            if base is not None and server["version"] < base["version"]:
                raise ValueError("Remote version moved backwards")
            snapshot = snapshots.get(key)
            reference = snapshot["task"] if snapshot and key not in conflicts else base
            changed = list(FIELDS) if reference is None else [f for f in FIELDS if not _same(f, local[f], reference[f])]
            collision = key in conflicts or (reference is None and not _equal(local, server))
            if reference is not None:
                collision = collision or any(not _same(f, server[f], reference[f]) and not _same(f, server[f], local[f]) for f in changed)
            if server["deleted"] and not local["deleted"] and changed:
                collision = True
            desired = dict(server)
            if collision:
                # Retain the remote identity; conflicting local work gets a fresh identity.
                if not local["deleted"] and not _equal(local, server):
                    preserved = dict(local)
                    preserved["id"], preserved["version"] = _uuid(), 0
                    entries[preserved["id"].lower()] = {"task": preserved, "base": None}
                    recovered += 1
            else:
                for field in changed:
                    desired[field] = local[field]
            entries[key] = {"task": desired, "base": dict(server)}
        candidate = self.visible(entries)
        if len(entries) > MAX_RECORDS or capacity is not None and len(candidate) > capacity:
            raise ValueError("Task capacity reached; all existing tasks retained")
        self.entries, self.sent = entries, None
        self.conflicts += recovered
        return candidate


def _now():
    return time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.monotonic() * 1000)


def _diff(left, right):
    return time.ticks_diff(left, right) if hasattr(time, "ticks_diff") else left - right


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError as error:
        if error.args and error.args[0] == 2:
            return False
        raise


def _load_state():
    found = False
    for path in (STATE_FILE, STATE_FILE + ".tmp", STATE_FILE + ".bak"):
        if not _exists(path):
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
        raise ValueError("Sync state is corrupt; restore its backup")
    return None


def _save_state(saved):
    Ledger(saved)
    temporary, backup = STATE_FILE + ".tmp", STATE_FILE + ".bak"
    with open(temporary, "w") as target:
        json.dump(saved, target)
        target.flush()
    with open(temporary) as source:
        Ledger(json.load(source))
    if _exists(STATE_FILE):
        if _exists(backup):
            os.remove(backup)
        os.rename(STATE_FILE, backup)
    try:
        os.rename(temporary, STATE_FILE)
    except OSError:
        if _exists(backup) and not _exists(STATE_FILE):
            os.rename(backup, STATE_FILE)
        raise


def _endpoint(url):
    if not isinstance(url, str) or not url.startswith("https://") or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("Sync requires HTTPS")
    parts = url[8:].split("/", 1)
    host, path = parts[0], "/" + parts[1] if len(parts) == 2 else "/api/sync"
    if not host or any(c in host for c in "@:#?\\") or any(c in path for c in "?#\\"):
        raise ValueError("Invalid sync endpoint")
    return host, path


def _config(saved):
    if not isinstance(saved, dict) or type(saved.get("enabled", False)) is not bool:
        raise ValueError("Invalid sync settings")
    if not saved.get("enabled", False):
        return None
    _endpoint(saved.get("url"))
    token = saved.get("token")
    if not isinstance(token, str) or len(token) < 32 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("Invalid private sync key")
    return {"url": saved["url"], "token": token, "ca_file": saved.get("ca_file", CA_FILE)}


_ledger = None
_settings = None
_plan = None
_busy = False
_result = None
_applying = False
_dirty = False
_blocked = False
_changed_at = 0
_last_attempt = None
_error = "Sync disabled"
_last_success = None


def _commit(ledger, candidate):
    global _applying, _ledger
    saved = ledger.data()
    if candidate != _plan.tasks:
        saved["pending_plan"] = _board_tasks(candidate)
        saved["pending_before"] = _board_tasks(_plan.tasks)
        _save_state(saved)
        _applying = True
        try:
            if not _plan.apply_tasks(candidate):
                raise OSError("Cannot persist board tasks")
        finally:
            _applying = False
    _save_state(ledger.data())
    _ledger = ledger


def start():
    """Explicit startup, after plan is loaded. Missing/corrupt data never resets tasks."""
    global _settings, _plan, _ledger, _error, _blocked, _dirty
    if _ledger is not None:
        return not _blocked
    try:
        if not _exists(CONFIG_FILE):
            return False
        with open(CONFIG_FILE) as source:
            _settings = _config(json.load(source))
        if _settings is None:
            return False
        import plan
        _plan = plan
        if getattr(plan, "storage_error", ""):
            raise ValueError("Board task state needs recovery")
        saved = _load_state()
        if saved is None and any(item.get("id") for item in plan.tasks):
            raise ValueError("Sync state missing for paired board tasks")
        ledger = Ledger(saved)
        if saved is not None and saved.get("pending_plan") is not None:
            if plan.tasks != saved["pending_plan"] and plan.tasks != saved["pending_before"]:
                raise ValueError("Board changed after interrupted sync; retain current tasks")
            if not plan.apply_tasks(saved["pending_plan"]):
                raise OSError("Cannot recover board task state")
        candidate = ledger.reconcile(plan.tasks)
        _commit(ledger, candidate)
        _error, _blocked, _dirty = "", False, False
        return True
    except Exception:
        _blocked, _error = True, "Sync state/settings need recovery; tasks retained"
        return False


def changed():
    global _dirty, _changed_at
    if not _applying:
        _dirty, _changed_at = True, _now()


def status():
    if _error:
        return _error
    if _busy:
        return "Syncing tasks"
    if _ledger is None:
        return "Sync disabled"
    pending = sum(1 for e in _ledger.entries.values() if e["base"] is None or not _equal(e["task"], e["base"]))
    if _dirty or pending:
        return "Task changes waiting to sync"
    return "Tasks up to date"


def info():
    pending = sum(1 for e in _ledger.entries.values()
                  if e["base"] is None or not _equal(e["task"], e["base"])) if _ledger is not None else 0
    return {"enabled": _settings is not None, "status": status(), "busy": _busy,
            "last_success_ms": _last_success,
            "tasks": len(_plan.tasks) if _plan is not None else 0,
            "pending": pending, "error": _error,
            "preserved_conflicts": _ledger.conflicts if _ledger is not None else 0}


def device_note_id():
    """The original board list identity, for the selected-note startup fallback."""
    return _ledger.device_note_id if _ledger is not None else None


def pending_tasks():
    """Read-only desired task changes for overlaying the document projection."""
    if _ledger is None:
        return []
    return [dict(entry["task"]) for entry in _ledger.entries.values()
            if entry["base"] is None or not _equal(entry["task"], entry["base"])]


def refresh_now():
    """Nudge a task read after a document with new task identities arrives."""
    global _last_attempt
    _last_attempt = None


def new_task(text, note_id=None, title="Desk Pal"):
    """Build a locally created task for the explicitly selected board note."""
    target = note_id or device_note_id()
    if not _identifier(target):
        return {"t": text, "done": False}
    return {"t": text, "done": False, "id": _uuid(), "noteId": target, "listTitle": title}


def _worker(settings, sent):
    global _result
    try:
        _result = {"response": _request(settings, sent), "sent": sent}
    except Exception:
        # Never expose credentials, full URLs, or task text in network errors.
        _result = {"error": "Task sync unavailable; retrying", "sent": sent}


def tick(connect):
    global _busy, _result, _dirty, _error, _last_attempt, _last_success, _blocked
    if _ledger is None or _settings is None or _blocked:
        return
    now = _now()
    if _result is not None:
        result, _result, _busy = _result, None, False
        if "error" in result:
            _error = result["error"]
        else:
            try:
                staged = Ledger(_ledger.data())
                staged.reconcile(_plan.tasks)
                candidate = staged.receive(result["response"], result["sent"], MAX_RECORDS)
                _commit(staged, candidate)
                _dirty, _error, _last_success = False, "", now
            except ValueError:
                _error = "Task sync response/capacity needs attention; tasks retained"
            except Exception:
                _error, _blocked = "Sync state needs recovery; tasks retained", True
    if _blocked:
        return
    if _dirty:
        try:
            staged = Ledger(_ledger.data())
            candidate = staged.reconcile(_plan.tasks)
            _commit(staged, candidate)
            _dirty = False
        except Exception:
            _error, _blocked = "Sync state needs recovery; tasks retained", True
            return
        if _diff(now, _changed_at) < DEBOUNCE_MS:
            return
    local_due = (_last_attempt is not None and _diff(_changed_at, _last_attempt) > 0
                 and _diff(now, _changed_at) >= DEBOUNCE_MS)
    if _busy or _last_attempt is not None and _diff(now, _last_attempt) < POLL_MS and not local_due:
        return
    if _last_attempt is not None and _diff(now, _last_attempt) < DEBOUNCE_MS:
        return
    if not connect():
        return
    try:
        staged = Ledger(_ledger.data())
        sent = staged.prepare()
        _save_state(staged.data())
        _ledger.sent = staged.sent
        _thread.stack_size(20 * 1024)
        _busy, _last_attempt = True, now
        _thread.start_new_thread(_worker, (dict(_settings), sent))
    except Exception:
        _busy, _last_attempt, _error = False, now, "Task sync could not start; retrying"


def _line(stream, limit=4096):
    result = bytearray()
    while len(result) < limit:
        value = stream.read(1)
        if not value:
            raise ValueError("Incomplete HTTP headers")
        result.extend(value)
        if value == b"\n":
            return bytes(result)
    raise ValueError("HTTP line too large")


def _read_exact(stream, length):
    result = bytearray()
    while len(result) < length:
        chunk = stream.read(min(1024, length - len(result)))
        if not chunk:
            raise ValueError("Incomplete task response")
        result.extend(chunk)
    return bytes(result)


def _read_body(stream, headers):
    if headers.get("transfer-encoding", "").lower() == "chunked":
        result = bytearray()
        while True:
            length = int(_line(stream, 128).split(b";", 1)[0], 16)
            if length < 0 or len(result) + length > MAX_BYTES:
                raise ValueError("Task response too large")
            if length == 0:
                total = 0
                while True:
                    line = _line(stream)
                    total += len(line)
                    if total > 16384:
                        raise ValueError("HTTP trailers too large")
                    if line == b"\r\n":
                        return bytes(result)
            result.extend(_read_exact(stream, length))
            if _read_exact(stream, 2) != b"\r\n":
                raise ValueError("Invalid HTTP chunk")
    if headers.get("transfer-encoding"):
        raise ValueError("Unsupported HTTP encoding")
    if "content-length" not in headers:
        raise ValueError("Task response needs a bounded length")
    length = int(headers["content-length"])
    if not 0 <= length <= MAX_BYTES:
        raise ValueError("Task response too large")
    return _read_exact(stream, length)


class _Budget:
    """A 15-second total I/O budget, including servers which send very slowly."""
    def __init__(self, stream, socket, started):
        self.stream, self.socket, self.started = stream, socket, started

    def _remaining(self):
        remaining = 15000 - _diff(_now(), self.started)
        if remaining <= 0:
            raise OSError("Task request timed out")
        self.socket.settimeout(remaining / 1000)

    def read(self, length):
        self._remaining()
        return self.stream.read(length)

    def write(self, data):
        self._remaining()
        return self.stream.write(data)

    def flush(self):
        self._remaining()
        if hasattr(self.stream, "flush"):
            self.stream.flush()

    def close(self):
        self.stream.close()


def _request(settings, sent):
    """Verified TLS; no redirects. Existing MicroPython requests disables verification."""
    import socket, ssl
    started = _now()
    host, path = _endpoint(settings["url"])
    token = settings["token"]
    method = "POST" if sent else "GET"
    body = json.dumps({"changes": sent}).encode() if sent else b""
    if len(body) > MAX_BYTES:
        raise ValueError("Task request too large")
    with open(settings.get("ca_file", CA_FILE), "rb") as source:
        certificate = source.read(16385)
    if not certificate or len(certificate) > 16384:
        raise ValueError("Invalid task sync CA")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cadata=certificate)
    address = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)[0]
    raw, stream, secured = None, None, None
    try:
        raw = socket.socket(address[0], socket.SOCK_STREAM, address[2])
        raw.settimeout(15)
        raw.connect(address[-1])
        secured = context.wrap_socket(raw, server_hostname=host)
        stream = secured.makefile("rwb") if hasattr(secured, "makefile") else secured
        stream = _Budget(stream, raw, started)
        header = ("%s %s HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\n"
                  "Accept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n"
                  "Content-Type: application/json\r\nContent-Length: %d\r\n\r\n") % (method, path, host, token, len(body))
        data = header.encode() + body
        offset = 0
        while offset < len(data):
            wrote = stream.write(data[offset:])
            if not wrote:
                raise OSError("Task request write failed")
            offset += wrote
        if hasattr(stream, "flush"):
            stream.flush()
        status_line = _line(stream).split(b" ", 2)
        if len(status_line) < 2 or int(status_line[1]) != 200:
            raise ValueError("Task HTTP request failed")
        headers, size = {}, 0
        while True:
            line = _line(stream)
            size += len(line)
            if size > 16384:
                raise ValueError("HTTP headers too large")
            if line == b"\r\n":
                break
            key, value = line.decode().split(":", 1)
            key = key.strip().lower()
            if key in headers:
                raise ValueError("Duplicate HTTP header")
            headers[key] = value.strip()
        if headers.get("content-encoding", "identity") != "identity":
            raise ValueError("Unsupported task response encoding")
        return json.loads(_read_body(stream, headers).decode())
    finally:
        for handle in (stream, secured, raw):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
