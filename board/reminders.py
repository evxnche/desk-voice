# Reminders: "remind me to reset my Codex limits in half an hour" / "at 3pm". Kept in reminders.json
# (they survive a restart) as clock times, and the Pal says each one when it's due (companion.py).
import json, time, binascii

PATH = "reminders.json"
MAX = 10

def _synced():
    return time.localtime()[0] >= 2025

def _load():
    try:
        with open(PATH) as f:
            saved = json.load(f)
        return [r for r in saved if isinstance(r, dict) and r.get("text") and isinstance(r.get("at"), int)]
    except (OSError, ValueError, TypeError):
        return []

def _save(items):
    with open(PATH, "w") as f:
        json.dump(items, f)

def add(text, minutes):
    """A reminder `minutes` from now. False until the clock is set, or when the list is full."""
    text = " ".join(str(text or "").split())[:80]
    try:
        minutes = max(1, min(7 * 24 * 60, round(float(minutes))))
    except (TypeError, ValueError):
        return False
    items = _load()
    if not text or not _synced() or len(items) >= MAX:
        return False
    items.append({"text": text, "at": int(time.time()) + minutes * 60})
    _save(items)
    return True

def cancel(text=None):
    """Cancel the reminder with this text (any case), or all of them."""
    items = _load()
    keep = [r for r in items if text and r["text"].lower() != str(text).strip().lower()]
    _save(keep)
    return len(keep) < len(items)

def due():
    """Texts of the reminders that are due, taken off the list."""
    if not _synced():
        return []
    items, now = _load(), int(time.time())
    ready = [r["text"] for r in items if r["at"] <= now]
    if ready:
        _save([r for r in items if r["at"] > now])
    return ready

def headers():
    """X-Reminders for voice: what's set and in how many minutes ("what reminders do I have?")."""
    now = int(time.time())
    items = [{"text": r["text"], "in_min": max(0, (r["at"] - now) // 60)} for r in _load()]
    return {"X-Reminders": binascii.b2a_base64(json.dumps(items).encode()).decode().strip()} if items else {}
