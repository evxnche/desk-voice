#!/usr/bin/env python3
"""Mac helper for the Desk Pal board, kept running by launchd (com.evan.deskpal-mac.plist).

- Checks in with the board every CHECK_IN_S (sooner when something changes): this Mac's address and
  what each recent Claude Code session is doing, from the turns/ files deskpal-notify.py keeps.
- Listens on PORT for the board's voice commands: POST /do?k=KEY {"action": "lock"} or
  {"action": "open", "target": "ezwrite"}.

Lives next to notify.py in ~/.claude/deskpal and shares its key and board-ip files.
"""
import difflib, glob, json, os, re, socket, subprocess, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BOARD = "deskpal.local"
PORT = 8737
CHECK_IN_S = 60
HERE = os.path.dirname(os.path.abspath(__file__))
KEY = open(os.path.join(HERE, "key")).read().strip()
IP_CACHE = os.path.join(HERE, "board-ip")
TURNS = os.path.join(HERE, "turns")

# Things to open that aren't apps in /Applications, by name without spaces (as transcribed: "easy write").
SITES = {"ezwrite": "https://ezwrite.xyz", "easywrite": "https://ezwrite.xyz"}
FORGET_AFTER = {"working": 6 * 3600, "waiting": 3 * 3600, "done": 3600}   # older sessions are left out


def board_ip(fresh=False):
    if not fresh:
        try:
            with open(IP_CACHE) as f:
                return f.read().strip()
        except OSError:
            pass
    ip = socket.gethostbyname(BOARD)
    with open(IP_CACHE, "w") as f:
        f.write(ip)
    return ip


def my_ip(board):
    """This Mac's address on the board's network (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((board, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def claude_sessions():
    """The newest few Claude Code sessions: project, state, minutes in that state, last prompt."""
    now, out = time.time(), []
    try:
        names = os.listdir(TURNS)
    except OSError:
        return []
    for name in names:
        try:
            with open(os.path.join(TURNS, name)) as f:
                t = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(t, dict) or t.get("state") not in FORGET_AFTER:
            continue
        age = now - t.get("at", 0)
        if age < FORGET_AFTER[t["state"]]:
            since = t["start"] if t["state"] == "working" else t["at"]
            out.append((t["at"], {"project": str(t.get("project", ""))[:80], "state": t["state"],
                                  "mins": int((now - since) // 60), "prompt": str(t.get("prompt", ""))[:120]}))
    return [s for _, s in sorted(out, key=lambda x: -x[0])[:5]]


def check_in(sessions):
    for fresh in (False, True):
        try:
            board = board_ip(fresh)
            body = json.dumps({"url": "http://%s:%d" % (my_ip(board), PORT), "claude": sessions}).encode()
            req = urllib.request.Request("http://%s/mac?k=%s" % (board, KEY), data=body, method="POST")
            urllib.request.urlopen(req, timeout=3).read()
            return
        except Exception:
            continue                          # the board may have a new address: look it up once more


def find(name):
    """The site URL or app a spoken name means, also when it was transcribed a bit off ("Easy Right")."""
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    apps = {}
    for path in glob.glob("/Applications/*.app") + glob.glob("/System/Applications/*.app") + \
            glob.glob(os.path.expanduser("~/Applications/*.app")):
        app = os.path.basename(path)[:-4]
        apps.setdefault(squash(app), app)
    known = {**{k: ("site", v) for k, v in SITES.items()}, **{k: ("app", v) for k, v in apps.items()}}
    close = difflib.get_close_matches(squash(name), known, n=1, cutoff=0.75)
    if not close:
        raise ValueError("nothing called that")
    return known[close[0]]


def run(action, target):
    if action == "lock":
        # Sleeping the display locks the Mac: its screen lock is set to "immediately".
        subprocess.run(["pmset", "displaysleepnow"], check=True)
    elif action == "open":
        name = target.strip()
        if not re.fullmatch(r"[\w .'&+-]{1,40}", name):
            raise ValueError("bad name")
        kind, what = find(name)
        print("open:", name, "->", what, flush=True)
        subprocess.run(["open", what] if kind == "site" else ["open", "-a", what], check=True, capture_output=True)
    else:
        raise ValueError("unknown action")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/do" or parse_qs(url.query).get("k") != [KEY]:
            return self.reply(401, {"ok": False})
        cmd = {}
        try:
            cmd = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            run(str(cmd.get("action")), str(cmd.get("target") or ""))
            self.reply(200, {"ok": True})
        except Exception as e:
            print("failed:", cmd, e, flush=True)
            self.reply(400, {"ok": False})

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args, flush=True)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sent, last = None, 0
    while True:
        sessions = claude_sessions()
        if sessions != sent or time.time() - last >= CHECK_IN_S:
            check_in(sessions)                # board unreachable: tried again on the next change or minute
            sent, last = sessions, time.time()
        time.sleep(5)


if __name__ == "__main__":
    main()
