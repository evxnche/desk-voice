# Focus timer: big countdown; KEY pauses/resumes, BOOT cancels, chime when it ends.
import time, math, struct
import dashboard, audio, palicon

active = False
paused = False
label = "Focus"
total_ms = 0
_end = 0              # ticks when it finishes (while running)
_left = 0             # ms remaining (while paused)

def start(minutes, name="Focus"):
    global active, paused, label, total_ms, _end
    total_ms = max(1, int(minutes * 60000))
    label = (name or "Focus")[:20]
    active, paused = True, False
    _end = time.ticks_add(time.ticks_ms(), total_ms)

def remaining():
    if not active:
        return 0
    return _left if paused else max(0, time.ticks_diff(_end, time.ticks_ms()))

def toggle_pause():
    global paused, _left, _end
    if not active:
        return
    if paused:
        _end = time.ticks_add(time.ticks_ms(), _left)
        paused = False
    else:
        _left = remaining()
        paused = True

def cancel():
    global active, paused
    active = paused = False

def finished():
    return active and not paused and remaining() == 0

def chime():
    """Two rising three-note phrases, loud enough to notice across a room."""
    n = audio.RATE // 7
    buf = bytearray(n * 2 * 7)
    i = 0
    for f in (660, 880, 1100, 0, 660, 880, 1320):
        step = 2 * math.pi * f / audio.RATE
        for k in range(n):
            fade = min(1, k / 300, (n - k) / 300)
            struct.pack_into("<h", buf, i, int(12000 * fade * math.sin(k * step)) if f else 0)
            i += 2
    audio.play(buf, volume=0xC8, mono=True)

def status():
    """Short text for the remote page, e.g. 'Focus 12:34' or 'Focus 12:34 (paused)'."""
    if not active:
        return ""
    s = remaining() // 1000
    return "%s %d:%02d%s" % (label, s // 60, s % 60, " (paused)" if paused else "")

def draw():
    d = dashboard.display()
    c = d.canvas
    d.clear(0)
    dashboard.header(d, label.lower())
    s = (remaining() + 999) // 1000
    text = "%d:%02d" % (s // 60, s % 60) if s < 3600 else "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60)
    scale = 11 if len(text) <= 4 else 9 if len(text) <= 5 else 6
    d.text_large(text, (400 - 8 * scale * len(text)) // 2, 70, scale)
    # progress bar fills as time passes
    done = total_ms - remaining()
    c.rect(20, 200, 360, 22, 1)
    c.fill_rect(22, 202, 356 * done // total_ms, 18, 1)
    if paused:
        d.text_large("PAUSED", 152, 240, 2)
    else:
        mins = total_ms // 60000
        d.text("%d minute %s" % (mins, label.lower()), 20, 246, 1)
    palicon.draw(c, 352, 236, "focus", time.ticks_ms() // 1000)
    c.fill_rect(0, 286, 400, 14, 1)
    d.text("KEY: %s   BOOT: cancel" % ("resume" if paused else "pause"), 4, 289, 0)
    d.show()

def draw_done():
    d = dashboard.display()
    d.clear(0)
    d.text_large("DONE!", 120, 60, 5)
    msg = "%d min %s complete" % (total_ms // 60000, label.lower())
    d.text_large(dashboard.ascii(msg)[:24], (400 - 16 * min(24, len(msg))) // 2, 150, 2)
    d.text("Take a short break.", 124, 190, 1)
    palicon.draw(d.canvas, 185, 220, "done")
    d.canvas.fill_rect(0, 286, 400, 14, 1)
    d.text("KEY or BOOT: dismiss", 4, 289, 0)
    d.show()
