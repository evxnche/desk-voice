"""Small, explicit facts the Pal may remember between restarts."""
import json
import os
import errno

PATH = "memories.json"
MAX_MEMORIES = 12
MAX_LENGTH = 140


def _clean(text):
    return " ".join(str(text or "").split())[:MAX_LENGTH].strip()


def list_all():
    saved = None
    for path in (PATH, PATH + ".bak"):
        try:
            with open(path) as source:
                saved = json.load(source)
            break
        except (OSError, ValueError, TypeError):
            pass
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
    temporary = PATH + ".tmp"
    backup = PATH + ".bak"
    try:
        with open(temporary, "w") as target:
            json.dump(entries, target)
        with open(temporary) as source:
            if json.load(source) != entries:
                raise ValueError("memory write did not validate")
        try:
            os.rename(temporary, PATH)
        except OSError as error:
            if not error.args or error.args[0] != errno.EEXIST:
                raise
            try:
                os.remove(backup)
            except OSError:
                pass
            os.rename(PATH, backup)
            try:
                os.rename(temporary, PATH)
            except OSError:
                os.rename(backup, PATH)
                raise
        try:
            os.remove(backup)
        except OSError:
            pass
        return True
    except (OSError, ValueError, TypeError):
        try:
            os.remove(temporary)
        except OSError:
            pass
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
