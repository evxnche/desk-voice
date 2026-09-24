# Small text for dense screens: MS Gothic 12 px in a 6 px cell (10 px line), from font_small.bin
# (made by tools/make_fonts.py). Same grid as the 5x7 font it replaced, so layouts are unchanged.
import bitfont

# The whole UI is lowercase except the flight radar, which turns this off while it draws.
# rlcd's text()/text_large() read it too.
lowercase = True

def text(fb, s, x, y):
    """Draw `s` in black at (x, y) on FrameBuffer `fb`; returns the x after the last char."""
    if lowercase:
        s = s.lower()
    return bitfont.get("font_small").text(fb, s, x, y)
