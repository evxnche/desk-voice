# Pixel screen: a little critter runs along the desk, hopping cacti under drifting clouds.
import framebuf, random
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

class Scene:
    def __init__(self):
        self.x = 60
        self.y = 0.0          # height above ground
        self.vy = 0.0
        self.frame = 0
        self.score = 0
        self.cacti = [[420, 0], [700, 1]]
        self.clouds = [[80, 60], [300, 95]]
        self.dots = [random.randint(0, 400) for _ in range(12)]

    def step(self):
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

        cx, kind = self.cacti[0]
        gap = cx - (self.x + RUN[0][1])
        if self.y == 0 and 0 < gap < 26:
            self.vy = 19.0
        if self.y > 0 or self.vy > 0:
            self.y += self.vy
            self.vy -= 2.6
            if self.y <= 0:
                self.y, self.vy = 0.0, 0.0

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
            blink = self.frame % 40 < 3
            fb, w, h = (RUN_BLINK if blink else RUN)[(self.frame // 3) % 2]
        c.blit(fb, self.x, GROUND - h + 1 - int(self.y), 0)
        c.fill_rect(0, 286, 400, 14, 1)
        c.text("BOOT: next screen   KEY: refresh / hold to talk", 4, 289, 0)
        d.show()

scene = Scene()
