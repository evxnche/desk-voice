# Renders the board's fonts into fixed-cell 1-bit bitmaps (run on the Mac: python3 tools/make_fonts.py).
# Each cell matches the grid the screens were laid out on, so no layout moves:
#   font_small.bin  MS Gothic 12 px in a 6 px cell       (was font5 5x7)
#   font_body.bin   ABC Areal Mono Bold in an 8 px cell (was framebuf's 8x8)
#   font_mid.bin    Departure Mono at 16.5 px (1.5x its grid) in a 12 px cell, for sub-headings
#   font_bigN.bin   Departure Mono in an 8N px cell (was the 8x8 scaled N times by text_large); it's a
#                   pixel font drawn on an 11 px grid, so it's rendered at whole multiples of 11 px
# File layout (read by board/bitfont.py): cell width, cell height, rows above the capitals, then 95
# glyphs (chars 32..126) and the Spanish letters in bitfont.EXTRA, MONO_HLSB, 1 = ink. y on the board
# is still the top of the capitals, as with the old fonts; taller glyphs (brackets, ascenders) reach
# `above` rows higher.
import ast, os, unicodedata
from PIL import Image, ImageDraw, ImageFont

FONTS = os.path.expanduser("~/Library/Fonts")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board")
# After ASCII, so Spanish shows its accents. Read from bitfont.py, which needs MicroPython to import.
EXTRA = next(ast.literal_eval(n.value) for n in ast.parse(open(os.path.join(OUT, "bitfont.py")).read()).body
             if isinstance(n, ast.Assign) and n.targets[0].id == "EXTRA")
CHARS = [chr(c) for c in range(32, 127)]
BIG_SCALES = (2, 3, 4, 5, 6, 8, 9, 11)   # every scale text_large() is called with

def build(name, path, size, cell_w, accents=True):
    """`accents=False`: the Spanish letters are drawn as their plain letters (é as e, ¿ as ?)."""
    font = ImageFont.truetype(os.path.join(FONTS, path), size)
    boxes = [font.getbbox(ch, anchor="ls") for ch in CHARS if ch != " "]
    top = min(b[1] for b in boxes)                 # tallest glyph (negative, above the baseline)
    bottom = max(b[3] for b in boxes)              # deepest descender
    cap = -font.getbbox("H", anchor="ls")[1]
    base, cell_h, above = -top, bottom - top, max(0, -top - cap)
    adv = round(font.getlength("0"))
    x0 = max(0, (cell_w - adv) // 2)               # centre narrower glyphs in the cell
    out = bytearray([cell_w, cell_h, above])
    for ch in CHARS + list(EXTRA):                 # the cell fits ASCII; capital accents may be clipped
        if ch in EXTRA and not accents:
            ch = {"\u00bf": "?", "\u00a1": "!"}.get(ch) or unicodedata.normalize("NFD", ch)[0]
        img = Image.new("1", (cell_w, cell_h), 1)
        d = ImageDraw.Draw(img)
        d.fontmode = "1"                           # no anti-aliasing: exactly what the panel shows
        d.text((x0, base), ch, font=font, fill=0, anchor="ls")
        out += bytes(b ^ 0xFF for b in img.tobytes())   # PIL "1" is 1 = white; the board wants 1 = ink
    open(os.path.join(OUT, name + ".bin"), "wb").write(out)
    print("%-11s %s %d px: cell %dx%d, caps %d px (+%d above), glyph %d px wide, %d bytes"
          % (name, path, size, cell_w, cell_h, cap, above, adv, len(out)))

def fit(path, scale, step=1, rows=8):
    """The biggest size (a multiple of `step`) whose capitals fit `rows` rows of the old 8-row glyph at
    this scale and whose width fits the 8 x scale cell."""
    size = step
    while True:
        f = ImageFont.truetype(os.path.join(FONTS, path), size + step)
        if -f.getbbox("H", anchor="ls")[1] > rows * scale or f.getlength("0") > 8 * scale:
            return size
        size += step

BODY, BIG = "ABCArealMono-Bold.ttf", "DepartureMono-Regular.otf"
build("font_small", "ms-gothic.ttf", 12, 6, accents=False)   # 11 px squashes g/y descenders; its é loses the e
build("font_body", BODY, fit(BODY, 1), 8)
build("font_mid", BIG, 16.5, 12)
for s in BIG_SCALES:
    build("font_big%d" % s, BIG, fit(BIG, s, 11), 8 * s)
