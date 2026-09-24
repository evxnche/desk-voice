# Pixel screen: a little critter runs along the desk, hopping cacti under drifting clouds.
# It auto-plays like a screensaver ("demo") until KEY is tapped, then KEY is the jump button.
import framebuf, random, time
import dashboard

GROUND = 250
SPEED = 7

def sprite(rows, scale):
    w, h = len(rows[0]) * scale, len(rows) * scale
    buf = bytearray(((w + 7) // 8) * h)
    fb = framebuf.FrameBuffer(buf, w, h, framebuf.MONO_HLSB)
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c == "#":
                fb.fill_rect(x * scale, y * scale, scale, scale, 1)
    return fb, w, h

BODY = [
    "....####....",
    "..########..",
    ".##########.",
    ".##.####.##.",
    ".##.####.##.",
    "############",
    "############",
    ".##########.",
]
BLINK = BODY[:3] + [".##########.", ".##########."] + BODY[5:]
LEGS_A = ["..##....##..", ".##......##."]
LEGS_B = ["...##..##...", "...##..##..."]
LEGS_AIR = [".##......##.", "............"]

RUN = [sprite(BODY + LEGS_A, 4), sprite(BODY + LEGS_B, 4)]
RUN_BLINK = [sprite(BLINK + LEGS_A, 4), sprite(BLINK + LEGS_B, 4)]
JUMP = sprite(BODY + LEGS_AIR, 4)

CACTI = [
    sprite(["..##..", "..##..", "#.##..", "#.##.#", "####.#", "..####", "..##..", "..##..", "..##.."], 4),
    sprite([".##.", "####", ".##.", ".##.", ".##."], 4),
]
CLOUD = sprite(["...####...", ".##....##.", "#........#", ".########."], 4)

OVER_IDLE_MS = 8000    # game-over screen falls back to the self-playing demo after this

class Scene:
    def __init__(self):
        self.reset()
        self.mode = "demo"    # demo (auto-plays) -> play (KEY jumps) -> over (crashed)

    def reset(self):
        self.x = 60
        self.y = 0.0          # height above ground
        self.vy = 0.0
        self.frame = 0
        self.score = 0
        self.cacti = [[420, 0], [700, 1]]
        self.clouds = [[80, 60], [300, 95]]
        self.dots = [random.randint(0, 400) for _ in range(12)]

    def demo(self):
        """Back to the self-playing screensaver (used when the screen is entered)."""
        if self.mode != "demo":
            self.reset()
            self.mode = "demo"

    def press(self):
        """KEY went down on this screen."""
        if self.mode == "demo":
            self.reset()
            self.mode = "play"
        elif self.mode == "over":
            if time.ticks_diff(time.ticks_ms(), self.over_at) < 600:   # ignore the panic-tap that crashed you
                return
            self.reset()
            self.mode = "play"
        if self.y == 0:
            self.vy = 21.0

    def _hit(self):
        fb, w, h = RUN[0]
        top = GROUND - h - self.y
        for cx, kind in self.cacti:
            _, cw, chh = CACTI[kind]
            if cx < self.x + w - 8 and cx + cw > self.x + 8 and GROUND - chh < top + h - 4:
                return True
        return False

    def step(self):
        if self.mode == "over":
            if time.ticks_diff(time.ticks_ms(), self.over_at) > OVER_IDLE_MS:
                self.reset()
                self.mode = "demo"
            return
        self.frame += 1
        for c in self.cacti:
            c[0] -= SPEED
        if self.cacti[0][0] < -30:
            self.cacti.pop(0)
            self.score += 1
            self.cacti.append([max(420, self.cacti[-1][0] + random.randint(180, 360)), random.randint(0, 1)])
        for cl in self.clouds:
            cl[0] -= 1
            if cl[0] < -50:
                cl[0], cl[1] = 410, random.randint(50, 110)
        self.dots = [(d - SPEED) % 400 for d in self.dots]

        if self.mode == "demo":
            cx, kind = self.cacti[0]
            gap = cx - (self.x + RUN[0][1])
            if self.y == 0 and 0 < gap < 26:
                self.vy = 21.0
        if self.y > 0 or self.vy > 0:
            self.y += self.vy
            self.vy -= 2.6
            if self.y <= 0:
                self.y, self.vy = 0.0, 0.0
        if self.mode == "play" and self._hit():
            self.mode = "over"
            self.over_at = time.ticks_ms()

    def draw(self):
        d = dashboard.display()
        c = d.canvas
        c.fill(0)
        d.text_large("PIXEL PAL", 10, 8, 2)
        d.text_large("%05d" % self.score, 310, 8, 2)
        d.line(0, 32, 400, 32, 1)
        for x, y in self.clouds:
            c.blit(CLOUD[0], x, y, 0)
        c.hline(0, GROUND, 400, 1)
        for x in self.dots:
            c.hline(x, GROUND + 8 + (x % 3) * 6, 4, 1)
        for x, kind in self.cacti:
            fb, w, h = CACTI[kind]
            c.blit(fb, x, GROUND - h + 1, 0)
        if self.y > 0:
            fb, w, h = JUMP
        else:
            blink = self.mode == "over" or self.frame % 40 < 3
            fb, w, h = (RUN_BLINK if blink else RUN)[(self.frame // 3) % 2]
        c.blit(fb, self.x, GROUND - h + 1 - int(self.y), 0)
        if self.mode == "over":
            c.fill_rect(80, 70, 240, 90, 0)
            c.rect(80, 70, 240, 90, 1)
            d.text_large("GAME OVER", 128, 86, 2)
            d.text_large("score %d" % self.score, 200 - 8 * len("score %d" % self.score), 118, 2)
        c.fill_rect(0, 286, 400, 14, 1)
        if self.mode == "demo":
            hint = "KEY: play   BOOT: next screen   hold KEY: talk"
        elif self.mode == "play":
            hint = "KEY: jump   BOOT: next screen"
        else:
            hint = "KEY: play again   BOOT: next screen"
        d.text(hint, 4, 289, 0)
        d.show()

scene = Scene()
