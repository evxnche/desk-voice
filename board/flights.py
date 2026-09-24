# Radar screen: aircraft near home (desk-voice /api/flights -> adsb.lol), nearest listed on the right.
import math, requests
import dashboard, secrets

URL = secrets.VOICE_URL.replace("/api/voice", "/api/flights") + "?k=" + secrets.VOICE_KEY
if hasattr(secrets, "HOME_LAT"):
    URL += "&lat=%s&lon=%s" % (secrets.HOME_LAT, secrets.HOME_LON)

CX, CY, R = 132, 162, 116       # radar centre and radius in pixels
LIST_X, LIST_ROWS = 262, 9

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

def _alt(ft):
    return "low" if ft < 100 else "%dft" % ft

def draw(footer=""):
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    d.text_large("FLIGHTS", 10, 8, 2)
    if last:
        n = len(last["aircraft"])
        label = dashboard.ascii("%d plane%s near %s" % (n, "" if n == 1 else "s", last.get("place", "") or "you"))[:32]
        d.text(label, 392 - 8 * len(label), 13, 1)
    d.line(0, 32, 400, 32, 1)

    # radar: two range rings, north tick, "you" cross
    for rr in (R, R // 2):
        c.ellipse(CX, CY, rr, rr, 1)
    c.text("N", CX - 3, CY - R - 10, 1)
    c.hline(CX - 4, CY, 9, 1)
    c.vline(CX, CY - 4, 9, 1)
    if last:
        radius = last.get("radius", 25)
        c.text("%dnm" % radius, CX + 3, CY + R - 10, 1)            # ring labels down the south axis
        c.text("%dnm" % (radius // 2), CX + 3, CY + R // 2 - 10, 1)
        for i, a in enumerate(last["aircraft"]):
            b = math.radians(a["bearing"])
            px = CX + int(a["dist"] / radius * R * math.sin(b))
            py = CY - int(a["dist"] / radius * R * math.cos(b))
            t = math.radians(a["track"])
            c.fill_rect(px - 2, py - 2, 5, 5, 1)
            c.line(px, py, px + int(10 * math.sin(t)), py - int(10 * math.cos(t)), 1)
            if i < 5:                              # label only the nearest few to keep it readable
                c.text(dashboard.ascii(a["id"])[:7], px + 5, py + 3, 1)

        # nearest list
        c.vline(LIST_X - 8, 40, 240, 1)
        y = 42
        for a in last["aircraft"][:LIST_ROWS]:
            c.text(dashboard.ascii("%-7s %s" % (a["id"][:7], a["type"]))[:17], LIST_X, y, 1)
            c.text("%s %snm" % (_alt(a["alt"]), a["dist"]), LIST_X, y + 10, 1)
            y += 26
        if not last["aircraft"]:
            c.text("no aircraft", LIST_X, 44, 1)
    else:
        d.text_large("loading...", CX - 76, CY - 8, 2)

    c.fill_rect(0, 286, 400, 14, 1)
    c.text(dashboard.ascii(footer)[:50] if footer else "BOOT: next screen   KEY: refresh / hold to talk", 4, 289, 0)
    d.show()
