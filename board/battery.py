# 18650 level from the onboard divider: GPIO4 (ADC1 ch3) sees 1/3 of the battery voltage.
from machine import ADC, Pin

_adc = ADC(Pin(4), atten=ADC.ATTN_11DB)

def volts():
    return sum(_adc.read_uv() for _ in range(16)) * 3 / 16 / 1e6

def percent():
    # Waveshare's own mapping: 3.0 V empty, 4.12 V full, linear between.
    return max(0, min(100, int((volts() - 3.0) / 1.12 * 100)))

def draw(d, right, y):
    """Battery icon + percentage, right-aligned to x=`right`, 16 px tall text at `y`."""
    pct = percent()
    label = "%d%%" % pct
    x = right - 16 * len(label)
    d.text_large(label, x, y, 2)
    ix = x - 38
    d.rect(ix, y + 1, 30, 14, 1)
    d.fill_rect(ix + 30, y + 5, 3, 6, 1)
    d.fill_rect(ix + 2, y + 3, 26 * pct // 100, 10, 1)

def draw_small(d, right, y):
    """Small battery icon + percentage in the small font, right-aligned to x=`right`, ~9 px tall."""
    import font5
    pct = percent()
    label = "%d%%" % pct
    x = right - 6 * len(label)
    font5.text(d.canvas, label, x, y)
    ix = x - 22
    d.rect(ix, y - 1, 17, 9, 1)
    d.fill_rect(ix + 17, y + 1, 2, 5, 1)
    d.fill_rect(ix + 2, y + 1, 13 * pct // 100, 5, 1)
