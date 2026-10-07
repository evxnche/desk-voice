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

# Grok CLI's public OAuth client and xAI's device-code sign-in (the same "enter this code" kind).
GROK_ID = "b1a00492-073a-47ea-816f-4c329264a828"
GROK_AUTH = "https://auth.x.ai/oauth2"
GROK_USAGE = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"

# Command Code and OpenCode Go read usage with an API key pasted on the remote page. Unlike the
# logins above these keys can run models, so treat oauth.json on the board as a secret.
COMMANDCODE_USAGE = "https://api.commandcode.ai/alpha/billing/credits"
COMMANDCODE_PLAN = "https://api.commandcode.ai/alpha/billing/subscriptions"
OPENCODE_USAGE = "https://opencode.ai/zen/go/v1/usage"

# Monthly credits (USD) per Command Code plan, from the CLI's own table; the API only says what's left.
COMMANDCODE_CREDITS = {"individual-go": 10, "individual-goat": 70, "individual-pro": 30, "individual-pro-v1": 80,
                       "individual-provider": 15, "individual-max": 150, "individual-ultra": 300, "teams-pro": 40}

# Muse Code has no usage endpoint: its limits only arrive at the end of a reply, so each read sends
# "hi" (~24 tokens) and keeps the response.subscription_usage event. The key is the Muse CLI's own
# API key (from the Mac's Keychain); it doesn't rotate, so sharing it never logs the Mac out.
MUSE_RESPONSES = "https://api.meta.ai/v1/responses"
MUSE_MODEL = "muse-spark-1.3-contributor"

NAMES = (("claude", "Claude"), ("codex", "Codex"), ("commandcode", "Command Code"),
         ("opencode", "OpenCode"), ("grok", "Grok"), ("muse", "Muse Code"))

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
    return [name for name, _ in NAMES if name in t]

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

# --- Grok: same as Codex, the code is entered at accounts.x.ai.

_grok_pending = None        # device_code while waiting for you to enter the code

def grok_start():
    """(code, page) to show on the remote page."""
    global _grok_pending
    status, r = _call("POST", GROK_AUTH + "/device/code", form={
        "client_id": GROK_ID, "scope": "openid profile email offline_access grok-cli:access"})
    if status != 200:
        raise ValueError("xAI said %d" % status)
    _grok_pending = r["device_code"]
    return r["user_code"], r.get("verification_uri_complete") or r["verification_uri"]

def grok_poll():
    """True once the code has been entered (tokens saved); False while still waiting."""
    global _grok_pending
    if not _grok_pending:
        raise ValueError("Tap Connect Grok first.")
    status, tok = _call("POST", GROK_AUTH + "/token", form={
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": _grok_pending,
        "client_id": GROK_ID})
    if tok.get("error") in ("authorization_pending", "slow_down"):
        return False
    if status != 200:
        raise ValueError("xAI said %d: %s" % (status, tok.get("error_description") or tok.get("error") or ""))
    _keep("grok", tok)
    _grok_pending = None
    return True

# --- Command Code / OpenCode Go: just a key.

def save_key(name, key):
    if name not in ("commandcode", "opencode") or not key.strip():
        raise ValueError("Paste a key first.")
    t = _load()
    t[name] = {"access": key.strip()}
    _save(t)

# --- Reading usage. Access tokens expire (Claude and Grok after hours, Codex after days); a 401 swaps
# the refresh token for new ones, so this never needs the board's clock.

def _refresh(t, name):
    if not t[name].get("refresh"):
        raise ValueError("key rejected")                       # a pasted key has nothing to refresh
    grant = {"grant_type": "refresh_token", "refresh_token": t[name]["refresh"]}
    if name == "grok":                                          # xAI wants a form, the others JSON
        grant["client_id"] = GROK_ID
        status, tok = _call("POST", GROK_AUTH + "/token", form=grant)
    else:
        url, cid = (CLAUDE_TOKEN, CLAUDE_ID) if name == "claude" else (CODEX_AUTH + "/oauth/token", CODEX_ID)
        grant["client_id"] = cid
        status, tok = _call("POST", url, body=grant)
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

# Seconds from 1970 to the board's epoch: the ESP32 counts from 2000, a Mac from 1970.
_UNIX = 946684800 if time.localtime(0)[0] == 2000 else 0

def _stamp(iso):
    """Epoch seconds for an ISO UTC timestamp ('2026-09-27T18:00:00.12+00:00'), or None."""
    try:
        d, t = iso[:19].split("T")
        return time.mktime(tuple(int(x) for x in d.split("-")) + tuple(int(x) for x in t.split(":")) + (0, 0))
    except Exception:
        return None

def _until(stamp):
    """Time left until `stamp`; needs the NTP clock."""
    if stamp is None:
        return ""
    left = stamp - time.time()
    return humanize(left) if left < 32 * 86400 else "?"        # way off = clock not set yet

def _at(stamp):
    """The local clock time of `stamp`: '3pm', '3:30pm', 'thu 3pm' when it isn't today, '25 oct' when
    it's over a week out; '' before NTP."""
    import room
    now = room.local_time()
    if stamp is None or not now:
        return ""
    stamp = int(stamp) + 30                                     # to the nearest minute: 2:59:59 is 3pm
    lt = time.localtime(stamp + room._offset(stamp))
    if stamp - time.time() >= 8 * 86400:                       # a weekday would be ambiguous
        return "%d %s" % (lt[2], room.MONTHS[lt[1] - 1])
    at = room.clock(lt[3], lt[4]).replace(":00", "")
    return at if lt[:3] == now[:3] else room.DAYS[lt[6]] + " " + at

def _label(seconds):
    seconds = int(seconds or 0)
    if seconds == 7 * 86400:
        return "Weekly"
    return "%d-hr" % (seconds // 3600) if seconds < 86400 else "%dd" % (seconds // 86400)

def _claude(t):
    r = _get(t, "claude", CLAUDE_USAGE, lambda e: {
        "Authorization": "Bearer " + e["access"], "anthropic-beta": "oauth-2025-04-20"})
    windows = []
    for key, label in (("five_hour", "5-hr"), ("seven_day", "Weekly")):
        if r.get(key):
            stamp = _stamp(r[key].get("resets_at") or "")
            windows.append({"label": label, "used": int(round(r[key].get("utilization") or 0)),
                            "resets": _until(stamp), "at": _at(stamp)})
    return windows

def _codex(t):
    r = _get(t, "codex", CODEX_USAGE, lambda e: {
        "Authorization": "Bearer " + e["access"], "ChatGPT-Account-Id": e.get("account") or "", "User-Agent": "codex-cli"})
    limits = r.get("rate_limit") or {}
    return [{"label": _label(w.get("limit_window_seconds")), "used": int(w.get("used_percent") or 0),
             "resets": humanize(w.get("reset_after_seconds")),
             "at": _at(time.time() + int(w.get("reset_after_seconds") or 0))}
            for w in (limits.get("primary_window"), limits.get("secondary_window")) if w]

def _windows(*rows):
    """Window dicts from (label, used %, reset epoch seconds or None) rows."""
    return [{"label": label, "used": int(round(used or 0)), "resets": _until(stamp), "at": _at(stamp)}
            for label, used, stamp in rows]

def _commandcode(t):
    auth = lambda e: {"Authorization": "Bearer " + e["access"]}
    r = _get(t, "commandcode", COMMANDCODE_USAGE, auth)
    limits = r.get("windowLimits") or {}
    rows = []
    for key, label in (("fiveHour", "5-hr"), ("weekly", "Weekly")):
        w = limits.get(key)
        if w and w.get("cap"):                                  # resetAt is 0 until the window starts
            rows.append((label, 100 * (w.get("used") or 0) / w["cap"], w["resetAt"] / 1000 - _UNIX if w.get("resetAt") else None))
    # Monthly credits, the way the CLI's /usage works them out: plan allowance + extras, minus what's left.
    sub = _get(t, "commandcode", COMMANDCODE_PLAN, auth).get("data") or {}
    plan = (sub.get("planId") or "").lower().replace("_", "-")
    match = [k for k in COMMANDCODE_CREDITS if plan.startswith(k)]
    credits = r.get("credits") or {}
    if sub.get("status") == "active" and match:
        monthly = max(0, credits.get("monthlyCredits") or 0)
        extra = max(0, credits.get("purchasedCredits") or 0) + max(0, credits.get("freeCredits") or 0)
        pool = max(COMMANDCODE_CREDITS[max(match, key=len)], monthly) + extra
        rows.append(("Month", 100 * (pool - monthly - extra) / pool, _stamp(sub.get("currentPeriodEnd") or "")))
    return _windows(*rows)

def _opencode(t):
    r = _get(t, "opencode", OPENCODE_USAGE, lambda e: {"Authorization": "Bearer " + e["access"]})
    u = r.get("usage") or {}
    return _windows(*[(label, u[key].get("percent"), _stamp(u[key].get("resetsAt") or ""))
                      for key, label in (("rolling", "5-hr"), ("weekly", "Weekly"), ("monthly", "Month")) if u.get(key)])

def _grok(t):
    r = _get(t, "grok", GROK_USAGE, lambda e: {"Authorization": "Bearer " + e["access"], "User-Agent": "grok-cli"})
    c = r.get("config") or {}
    kind = (c.get("currentPeriod") or {}).get("type", "")     # USAGE_PERIOD_TYPE_WEEKLY
    label = {"WEEKLY": "Weekly", "MONTHLY": "Month", "DAILY": "Daily"}.get(kind.split("_")[-1], "Usage")
    return _windows((label, c.get("creditUsagePercent"), _stamp(c.get("billingPeriodEnd") or "")))

def _muse(t):
    r = requests.post(MUSE_RESPONSES, timeout=30, headers={"Authorization": "Bearer " + t["muse"]["access"]},
                      json={"model": MUSE_MODEL, "input": "hi", "stream": True, "store": False,
                            "reasoning": {"effort": "minimal"}, "max_output_tokens": 16})
    try:
        status, text = r.status_code, r.text
    finally:
        r.close()
    if status != 200:
        raise ValueError("error %d" % status)
    for line in text.split("\n"):
        if line.startswith("data:") and "subscription_usage" in line:
            u = json.loads(line[5:])["subscription"]
            rows = []
            for w, label in ((u.get("window"), None), (u.get("weekly"), "Weekly")):
                if w:
                    rows.append((label or _label(60 * (w.get("window_duration_mins") or 0)), w.get("used_percent"),
                                 w["resets_at"] - _UNIX if w.get("resets_at") else None))
            return _windows(*rows)
    raise ValueError("no usage in reply")

def fetch(previous=None):
    """A snapshot shaped like the relay's ({"providers"}) for dashboard.draw. A provider
    that fails keeps its previous numbers, marked with why."""
    t = _load()
    before = {p.get("name"): p for p in (previous or {}).get("providers", [])}
    cards = []
    readers = {"claude": _claude, "codex": _codex, "commandcode": _commandcode, "opencode": _opencode, "grok": _grok,
               "muse": _muse}
    for name, label in NAMES:
        if name not in t:
            continue
        try:
            cards.append({"name": label, "status": "live", "windows": readers[name](t)})
        except Exception as e:
            print("usage %s: %s" % (name, e))
            cards.append({"name": label, "status": str(e)[:20], "windows": before.get(label, {}).get("windows", [])})
    return {"providers": cards}
