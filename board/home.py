# "Where am I?" per Wi-Fi network. The phone's location (sent via the remote page's button) is saved
# for the network the board is on, so a location set on the hotspot never sticks once you're home.
# With nothing saved for this network, the service falls back to IP geolocation.
import json, network

FILE = "locations.json"

def _ssid():
    w = network.WLAN(network.STA_IF)
    return w.config("ssid") if w.isconnected() else ""

def _all():
    try:
        return json.load(open(FILE))
    except Exception:
        return {}

def save(lat, lon, place):
    locs = _all()
    locs[_ssid()] = {"lat": lat, "lon": lon, "place": place}
    with open(FILE, "w") as f:
        json.dump(locs, f)

def current():
    return _all().get(_ssid())

def _quote(s):
    return "".join(c if c.isalpha() or c.isdigit() or c in "-_." else "%%%02X" % ord(c) for c in s)

def query():
    """'&home_lat=..&home_lon=..&home_place=..' for the saved location on this network, else ''."""
    loc = current()
    if not loc:
        return ""
    return "&home_lat=%s&home_lon=%s&home_place=%s" % (loc["lat"], loc["lon"], _quote(loc.get("place", "")))
