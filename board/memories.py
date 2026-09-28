"""Small, explicit facts the Pal may remember between restarts."""
import json

PATH = "memories.json"
MAX_MEMORIES = 12
MAX_LENGTH = 140


def _clean(text):
    return " ".join(str(text or "").split())[:MAX_LENGTH].strip()


def list_all():
    try:
        with open(PATH) as source:
            saved = json.load(source)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(saved, list):
        return []
    entries = []
    for value in saved:
        if isinstance(value, str):
            item = _clean(value)
            if item and item.lower() not in [entry.lower() for entry in entries]:
                entries.append(item)
        if len(entries) >= MAX_MEMORIES:
            break
    return entries


def _save(entries):
    try:
        with open(PATH, "w") as target:
            json.dump(entries, target)
        return True
    except (OSError, ValueError, TypeError):
        return False


def add(text):
    item = _clean(text)
    if not item:
        return False
    entries = list_all()
    if len(entries) >= MAX_MEMORIES or item.lower() in [entry.lower() for entry in entries]:
        return False
    entries.append(item)
    return _save(entries)


def delete(index):
    entries = list_all()
    if not isinstance(index, int) or not 0 <= index < len(entries):
        return False
    del entries[index]
    return _save(entries)


def clear():
    return _save([])
