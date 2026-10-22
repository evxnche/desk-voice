#!/usr/bin/env python3
"""Agent babysitter: tell the Desk Pal board when Claude Code or Codex needs you.

Claude Code hooks (JSON on stdin, event name as argv[1]):
  prompt  UserPromptSubmit  remember when this turn started
  stop    Stop              chime "done" only if the turn ran >= LONG_TURN_S (short replies are
                            ones you're watching anyway)
  notify  Notification      chime "needs you" (permission prompts, idle input requests)
Codex `notify` (JSON as the last argv): agent-turn-complete -> "done".

Each Claude session's state (working / waiting / done, its project and your last prompt) is kept in
turns/<session> for deskpal-mac.py, which tells the board ("what's Claude doing?").

Each alert also goes to desk-voice's /api/agent mailbox, which the glasses app polls.

Always exits 0 within ~2 s: a board that's off or on another network must never slow an agent.
"""
import json, os, socket, ssl, sys, threading, time, urllib.request

BOARD = "deskpal.local"
# Your own desk-voice deployment: DESKPAL_AGENT_URL=https://<yours>.vercel.app/api/agent in the hooks' environment.
CLOUD = os.environ.get("DESKPAL_AGENT_URL", "https://desk-voice.vercel.app/api/agent")
# python.org's Python (what `python3` is here) has no CA certificates of its own; macOS ships a bundle.
TLS = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else None
LONG_TURN_S = 60
HERE = os.path.dirname(os.path.abspath(__file__))
KEY = open(os.path.join(HERE, "key")).read().strip()
IP_CACHE = os.path.join(HERE, "board-ip")
STARTS = os.path.join(HERE, "turns")


def board_ip():
    # macOS takes 2-5 s to resolve .local names (it waits on an IPv6 lookup), so remember the address.
    try:
        with open(IP_CACHE) as f:
            return f.read().strip()
    except OSError:
        pass
    ip = socket.gethostbyname(BOARD)
    with open(IP_CACHE, "w") as f:
        f.write(ip)
    return ip


def send(agent, project, kind, message):
    body = json.dumps({"agent": agent, "project": project, "kind": kind, "message": message[:240]}).encode()

    def to_board():
        # A failed send keeps the remembered address: the board may just be restarting, and deleting it
        # left the Mac unable to find the board where deskpal.local doesn't resolve. deskpal-mac.py looks
        # the board up again within a minute when its address really changed.
        try:
            url = "http://%s/agent?k=%s" % (board_ip(), KEY)
            urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST"), timeout=1.5).read()
        except Exception:
            pass

    def to_glasses():
        # The glasses app (ezmeta) polls this mailbox, so the alert reaches you away from the desk too.
        try:
            req = urllib.request.Request(CLOUD + "?k=" + KEY, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=1.8, context=TLS).read()
        except Exception:
            pass

    sends = [threading.Thread(target=f, daemon=True) for f in (to_board, to_glasses)]
    for t in sends:
        t.start()
    for t in sends:
        t.join(2)


def claude(event):
    data = json.load(sys.stdin)
    session = data.get("session_id", "unknown")
    project = os.path.basename(data.get("cwd") or os.getcwd())
    os.makedirs(STARTS, exist_ok=True)
    start_file = os.path.join(STARTS, session)
    try:
        with open(start_file) as f:
            turn = json.load(f)
        if not isinstance(turn, dict):        # older files hold just the start time
            turn = {"start": float(turn)}
    except (OSError, ValueError):
        turn = {}
    now = time.time()
    if event == "prompt":
        turn = {"start": now, "prompt": " ".join(str(data.get("prompt") or "").split())[:120]}
    if event == "stop":
        if "start" not in turn:
            return
        took = now - turn["start"]
        turn["state"] = "done"
    elif event == "notify" and turn.get("state") == "done":
        pass                                  # "waiting for your input" after a finished turn: still done
    else:
        turn["state"] = "working" if event == "prompt" else "waiting"
    turn.update(project=project, at=now)
    with open(start_file, "w") as f:
        json.dump(turn, f)
    if event == "stop" and took >= LONG_TURN_S:
        send("Claude", project, "done", "Finished after %d min." % max(1, round(took / 60)))
    elif event == "notify":
        send("Claude", project, "needs", data.get("message") or "Claude is waiting for you.")


def codex(payload):
    data = json.loads(payload)
    if data.get("type") != "agent-turn-complete":
        return
    project = os.path.basename(data.get("cwd") or os.getcwd())
    send("Codex", project, "done", data.get("last-assistant-message") or "Turn complete.")


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] in ("prompt", "stop", "notify"):
            claude(sys.argv[1])
        elif len(sys.argv) > 3 and sys.argv[1] == "--chain":
            # Codex allows one notify command; run the one that was there before, then ours.
            import subprocess
            subprocess.Popen(json.loads(sys.argv[2]) + [sys.argv[-1]], start_new_session=True)
            codex(sys.argv[-1])
        elif len(sys.argv) > 1:
            codex(sys.argv[-1])
    except Exception:
        pass
    sys.exit(0)
