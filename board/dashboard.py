from machine import Pin, SPI
import rlcd, battery, palicon, font5

W, H = 400, 300
_display = None

def display():
    global _display
    if _display is None:
        # SPI(2) defaults MISO to GPIO37, which the octal PSRAM owns, and GPIO13 is the codec I2C SDA; the display is write-only, so no MISO.
        spi = SPI(1, baudrate=20000000, polarity=0, phase=0, sck=Pin(11), mosi=Pin(12), miso=None)
        _display = rlcd.RLCD(spi, cs=Pin(40), dc=Pin(5), rst=Pin(41))
    return _display

_SUBS = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-",
         "\u2014": "-", "\u2026": "...", "\u00b0": "", "\u00a0": " ", "\u00df": "ss"}
# Accented letters fold to their base letter (place names like Duesseldorf, Cancun, Malaga).
for _base, _accented in (("a", "\u00e0\u00e1\u00e2\u00e3\u00e4\u00e5"), ("e", "\u00e8\u00e9\u00ea\u00eb"),
                         ("i", "\u00ec\u00ed\u00ee\u00ef"), ("o", "\u00f2\u00f3\u00f4\u00f5\u00f6\u00f8"),
                         ("u", "\u00f9\u00fa\u00fb\u00fc"), ("c", "\u00e7"), ("n", "\u00f1")):
    for _ch in _accented:
        _SUBS[_ch] = _base
        _SUBS[chr(ord(_ch) - 32)] = _base.upper()   # Latin-1 capitals sit 32 below; MicroPython can't .upper() them

def ascii(s):
    return "".join(_SUBS.get(c, c if 32 <= ord(c) < 127 else "-") for c in str(s))

def bar(d, x, y, w, h, pct):
    d.rect(x, y, w, h, 1)
    fill = max(0, min(100, pct)) * (w - 4) // 100
    if fill:
        d.fill_rect(x + 2, y + 2, fill, h - 4, 1)

def header(d, title, extra=""):
    """The header every screen shares, on a 24 px bar: title, date and time at the same places, `extra`
    (small, up to 14 chars) right before the battery. The title and extra keep the caller's case; the
    date and time are always lowercase."""
    import room                      # room imports this module
    d.text(ascii(title)[:9], 10, 9, 1)
    if extra:
        extra = ascii(extra)[:14]
        font5.text(d.canvas, extra, 338 - 6 * len(extra), 10)
    case, font5.lowercase = font5.lowercase, True
    lt = room.local_time()
    if lt:
        d.text("%s %d %s" % (room.DAYS[lt[6]], lt[2], room.MONTHS[lt[1] - 1]), 98, 9, 1)
        d.text(room.clock(lt[3], lt[4]), 186, 9, 1)
    font5.lowercase = case
    battery.draw_small(d, 392, 10)
    d.line(0, 24, W, 24, 1)

def draw(data, footer=""):
    d = display()
    d.clear(0)
    header(d, "limits")
    palicon.draw(d.canvas, 360, 28, "limits")

    # Compact rows so six providers fit: name, then one line per window (label, bar, %, reset).
    # Text stops short of x=358 so it never runs under the Pal icon.
    y = 30
    for p in data.get("providers", []):
        windows = p.get("windows", [])[:3]
        if y + 12 + 13 * len(windows) > H - 14:   # keep clear of the footer bar
            break
        name = ascii(p.get("name", "?"))
        if p.get("status", "live") != "live":
            name += " (" + ascii(p["status"]) + ")"
        d.text(name.lower(), 10, y, 1)
        y += 12
        for win in windows:
            used = int(win.get("used", 0))
            font5.text(d.canvas, ascii(win.get("label", ""))[:6], 10, y + 1)
            bar(d, 50, y, 100, 9, used)
            d.text("%d%%" % used, 156, y + 1, 1)
            if win.get("resets"):                   # blank when the window hasn't started yet
                resets = "resets " + ascii(win["resets"])
                if win.get("at"):
                    resets += " (" + ascii(win["at"]) + ")"
                font5.text(d.canvas, resets[:27], 196, y + 1)
            y += 13
        y += 4

    if footer:
        d.fill_rect(0, H - 14, W, 14, 1)
        d.text(ascii(footer)[:50], 4, H - 11, 0)
    d.show()

def message(title, line=""):
    d = display()
    d.clear(0)
    d.text_large(ascii(title), 10, 120, 2)
    d.text(ascii(line)[:50], 10, 150, 1)
    d.show()
