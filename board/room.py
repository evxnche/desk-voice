# Room screen: UK local time (from NTP) + onboard SHTC3 temperature/humidity.
import time
from machine import I2C, Pin
import dashboard

i2c = I2C(0, scl=Pin(14), sda=Pin(13), freq=100000)
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

def climate():
    """(temp C, humidity %) from the SHTC3, or None if it doesn't answer."""
    try:
        i2c.writeto(0x70, b"\x35\x17")            # wake
        time.sleep_ms(1)
        i2c.writeto(0x70, b"\x78\x66")            # measure, T first
        time.sleep_ms(20)
        d = i2c.readfrom(0x70, 6)
        i2c.writeto(0x70, b"\xb0\x98")            # sleep
    except OSError:
        return None
    return -45 + 175 * ((d[0] << 8) | d[1]) / 65536, 100 * ((d[3] << 8) | d[4]) / 65536

def _uk_offset(t):
    """BST (+1h) from 01:00 UTC on the last Sunday of March to the last Sunday of October."""
    y = time.localtime(t)[0]
    def last_sunday(month):
        ts = time.mktime((y, month, 31, 1, 0, 0, 0, 0))
        return ts - ((time.localtime(ts)[6] + 1) % 7) * 86400
    return 3600 if last_sunday(3) <= t < last_sunday(10) else 0

def local_time():
    t = time.time()
    if time.localtime(t)[0] < 2025:              # clock never synced
        return None
    return time.localtime(t + _uk_offset(t))

def draw():
    d = dashboard.display()
    d.clear(0)
    d.text_large("ROOM", 10, 8, 2)
    lt = local_time()
    if lt:
        date = "%s %d %s" % (DAYS[lt[6]], lt[2], MONTHS[lt[1] - 1])
        d.text_large(date, 390 - 16 * len(date), 8, 2)
        d.text_large("%02d:%02d" % (lt[3], lt[4]), 40, 60, 8)
    else:
        d.text_large("--:--", 40, 60, 8)
    d.line(0, 32, 400, 32, 1)
    d.line(0, 150, 400, 150, 1)
    c = climate()
    d.text("TEMPERATURE", 20, 168, 1)
    d.text("HUMIDITY", 230, 168, 1)
    if c:
        d.text_large("%.1fC" % c[0], 20, 190, 4)
        d.text_large("%d%%" % round(c[1]), 230, 190, 4)
    else:
        d.text_large("sensor?", 20, 190, 2)
    d.fill_rect(0, 286, 400, 14, 1)
    d.text("BOOT: next screen   KEY: refresh / hold to talk", 4, 289, 0)
    d.show()
