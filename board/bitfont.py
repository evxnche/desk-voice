# Fixed-cell bitmap fonts made on the Mac by tools/make_fonts.py. A .bin file is: cell width, cell
# height, rows above the capitals, then 95 glyphs (chars 32..126) and EXTRA's, MONO_HLSB, 1 = ink.
# y is the top of the capitals, like framebuf.text(); every glyph advances the full cell width.
import framebuf

EXTRA = "\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00fc\u00c1\u00c9\u00cd\u00d3\u00da\u00d1\u00dc\u00bf\u00a1"   # Spanish: áéíóúñü ÁÉÍÓÚÑÜ ¿¡

# Palette for white-on-black text: background 0 -> 1 (skipped via key=1), ink 1 -> 0.
_INVERT = framebuf.FrameBuffer(bytearray(1), 2, 1, framebuf.MONO_HLSB)
_INVERT.pixel(0, 0, 1)

class Font:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.w, self.h, self.above = f.read(3)
            self.data = memoryview(bytearray(f.read()))
        self.size = (self.w + 7) // 8 * self.h
        self.glyphs = {}

    def text(self, fb, s, x, y, c=1):
        """Draw `s` at (x, y) in colour c; returns the x after the last char."""
        y -= self.above
        for ch in s:
            o = ord(ch) - 32
            if o >= 95:
                o = 95 + EXTRA.find(ch) if ch in EXTRA else 0
            if 0 < o < 95 + len(EXTRA) and (o + 1) * self.size <= len(self.data):
                g = self.glyphs.get(o)
                if g is None:
                    g = self.glyphs[o] = framebuf.FrameBuffer(
                        self.data[o * self.size:(o + 1) * self.size], self.w, self.h, framebuf.MONO_HLSB)
                if c:
                    fb.blit(g, x, y, 0)
                else:
                    fb.blit(g, x, y, 1, _INVERT)
            x += self.w
        return x

_fonts = {}

def get(name):
    f = _fonts.get(name)
    if f is None:
        f = _fonts[name] = Font(name + ".bin")
    return f
