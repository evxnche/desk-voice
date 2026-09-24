# Renders the board's fonts into fixed-cell 1-bit bitmaps (run on the Mac: python3 tools/make_fonts.py).
# Each cell matches the grid the screens were laid out on, so no layout moves:
#   font_small.bin  MS Gothic 12 px in a 6 px cell       (was font5 5x7)
#   font_body.bin   Departure Mono 11 px in an 8 px cell (was framebuf's 8x8)
#   font_bigN.bin   ABC Areal Mono Bold in an 8N px cell (was the 8x8 scaled N times by text_large)
# File layout (read by board/bitfont.py): cell width, cell height, rows above the capitals, then 95
# glyphs (chars 32..126), MONO_HLSB, 1 = ink. y on the board is still the top of the capitals, as with
# the old fonts; taller glyphs (brackets, ascenders) reach `above` rows higher.
import os
from PIL import Image, ImageDraw, ImageFont

FONTS = os.path.expanduser("~/Library/Fonts")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board")
CHARS = [chr(c) for c in range(32, 127)]
BIG_SCALES = (2, 3, 4, 5, 6, 8, 9, 11)   # every scale text_large() is called with

def build(name, path, size, cell_w):
    font = ImageFont.truetype(os.path.join(FONTS, path), size)
    boxes = [font.getbbox(ch, anchor="ls") for ch in CHARS if ch != " "]
    top = min(b[1] for b in boxes)                 # tallest glyph (negative, above the baseline)
    bottom = max(b[3] for b in boxes)              # deepest descender
    cap = -font.getbbox("H", anchor="ls")[1]
    base, cell_h, above = -top, bottom - top, max(0, -top - cap)
    adv = round(font.getlength("0"))
    x0 = max(0, (cell_w - adv) // 2)               # centre narrower glyphs in the cell
    out = bytearray([cell_w, cell_h, above])
    for ch in CHARS:
        img = Image.new("1", (cell_w, cell_h), 1)
        d = ImageDraw.Draw(img)
        d.fontmode = "1"                           # no anti-aliasing: exactly what the panel shows
        d.text((x0, base), ch, font=font, fill=0, anchor="ls")
        out += bytes(b ^ 0xFF for b in img.tobytes())   # PIL "1" is 1 = white; the board wants 1 = ink
    open(os.path.join(OUT, name + ".bin"), "wb").write(out)
    print("%-11s %s %d px: cell %dx%d, caps %d px (+%d above), glyph %d px wide, %d bytes"
          % (name, path, size, cell_w, cell_h, cap, above, adv, len(out)))

build("font_small", "ms-gothic.ttf", 12, 6)   # 11 px squashes g/y descenders
build("font_body", "DepartureMono-Regular.otf", 11, 8)
for s in BIG_SCALES:
    # the biggest size whose capitals fit 7.5 rows of the old 8-row glyph and whose width fits the cell
    size = 8
    while True:
        f = ImageFont.truetype(os.path.join(FONTS, "ABCArealMono-Bold.ttf"), size + 1)
        cap = -f.getbbox("H", anchor="ls")[1]
        if cap > 7.5 * s or f.getlength("0") > 8 * s:
            break
        size += 1
    build("font_big%d" % s, "ABCArealMono-Bold.ttf", size, 8 * s)
