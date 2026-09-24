# Radar screen: aircraft near home (desk-voice /api/flights). The nearest few are numbered on
# the radar and described in plain English in the list on the right.
import math, requests
from array import array
import dashboard, secrets

URL = secrets.VOICE_URL.replace("/api/voice", "/api/flights") + "?k=" + secrets.VOICE_KEY
if hasattr(secrets, "HOME_LAT"):
    URL += "&lat=%s&lon=%s" % (secrets.HOME_LAT, secrets.HOME_LON)

CX, CY, R = 106, 164, 100       # radar centre and radius in pixels
LIST_X = 216

last = None

def fetch():
    """Refresh `last`; return '' on success or a short error for the footer."""
    global last
    try:
        r = requests.get(URL, timeout=15)
        if r.status_code == 200:
            last = r.json()
            r.close()
            return ""
        code = r.status_code
        r.close()
        return "flight data error %d" % code
    except Exception as e:
        return "flight fetch failed: %s" % e

def _commas(n):
    s = str(abs(int(n)))
    out = ""
    while len(s) > 3:
        out = "," + s[-3:] + out
        s = s[:-3]
    return ("-" if n < 0 else "") + s + out

def _plane(c, x, y, track, size, filled):
    """Arrowhead pointing along `track` (degrees)."""
    t = math.radians(track)
    pts = []
    for ang, rad in ((0, size), (140, size * 0.8), (180, size * 0.3), (220, size * 0.8)):
        a = t + math.radians(ang)
        pts += (int(rad * math.sin(a)), -int(rad * math.cos(a)))
    c.poly(x, y, array("h", pts), 1, filled)

def _arrow(c, x, y, up):
    """Tiny climbing/descending triangle, 7 px wide."""
    for i in range(4):
        row = y + (i if not up else 3 - i)
        c.hline(x + i, row + 1, 7 - 2 * i, 1)

def draw(footer=""):
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    d.text_large("FLIGHTS", 10, 8, 2)
    if last:
        n = len(last["aircraft"])
        label = dashboard.ascii("%d plane%s near %s" % (n, "" if n == 1 else "s", last.get("place", "") or "you"))[:30]
        c.text(label, 392 - 8 * len(label), 13, 1)
    d.line(0, 32, 400, 32, 1)

    # radar
    for rr in (R, R // 2):
        c.ellipse(CX, CY, rr, rr, 1)
    c.text("N", CX - 3, CY - R - 10, 1)
    c.hline(CX - 4, CY, 9, 1)
    c.vline(CX, CY - 4, 9, 1)
    c.text("you", CX - 11, CY + 7, 1)
    if last:
        miles = last.get("miles", 30)
        c.text("%dmi" % miles, CX - R + 2, CY + R - 30, 1)
        c.text("%dmi" % (miles // 2), CX - R // 2 + 4, CY + R // 2 - 22, 1)
        radius = last.get("radius", 26)
        numbered = []
        for i, a in enumerate(last["aircraft"]):
            b = math.radians(a["bearing"])
            px = CX + int(a["dist"] / radius * R * math.sin(b))
            py = CY - int(a["dist"] / radius * R * math.cos(b))
            if "who" in a:
                numbered.append((i + 1, px, py))
                _plane(c, px, py, a["track"], 8, True)
            else:
                _plane(c, px, py, a["track"], 6, False)
        for n, px, py in numbered:                 # numbers last so planes never cover them
            c.fill_rect(px + 5, py - 12, 10, 11, 0)
            c.text(str(n), px + 6, py - 10, 1)

        # list
        c.vline(LIST_X - 6, 38, 246, 1)
        y = 38
        for i, a in enumerate(last["aircraft"]):
            if "who" not in a:
                break
            d.text_large(str(i + 1), LIST_X, y + 6, 2)
            tx = LIST_X + 20
            c.text(dashboard.ascii(a["who"])[:20], tx, y, 1)
            c.text(dashboard.ascii(a["where"])[:20], tx, y + 10, 1)
            info = "%sft %dmi %s" % (_commas(a["alt"]), a["miles"], a["dir"]) if a["alt"] >= 100 else "low %dmi %s" % (a["miles"], a["dir"])
            c.text(info, tx, y + 20, 1)
            if a.get("trend"):
                _arrow(c, tx + 8 * len(info) + 4, y + 20, a["trend"] == "up")
            if y > 38:
                c.hline(LIST_X, y - 4, 400 - LIST_X - 4, 1)
            y += 41
        if not last["aircraft"]:
            c.text("no aircraft nearby", LIST_X, 44, 1)
    else:
        d.text_large("loading...", CX - 76, CY - 8, 2)

    c.fill_rect(0, 286, 400, 14, 1)
    c.text(dashboard.ascii(footer)[:50] if footer else "BOOT: next screen   KEY: refresh / hold to talk", 4, 289, 0)
    d.show()
