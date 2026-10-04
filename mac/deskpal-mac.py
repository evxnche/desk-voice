#!/usr/bin/env python3
"""Mac helper for the Desk Pal board, kept running by launchd (com.evan.deskpal-mac.plist).

- Checks in with the board every CHECK_IN_S (sooner when something changes): this Mac's address and
  what each recent Claude Code session is doing, from the turns/ files deskpal-notify.py keeps.
- Listens on PORT for the board's voice commands: POST /do?k=KEY {"action": "lock"} or
  {"action": "open", "target": "ezwrite"} (see run() for the rest). "screen" sends a screenshot to
  desk-voice's /api/look and has the board speak the answer.
- The procrastination cop: notes the app in front (and the site, in a browser) every few seconds;
  after NAG_AFTER of YouTube and the like in work hours the Pal tells you off, and at PROUD_AT on a
  focused day it says it's proud of you.

macOS asks once each to allow: Screen Recording ("what's this error?"), Accessibility (typing),
and control of System Events and the browsers (hiding windows, reading the site in front).

Lives next to notify.py in ~/.claude/deskpal and shares its key and board-ip files.
"""
import datetime, difflib, glob, json, os, random, re, socket, subprocess, tempfile, threading, time, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BOARD = "deskpal.local"
PORT = 8737
CHECK_IN_S = 60
HERE = os.path.dirname(os.path.abspath(__file__))
KEY = open(os.path.join(HERE, "key")).read().strip()
IP_CACHE = os.path.join(HERE, "board-ip")
TURNS = os.path.join(HERE, "turns")
LOOK_URL = "https://desk-voice.vercel.app/api/look"
UTF8 = dict(os.environ, LANG="en_US.UTF-8")   # launchd sets no locale, and pbcopy then mangles accents

# Things to open that aren't apps in /Applications, by name without spaces (as transcribed: "easy write").
# Any other site opens when it's said as a domain ("bbc.co.uk").
SITES = {"ezwrite": "https://ezwrite.xyz", "easywrite": "https://ezwrite.xyz",
         "youtube": "https://www.youtube.com", "twitter": "https://x.com", "x": "https://x.com",
         "gmail": "https://mail.google.com", "github": "https://github.com", "reddit": "https://www.reddit.com",
         "chatgpt": "https://chatgpt.com", "googlecalendar": "https://calendar.google.com", "vercel": "https://vercel.com"}
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
    if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", name.lower()):
        return "site", "https://" + name.lower()
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


def osascript(script):
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


def say_on_board(kind, text):
    """Have the Pal say `text`: kind "screen" (an answer), "cop" or "proud"."""
    body = json.dumps({"kind": kind, "text": text}).encode()
    req = urllib.request.Request("http://%s/mac/say?k=%s" % (board_ip(), KEY), data=body, method="POST")
    urllib.request.urlopen(req, timeout=5).read()


def look(question):
    """Screenshot the main display, ask desk-voice about it, and have the board speak the answer."""
    with tempfile.TemporaryDirectory() as tmp:
        shot = os.path.join(tmp, "screen.jpg")
        subprocess.run(["screencapture", "-x", "-m", "-t", "jpg", shot], check=True)
        subprocess.run(["sips", "-Z", "1600", "-s", "formatOptions", "70", shot], check=True, capture_output=True)
        with open(shot, "rb") as f:
            image = f.read()
    url = "%s?k=%s&q=%s" % (LOOK_URL, KEY, urllib.parse.quote(question))
    req = urllib.request.Request(url, data=image, method="POST", headers={"Content-Type": "image/jpeg"})
    text = json.load(urllib.request.urlopen(req, timeout=60))["text"]
    say_on_board("screen", text)


# Pages open as real tabs in Arc's main window (macOS's "open" puts them in a Little Arc pop-up, which
# scripts can't see), so "close that tab" can close exactly the tab this helper opened.
_opened_tab = [None]                                 # Arc id of the last tab this helper opened


def arc(script):
    return subprocess.run(["osascript", "-e", 'tell application "Arc"\n%s\nend tell' % script],
                          capture_output=True, text=True, check=True, timeout=10).stdout.strip()


def arc_tabs():
    """{id: (url, title)} for the tabs in Arc's front window."""
    out = arc('set out to ""\nrepeat with t in tabs of front window\nset out to out & (id of t as text) & '
              '(character id 9) & (URL of t) & (character id 9) & (title of t) & linefeed\nend repeat\nreturn out')
    return {r[0]: (r[1], r[2]) for r in ((line.split("\t") + ["", ""])[:3] for line in out.splitlines() if line)}


def open_page(url):
    """A new tab in Arc's front window, remembered for "close that tab"; any other browser via open."""
    try:
        before = set(arc_tabs())
        arc('tell front window to make new tab with properties {URL:"%s"}\nactivate' % url.replace('"', "%22"))
        new = set(arc_tabs()) - before
        _opened_tab[0] = new.pop() if len(new) == 1 else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):   # no Arc window, or no permission yet
        _opened_tab[0] = None
        subprocess.run(["open", url], check=True, capture_output=True)


def fits(target, url, title):
    """Does "close the YouTube tab" mean a tab showing this? (No target: any tab.)"""
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    if not target:
        return True
    site = urllib.parse.urlparse(SITES.get(squash(target), "")).hostname or ""
    return squash(target) in squash(url + title) or bool(site and site.replace("www.", "") in url)


def close_tab(target):
    """Close the tab this helper opened, else the tab you're on, and only if it's the one asked for;
    never any other tab."""
    opened = arc_tabs().get(_opened_tab[0]) if _opened_tab[0] else None
    if opened and fits(target, *opened):
        arc('close (first tab of front window whose id is "%s")' % _opened_tab[0])
        print("  closed the tab it opened:", opened[0], flush=True)
        _opened_tab[0] = None
        return
    url, title = arc("get URL of active tab of front window"), arc("get title of active tab of front window")
    if not fits(target, url, title):
        raise ValueError("neither the tab it opened nor the one in front is that")
    arc("close active tab of front window")
    print("  closed the tab in front:", url, flush=True)


def type_text(text):
    """Type into whatever is in front by pasting, then put the clipboard back as it was."""
    before = subprocess.run(["pbpaste"], capture_output=True, env=UTF8).stdout
    subprocess.run(["pbcopy"], input=text.encode(), check=True, env=UTF8)
    osascript('tell application "System Events" to keystroke "v" using command down')
    time.sleep(0.5)
    subprocess.run(["pbcopy"], input=before, env=UTF8)


def run(action, target):
    print(action, "(%d chars)" % len(target) if action in ("copy", "type", "screen") else target, flush=True)
    if action == "lock":
        # Sleeping the display locks the Mac: its screen lock is set to "immediately".
        subprocess.run(["pmset", "displaysleepnow"], check=True)
    elif action == "sleep":
        subprocess.run(["pmset", "sleepnow"], check=True)
    elif action == "hide_all":
        osascript('tell application "System Events" to set visible of every process whose visible is true '
                  'and name is not "Finder" to false')
    elif action == "volume":
        osascript("set volume output volume %d without output muted" % max(0, min(100, int(target))))
    elif action in ("mute", "unmute"):
        osascript("set volume output muted %s" % ("true" if action == "mute" else "false"))
    elif action == "copy":
        subprocess.run(["pbcopy"], input=target.encode(), check=True, env=UTF8)
    elif action == "type":
        type_text(target)
    elif action == "url":                 # search results ("open YouTube and look up Perplexity")
        if not re.fullmatch(r"https://[^\s\"']{1,500}", target):
            raise ValueError("not a web address")
        open_page(target)
    elif action == "close_tab":
        close_tab(target.strip())
    elif action == "screen":
        threading.Thread(target=look, args=(target or "What's on my screen?",), daemon=True).start()
    elif action in ("open", "close"):
        name = target.strip()
        if not re.fullmatch(r"[\w .'&+-]{1,40}", name):
            raise ValueError("bad name")
        kind, what = find(name)
        print("  ->", what, flush=True)
        if action == "open":
            if kind == "site":
                open_page(what)
            else:
                subprocess.run(["open", "-a", what], check=True, capture_output=True)
        elif kind == "site":
            close_tab(name)                   # "close YouTube" means its tab
        else:
            # Quit like Cmd-Q, so an app with unsaved work asks first.
            subprocess.run(["osascript", "-e", 'quit app "%s"' % what], check=True, capture_output=True)
    else:
        raise ValueError("unknown action")


# The procrastination cop.
DISTRACTIONS = {"youtube.com": "YouTube", "x.com": "X", "twitter.com": "Twitter", "reddit.com": "Reddit",
                "instagram.com": "Instagram", "tiktok.com": "TikTok", "netflix.com": "Netflix",
                "facebook.com": "Facebook", "twitch.tv": "Twitch"}
DISTRACTING_APPS = {}                  # app name -> what to call it, e.g. {"TV": "Apple TV"}
BROWSERS = {"Arc": 'tell application "Arc" to get URL of active tab of front window',
            "Comet": 'tell application "Comet" to get URL of active tab of front window',
            "Google Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
            "Safari": 'tell application "Safari" to get URL of front document'}
WORK_DAYS, WORK_HOURS = range(0, 5), (9, 18)   # Monday-Friday, 9am-6pm
NAG_AFTER = 15 * 60                    # this long on distractions (breaks under BREAK_OK don't count) gets a nag
BREAK_OK = 2 * 60                      # this long away from them starts the count again
AWAY_IDLE = 20 * 60                    # no mouse or keys for this long: not at the Mac
PROUD_AT = (17, 30)
PROUD_IF = (3 * 3600, 20 * 60)         # at least this much work and at most this much distraction today

NAGS = ("You've been on {site} for {m} minutes. I'm watching you. Back to work.",
        "{m} minutes of {site}. Your agents are working harder than you are right now.",
        "Hey. {site}. {m} minutes. Close it.",
        "That's {m} minutes on {site}. Claude didn't sign up to do all the work alone.",
        "{m} minutes on {site}? I'm not angry, just disappointed. Okay, I'm a bit angry.")
PROUDS = ("Great focus day: {h} hours of work and only {m} minutes of distractions. I'm proud of you.",
          "{h} hours of real work today and barely any scrolling. Nice one.",
          "Focus level today: crab-tastic. {h} hours in and hardly any distractions.")


def front_app():
    out = subprocess.run(["lsappinfo", "info", "-only", "name", subprocess.run(
        ["lsappinfo", "front"], capture_output=True, text=True).stdout.strip()], capture_output=True, text=True).stdout
    m = re.match(r'\s*"([^"]*)"', out)
    return m.group(1) if m else ""


def idle_seconds():
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(m.group(1)) / 1e9 if m else 0


def distraction():
    """What's distracting you right now ("YouTube"), or None."""
    app = front_app()
    if app in DISTRACTING_APPS:
        return DISTRACTING_APPS[app]
    if app in BROWSERS:
        try:
            url = subprocess.run(["osascript", "-e", BROWSERS[app]], capture_output=True, text=True, timeout=3).stdout
        except subprocess.TimeoutExpired:
            return None
        host = urllib.parse.urlparse(url.strip()).hostname or ""
        for domain, name in DISTRACTIONS.items():
            if host == domain or host.endswith("." + domain):
                return name
    return None


class Cop:
    def __init__(self):
        self.day, self.last = None, time.time()

    def tick(self):
        now = time.time()
        dt, self.last = min(30, now - self.last), now     # capped: the Mac may have slept in between
        today = datetime.datetime.now()
        if self.day != today.date():
            self.day, self.work, self.wasted, self.proud = today.date(), 0, 0, False
            self.streak, self.clean, self.next_nag = 0, 0, NAG_AFTER
        if today.weekday() not in WORK_DAYS or not WORK_HOURS[0] <= today.hour < WORK_HOURS[1]:
            return
        if idle_seconds() > AWAY_IDLE:
            return
        site = distraction()
        if site:
            self.streak += dt
            self.wasted += dt
            self.clean = 0
            if self.streak >= self.next_nag:
                self.next_nag += NAG_AFTER
                say_on_board("cop", random.choice(NAGS).format(site=site, m=int(self.streak // 60)))
        else:
            self.work += dt
            self.clean += dt
            if self.clean >= BREAK_OK:
                self.streak, self.next_nag = 0, NAG_AFTER
        if not self.proud and (today.hour, today.minute) >= PROUD_AT and \
                self.work >= PROUD_IF[0] and self.wasted <= PROUD_IF[1]:
            self.proud = True
            say_on_board("proud", random.choice(PROUDS).format(h=int(self.work // 3600), m=int(self.wasted // 60)))


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
            # The board already said it was done: put that right.
            what = {"open": "open %s", "close": "close %s", "url": "open that",
                    "close_tab": "tell which tab to close"}.get(cmd.get("action"), "do that")
            try:
                say_on_board("screen", "Sorry, I couldn't %s on your Mac." % (what % cmd.get("target", "") if "%s" in what else what))
            except Exception:
                pass

    def reply(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(self.address_string(), (fmt % args).split("?")[0], flush=True)   # not the key


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sent, last, cop = None, 0, Cop()
    while True:
        sessions = claude_sessions()
        if sessions != sent or time.time() - last >= CHECK_IN_S:
            check_in(sessions)                # board unreachable: tried again on the next change or minute
            sent, last = sessions, time.time()
        try:
            cop.tick()
        except Exception as e:
            print("cop:", e, flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
