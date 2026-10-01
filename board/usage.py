# Agent limits straight from Anthropic and OpenAI: no Mac, no relay. The board signs in once per
# provider from the remote page with its own login (separate from the Mac's, so a refresh here never
# logs the Mac out) and keeps the tokens in oauth.json. Nothing here ever sends a token over the LAN.
import json, os, time, hashlib, binascii, requests

TOKENS = "oauth.json"

# Claude Code's public OAuth client. Only user:profile is asked for: enough to read usage, and a
# leaked board token can't run models.
CLAUDE_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_AUTHORIZE = "https://claude.ai/oauth/authorize"
CLAUDE_REDIRECT = "https://platform.claude.com/oauth/code/callback"   # shows a code to paste back
CLAUDE_TOKEN = "https://platform.claude.com/v1/oauth/token"
CLAUDE_USAGE = "https://api.anthropic.com/api/oauth/usage"

# Codex CLI's public OAuth client and its device-code sign-in (the "enter this code" kind).
CODEX_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_AUTH = "https://auth.openai.com"
CODEX_DEVICE_PAGE = CODEX_AUTH + "/codex/device"
CODEX_USAGE = "https://chatgpt.com/backend-api/wham/usage"

def _load():
    try:
        return json.load(open(TOKENS))
    except Exception:
        return {}

def _save(t):
    with open(TOKENS, "w") as f:
        json.dump(t, f)

def connected():
    t = _load()
    return [name for name in ("claude", "codex") if name in t]

def _q(s):
    return "".join(c if c.isalpha() or c.isdigit() or c in "-_.~" else "%%%02X" % ord(c) for c in s)

def _b64url(b):
    return binascii.b2a_base64(b).decode().strip().rstrip("=").replace("+", "-").replace("/", "_")

def _jwt(token):
    part = token.split(".")[1].replace("-", "+").replace("_", "/")
    return json.loads(binascii.a2b_base64(part + "=" * (-len(part) % 4)))

def _call(method, url, headers=None, body=None, form=None):
    """(status, parsed JSON) for one HTTPS request; a non-JSON body comes back as {'error': text}."""
    headers = dict(headers or {})
    data = None
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = "&".join(k + "=" + _q(v) for k, v in form.items())
    r = requests.request(method, url, data=data, json=body, headers=headers, timeout=15)
    try:
        status, text = r.status_code, r.text
    finally:
        r.close()
    try:
        return status, json.loads(text)
    except ValueError:
        return status, {"error": text[:80]}

def _keep(name, tok, **extra):
    t = _load()
    entry = t.get(name, {})
    entry["access"] = tok["access_token"]
    entry["refresh"] = tok.get("refresh_token") or entry.get("refresh")   # both providers rotate it
    entry.update(extra)
    t[name] = entry
    _save(t)

# --- Claude: open the sign-in link, then paste the code Anthropic shows back into the remote page.

_claude_pending = None      # (verifier, state) between "Connect Claude" and pasting the code

def claude_login_url():
    global _claude_pending
    verifier = _b64url(os.urandom(32))
    state = _b64url(os.urandom(32))
    _claude_pending = (verifier, state)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return (CLAUDE_AUTHORIZE + "?code=true&client_id=" + CLAUDE_ID + "&response_type=code&redirect_uri=" +
            _q(CLAUDE_REDIRECT) + "&scope=" + _q("user:profile") + "&code_challenge=" + challenge +
            "&code_challenge_method=S256&state=" + state)

def claude_finish(pasted):
    global _claude_pending
    if not _claude_pending:
        raise ValueError("Tap Connect Claude first.")
    verifier, state = _claude_pending
    code, _, pasted_state = pasted.strip().partition("#")      # Anthropic shows "code#state"
    if pasted_state and pasted_state != state:
        raise ValueError("That code is from another sign-in. Tap Connect Claude again.")
    status, tok = _call("POST", CLAUDE_TOKEN, body={
        "grant_type": "authorization_code", "client_id": CLAUDE_ID, "code": code, "state": state,
        "redirect_uri": CLAUDE_REDIRECT, "code_verifier": verifier})
    if status != 200:
        raise ValueError("Anthropic said %d: %s" % (status, tok.get("error_description") or tok.get("error") or ""))
    _keep("claude", tok)
    _claude_pending = None

# --- Codex: the board gets a short code, you type it at auth.openai.com/codex/device.

_codex_pending = None       # {"id", "code"} while waiting for you to enter the code

def codex_start():
    global _codex_pending
    status, r = _call("POST", CODEX_AUTH + "/api/accounts/deviceauth/usercode", body={"client_id": CODEX_ID})
    if status == 404:
        raise ValueError("Turn on device code sign-in in ChatGPT settings > Security, then try again.")
    if status != 200:
        raise ValueError("OpenAI said %d" % status)
    _codex_pending = {"id": r["device_auth_id"], "code": r.get("user_code") or r.get("usercode")}
    return _codex_pending["code"]

def codex_poll():
    """True once the code has been entered (tokens saved); False while still waiting."""
    global _codex_pending
    if not _codex_pending:
        raise ValueError("Tap Connect Codex first.")
    status, r = _call("POST", CODEX_AUTH + "/api/accounts/deviceauth/token",
                      body={"device_auth_id": _codex_pending["id"], "user_code": _codex_pending["code"]})
    if status in (403, 404):
        return False                                            # not entered yet
    if status != 200:
        raise ValueError("OpenAI said %d" % status)
    status, tok = _call("POST", CODEX_AUTH + "/oauth/token", form={
        "grant_type": "authorization_code", "client_id": CODEX_ID, "code": r["authorization_code"],
        "redirect_uri": CODEX_AUTH + "/deviceauth/callback", "code_verifier": r["code_verifier"]})
    if status != 200:
        raise ValueError("OpenAI said %d" % status)
    account = _jwt(tok["id_token"]).get("https://api.openai.com/auth", {}).get("chatgpt_account_id")
    _keep("codex", tok, account=account)
    _codex_pending = None
    return True

# --- Reading usage. Access tokens expire (Claude after hours, Codex after days); a 401 swaps the
# refresh token for new ones, so this never needs the board's clock.

def _refresh(t, name):
    url, cid = (CLAUDE_TOKEN, CLAUDE_ID) if name == "claude" else (CODEX_AUTH + "/oauth/token", CODEX_ID)
    status, tok = _call("POST", url, body={"grant_type": "refresh_token", "refresh_token": t[name]["refresh"], "client_id": cid})
    if status != 200:
        raise ValueError("sign in again")
    _keep(name, tok)
    t[name] = _load()[name]

def _get(t, name, url, headers):
    for attempt in (0, 1):
        status, r = _call("GET", url, headers(t[name]))
        if status == 401 and not attempt:
            _refresh(t, name)
            continue
        if status != 200:
            raise ValueError("error %d" % status)
        return r

def humanize(seconds):
    """'3h 2m', '4d 15h', 'now' - same as the Mac pusher."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "now"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return "%dd %dh" % (days, hours) if hours else "%dd" % days
    if hours:
        return "%dh %dm" % (hours, minutes) if minutes else "%dh" % hours
    return "%dm" % minutes

def _until(iso):
    """Time left until an ISO UTC timestamp ('2026-09-27T18:00:00.12+00:00'); needs the NTP clock."""
    if not iso:
        return ""
    try:
        d, t = iso[:19].split("T")
        stamp = time.mktime(tuple(int(x) for x in d.split("-")) + tuple(int(x) for x in t.split(":")) + (0, 0))
    except Exception:
        return ""
    left = stamp - time.time()
    return humanize(left) if left < 8 * 86400 else "?"         # way off = clock not set yet

def _label(seconds):
    seconds = int(seconds or 0)
    if seconds == 7 * 86400:
        return "Weekly"
    return "%d-hr" % (seconds // 3600) if seconds < 86400 else "%dd" % (seconds // 86400)

def _claude(t):
    r = _get(t, "claude", CLAUDE_USAGE, lambda e: {
        "Authorization": "Bearer " + e["access"], "anthropic-beta": "oauth-2025-04-20"})
    return [{"label": label, "used": int(round(r[key].get("utilization") or 0)), "resets": _until(r[key].get("resets_at"))}
            for key, label in (("five_hour", "5-hr"), ("seven_day", "Weekly")) if r.get(key)]

def _codex(t):
    r = _get(t, "codex", CODEX_USAGE, lambda e: {
        "Authorization": "Bearer " + e["access"], "ChatGPT-Account-Id": e.get("account") or "", "User-Agent": "codex-cli"})
    limits = r.get("rate_limit") or {}
    return [{"label": _label(w.get("limit_window_seconds")), "used": int(w.get("used_percent") or 0),
             "resets": humanize(w.get("reset_after_seconds"))}
            for w in (limits.get("primary_window"), limits.get("secondary_window")) if w]

def fetch(previous=None):
    """A snapshot shaped like the relay's ({"providers"}) for dashboard.draw. A provider
    that fails keeps its previous numbers, marked with why."""
    t = _load()
    before = {p.get("name"): p for p in (previous or {}).get("providers", [])}
    cards = []
    for name, label, read in (("claude", "Claude", _claude), ("codex", "Codex", _codex)):
        if name not in t:
            continue
        try:
            cards.append({"name": label, "status": "live", "windows": read(t)})
        except Exception as e:
            print("usage %s: %s" % (name, e))
            cards.append({"name": label, "status": str(e)[:20], "windows": before.get(label, {}).get("windows", [])})
    return {"providers": cards}
