import time
from machine import Pin, SPI
import framebuf
import micropython
import font5, bitfont

class RLCD:
    def __init__(self, spi, cs, dc, rst, width=400, height=300):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.rst = rst
        self.width = width
        self.height = height
        
        # 1. Hardware Buffer (The weird format the screen needs)
        self.hw_len = (self.width * self.height) // 8
        self.hw_buffer = bytearray(self.hw_len)

        # 2. Virtual Canvas (Standard format for drawing lines, text, bitmaps)
        # We use MONO_HLSB (Standard Horizontal Byte layout)
        self.canvas_buffer = bytearray(self.hw_len)
        self.canvas = framebuf.FrameBuffer(self.canvas_buffer, self.width, self.height, framebuf.MONO_HLSB)
        
        # Init Pins
        self.cs.init(self.cs.OUT, value=1)
        self.dc.init(self.dc.OUT, value=0)
        self.rst.init(self.rst.OUT, value=1)
        
        self.reset()
        self.init_display()

    # --- DRAWING WRAPPERS ---
    def pixel(self, x, y, c): self.canvas.pixel(x, y, c)
    def line(self, x1, y1, x2, y2, c): self.canvas.line(x1, y1, x2, y2, c)
    def rect(self, x, y, w, h, c): self.canvas.rect(x, y, w, h, c)
    def fill_rect(self, x, y, w, h, c): self.canvas.fill_rect(x, y, w, h, c)
    def text(self, msg, x, y, c=1): bitfont.get("font_body").text(self.canvas, msg.lower() if font5.lowercase else msg, x, y, c)
    def clear(self, c=0): self.canvas.fill(c)

    # --- LARGE TEXT: an 8*scale px cell per char, same grid as the old scaled 8x8 font ---
    def text_large(self, msg, x, y, scale=2, c=1):
        if font5.lowercase:
            msg = msg.lower()
        bitfont.get("font_big%d" % scale).text(self.canvas, msg, x, y, c)

    # --- RAW BITMAPS (1:1 scale) ---
    def bitmap(self, x, y, w, h, pixel_data):
        img = framebuf.FrameBuffer(pixel_data, w, h, framebuf.MONO_HLSB)
        self.canvas.blit(img, x, y)

    # --- PBM FILE LOADER WITH SCALING (NEW!) ---
    def draw_pbm(self, filename, x, y, scale=1):
        try:
            with open(filename, 'rb') as f:
                line1 = f.readline()
                if not line1.startswith(b'P4'): print("Err: Not P4 PBM"); return
                while True:
                    line = f.readline()
                    if not line.startswith(b'#'): break
                dims = line.split(); w = int(dims[0]); h = int(dims[1])
                data = bytearray(f.read())
                
                # Create temp buffer for source image
                src_fb = framebuf.FrameBuffer(data, w, h, framebuf.MONO_HLSB)
                
                if scale == 1:
                     self.canvas.blit(src_fb, x, y) # Fast path
                else:
                    # Slow path: iterate pixels and draw scaled rects
                    for sy in range(h):
                        for sx in range(w):
                            if src_fb.pixel(sx, sy):
                                self.canvas.fill_rect(x + (sx * scale), y + (sy * scale), scale, scale, 1)
                print(f"Loaded {filename} (scale {scale})")
        except OSError:
            print(f"Error: Could not open {filename}")

    # --- SCREENSHOT ---
    def save_screenshot(self, filename):
        print(f"Saving screenshot to {filename}...")
        try:
            with open(filename, 'wb') as f:
                f.write(b'P4\n')
                f.write(f"{self.width} {self.height}\n".encode())
                f.write(self.canvas_buffer)
            print("Saved!")
        except Exception as e:
            print(f"Error saving screenshot: {e}")

    # --- HARDWARE LOGIC ---
    def reset(self):
        self.rst(1); time.sleep_ms(50); self.rst(0); time.sleep_ms(20); self.rst(1); time.sleep_ms(50)

    def write_cmd(self, cmd):
        self.cs(0); self.dc(0); self.spi.write(bytearray([cmd])); self.cs(1)

    def write_data(self, data):
        self.cs(0); self.dc(1)
        if isinstance(data, int): self.spi.write(bytearray([data]))
        elif isinstance(data, list): self.spi.write(bytearray(data))
        else: self.spi.write(data)
        self.cs(1)

    def init_display(self):
        self.write_cmd(0xD6); self.write_data(0x17); self.write_data(0x02)
        self.write_cmd(0xD1); self.write_data(0x01)
        self.write_cmd(0xC0); self.write_data(0x11); self.write_data(0x04)
        # Source voltages, oscillator and frame rate are Waveshare's values for this
        # 4.2" panel. The old ones (0x41/0xA6/0x05, and a decimal 19 typo in C5)
        # matched no reference driver; suspected cause of bands of dark lines that came and went.
        self.write_cmd(0xC1); self.write_data([0x69, 0x69, 0x69, 0x69])
        self.write_cmd(0xC2); self.write_data([0x19, 0x19, 0x19, 0x19])
        self.write_cmd(0xC4); self.write_data([0x4B, 0x4B, 0x4B, 0x4B])
        self.write_cmd(0xC5); self.write_data([0x19, 0x19, 0x19, 0x19])
        self.write_cmd(0xD8); self.write_data(0x80); self.write_data(0xE9)
        self.write_cmd(0xB2); self.write_data(0x02)
        self.write_cmd(0xB3); self.write_data([0xE5, 0xF6, 0x05, 0x46, 0x77, 0x77, 0x77, 0x77, 0x76, 0x45])
        self.write_cmd(0xB4); self.write_data([0x05, 0x46, 0x77, 0x77, 0x77, 0x77, 0x76, 0x45])
        self.write_cmd(0x62); self.write_data([0x32, 0x03, 0x1F])
        self.write_cmd(0xB7); self.write_data(0x13)
        self.write_cmd(0xB0); self.write_data(0x64)
        self.write_cmd(0x11); time.sleep_ms(200)
        self.write_cmd(0xC9); self.write_data(0x00)
        self.write_cmd(0x36); self.write_data(0x48) 
        self.write_cmd(0x3A); self.write_data(0x11) 
        self.write_cmd(0xB9); self.write_data(0x20)
        self.write_cmd(0xB8); self.write_data(0x29)
        self.write_cmd(0x20) # Inversion OFF (White Background)
        self.write_cmd(0x2A); self.write_data([0x12, 0x2A])
        self.write_cmd(0x2B); self.write_data([0x00, 0xC7])
        self.write_cmd(0x35); self.write_data(0x00)
        self.write_cmd(0xD0); self.write_data(0xFF)
        self.write_cmd(0x38); self.write_cmd(0x29)

    # --- THE HEAVY LIFTER ---
    # Viper rewrite: walks the panel's byte layout (2 px wide x 4 px tall per byte,
    # columns bottom-up) and pulls bits straight from the MONO_HLSB canvas.
    # ~20x faster than the per-pixel canvas.pixel() loop it replaces.
    def show(self):
        _to_panel(self.canvas_buffer, self.hw_buffer)
        self.write_cmd(0x2A); self.write_data(0x12); self.write_data(0x2A)
        self.write_cmd(0x2B); self.write_data(0x00); self.write_data(0xC7)
        self.write_cmd(0x2C)
        self.cs(0); self.dc(1)
        self.spi.write(self.hw_buffer)
        self.cs(1)

@micropython.viper
def _to_panel(src: ptr8, dst: ptr8):
    for bx in range(200):
        sbyte = bx >> 2
        sh0 = 7 - ((bx << 1) & 7)
        sh1 = sh0 - 1
        for by in range(75):
            v = 0
            row = (299 - (by << 2)) * 50 + sbyte
            for ly in range(4):
                b = int(src[row - ly * 50])
                v |= (((b >> sh0) & 1) << (7 - (ly << 1))) | (((b >> sh1) & 1) << (6 - (ly << 1)))
            dst[bx * 75 + by] = v
