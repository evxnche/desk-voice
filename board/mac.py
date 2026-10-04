# The owner's Mac: its helper (mac/deskpal-mac.py) checks in over the LAN every minute with its address
# and what Claude Code is doing; voice commands ("lock my Mac", "open ezwrite") are passed back to it.
import time, json, socket, _thread, binascii
import secrets

FRESH_MS = 3 * 60 * 1000     # no check-in for this long: the Mac is asleep or off

DICTATE_MS = 10 * 60 * 1000   # dictation mode ends on its own after this long unused

url = ""                       # "http://192.168.1.20:8737"
_dictate_until = None
claude = []                    # [{"project", "state": "working"|"waiting"|"done", "mins", "prompt"}]
_seen = None

def check_in(info):
    global url, claude, _seen
    u = str(info.get("url") or "")
    if not u.startswith("http://"):
        return False
    url, _seen = u, time.ticks_ms()
    claude = [s for s in info.get("claude") or [] if isinstance(s, dict)][:5]
    return True

def online():
    return _seen is not None and time.ticks_diff(time.ticks_ms(), _seen) < FRESH_MS

def headers():
    """X-Mac for voice: is the Mac reachable, and what Claude Code is up to ("what's Claude doing?")."""
    if not online():
        return {}
    enc = binascii.b2a_base64(json.dumps({"claude": claude}).encode()).decode().strip()
    return {"X-Mac": enc} if len(enc) <= 2500 else {"X-Mac": "e30="}    # {} when too long: still online

def _send(body):
    try:
        host, _, port = url[7:].partition(":")
        s = socket.socket()
        s.settimeout(3)
        s.connect(socket.getaddrinfo(host, int(port or 80))[0][-1])
        s.send(b"POST /do?k=%s HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
               % (secrets.VOICE_KEY.encode(), len(body)))
        s.sendall(body)
        s.recv(64)
        s.close()
    except Exception as e:
        print("mac:", e)

def dictating():
    return _dictate_until is not None and time.ticks_diff(_dictate_until, time.ticks_ms()) > 0

def dictate(on):
    """Dictation mode on (or kept on: each typed line extends it) or off."""
    global _dictate_until
    _dictate_until = time.ticks_add(time.ticks_ms(), DICTATE_MS) if on else None

def do(action, target=""):
    """Hand one action to the Mac in the background, so a Mac that's gone quiet never holds up the board."""
    if not online():
        return False
    if action == "type":
        dictate(dictating())                  # still dictating? then for another 10 minutes
    _thread.stack_size(20 * 1024)
    _thread.start_new_thread(_send, (json.dumps({"action": action, "target": target}).encode(),))
    return True
