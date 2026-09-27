# ES8311 (speaker DAC) + ES7210 (mic ADC) on the Waveshare ESP32-S3-RLCD-4.2.
# Register sequences ported from Espressif's esp_codec_dev (slave mode, 16-bit I2S,
# MCLK = 256 x fs). MicroPython's I2S has no MCLK output, so PWM drives GPIO16 at
# 4 MHz (80 MHz / 20, exact) and the rate is 4 MHz / 256 = 15625 Hz, which keeps
# the I2S clocks on the same exact ratio. Both codecs share BCLK/WS, so the
# board records and plays one after the other, never at once.
import math, struct, time, micropython
from machine import I2C, I2S, PWM, Pin
try:
    import wake          # built into Desk Pal's own firmware (firmware/); stock MicroPython has no wake word
except ImportError:
    wake = None

WAKE_PHRASES = ["easy"]  # "EZ"; any English phrase works; longer ones wake it by accident less often

RATE = 15625
MCLK_HZ = RATE * 256
ES8311, ES7210 = 0x18, 0x40
SCK, WS, MCK, DOUT, DIN, PA = 9, 45, 16, 8, 10, 46

i2c = I2C(0, scl=Pin(14), sda=Pin(13), freq=100000)
pa = Pin(PA, Pin.OUT, value=0)

def w(addr, reg, val):
    i2c.writeto_mem(addr, reg, bytes([val & 0xFF]))

def r(addr, reg):
    return i2c.readfrom_mem(addr, reg, 1)[0]

def _es8311_init(volume):
    for reg, val in ((0x44, 0x08), (0x44, 0x08), (0x01, 0x30), (0x02, 0x00), (0x03, 0x10),
                     (0x16, 0x24), (0x04, 0x10), (0x05, 0x00), (0x0B, 0x00), (0x0C, 0x00),
                     (0x10, 0x1F), (0x11, 0x7F), (0x00, 0x80), (0x01, 0x3F)):
        w(ES8311, reg, val)
    w(ES8311, 0x06, r(ES8311, 0x06) & ~0x20)
    for reg, val in ((0x13, 0x10), (0x1B, 0x0A), (0x1C, 0x6A), (0x44, 0x58)):
        w(ES8311, reg, val)
    # I2S normal format, 16-bit
    w(ES8311, 0x09, (r(ES8311, 0x09) & 0xFC) | 0x0C)
    w(ES8311, 0x0A, (r(ES8311, 0x0A) & 0xFC) | 0x0C)
    # fs from MCLK = 256 x fs
    w(ES8311, 0x02, r(ES8311, 0x02) & 0x07)
    w(ES8311, 0x05, 0x00)
    w(ES8311, 0x03, (r(ES8311, 0x03) & 0x80) | 0x10)
    w(ES8311, 0x04, (r(ES8311, 0x04) & 0x80) | 0x20)
    w(ES8311, 0x07, r(ES8311, 0x07) & 0xC0)
    w(ES8311, 0x08, 0xFF)
    w(ES8311, 0x06, (r(ES8311, 0x06) & 0xE0) | 0x03)
    # start: DAC on, ADC off
    w(ES8311, 0x00, 0x80)
    w(ES8311, 0x01, 0x3F)
    w(ES8311, 0x09, r(ES8311, 0x09) & ~0x40)
    w(ES8311, 0x0A, r(ES8311, 0x0A) | 0x40)
    for reg, val in ((0x17, 0xBF), (0x0E, 0x02), (0x12, 0x00), (0x14, 0x1A), (0x0D, 0x01),
                     (0x15, 0x40), (0x37, 0x08), (0x45, 0x00)):
        w(ES8311, reg, val)
    w(ES8311, 0x32, volume)                       # 0xBF = 0 dB, 0xFF = +32 dB
    w(ES8311, 0x31, r(ES8311, 0x31) & 0x9F)       # unmute

def _es7210_mics(gain):
    for reg in (0x43, 0x44, 0x45, 0x46):
        w(ES7210, reg, r(ES7210, reg) & ~0x10)
    w(ES7210, 0x4B, 0xFF)
    w(ES7210, 0x4C, 0xFF)
    w(ES7210, 0x01, r(ES7210, 0x01) & ~0x0B)
    w(ES7210, 0x4B, 0x00)
    for reg in (0x43, 0x44):                      # MIC1 + MIC2
        w(ES7210, reg, (r(ES7210, reg) & ~0x1F) | 0x10 | gain)
    w(ES7210, 0x12, 0x00)                         # plain I2S, not TDM

def _es7210_init(gain=10):                        # gain step 10 = 30 dB
    for reg, val in ((0x00, 0xFF), (0x00, 0x41), (0x01, 0x3F), (0x09, 0x30), (0x0A, 0x30),
                     (0x23, 0x2A), (0x22, 0x0A), (0x20, 0x0A), (0x21, 0x2A)):
        w(ES7210, reg, val)
    w(ES7210, 0x08, r(ES7210, 0x08) & ~0x01)      # slave
    for reg, val in ((0x40, 0x43), (0x41, 0x70), (0x42, 0x70), (0x07, 0x20), (0x02, 0xC1)):
        w(ES7210, reg, val)
    _es7210_mics(gain)
    off = r(ES7210, 0x01)
    w(ES7210, 0x11, (r(ES7210, 0x11) & 0x1C) | 0x60)   # I2S normal, 16-bit
    w(ES7210, 0x01, off)
    w(ES7210, 0x06, 0x00)
    w(ES7210, 0x40, 0x43)
    for reg in (0x47, 0x48, 0x49, 0x4A):
        w(ES7210, reg, 0x08)
    _es7210_mics(gain)
    w(ES7210, 0x40, 0x43)
    w(ES7210, 0x00, 0x71)
    w(ES7210, 0x00, 0x41)
    w(ES7210, 0x14, r(ES7210, 0x14) & ~0x03)      # unmute
    w(ES7210, 0x15, r(ES7210, 0x15) & ~0x03)

mclk = None

def _mclk():
    global mclk
    if mclk is None:
        mclk = PWM(Pin(MCK), freq=MCLK_HZ, duty_u16=32768)

def _i2s(mode, sd, fmt=I2S.STEREO, ibuf=40000):
    if wake:
        wake.stop()                               # the listener holds I2S0 while idle
    _mclk()
    return I2S(0, sck=Pin(SCK), ws=Pin(WS), sd=Pin(sd), mode=mode,
               bits=16, format=fmt, rate=RATE, ibuf=ibuf)

_wake_ready = False

def listen():
    """Keep the wake-phrase listener running; call often. Anything that plays or records pauses it
    (via _i2s) and the next call here resumes it."""
    global _wake_ready, wake
    if wake is None:
        return
    if not _wake_ready:
        try:
            wake.init(WAKE_PHRASES)
        except Exception as e:                    # e.g. no speech model flashed: run without it
            print("wake phrase off:", e)
            wake = None
            return
        _wake_ready = True
    _mclk()
    if wake.start():
        _es7210_init()                            # needs BCLK, which wake.start() just started

def woke():
    """(phrase index, probability, background level, pre-roll bytes) once the wake phrase is heard."""
    return wake.heard() if wake else None

TX_BUF = 16000

def play(buf, volume=0xD0, mono=False, stop=None):
    """Play 16-bit PCM. `stop()` is polled between chunks; returns False if it cut playback short."""
    out = _i2s(I2S.TX, DOUT, I2S.MONO if mono else I2S.STEREO, TX_BUF)
    _es8311_init(volume)
    pa(1)
    finished = True
    try:
        mv = memoryview(buf)
        for i in range(0, len(buf), 4096):
            if stop and stop():
                finished = False
                break
            out.write(mv[i:i + 4096])
        if finished:
            # write() returns once data is queued, not played: push a full buffer of
            # silence so the queued audio drains before the amp switches off.
            out.write(bytearray(TX_BUF + 4096))
    finally:
        pa(0)
        out.deinit()
    return finished

def record(seconds):
    buf = bytearray(RATE * 4 * seconds)           # stereo 16-bit
    mic = _i2s(I2S.RX, DIN)
    _es7210_init()
    try:
        junk = bytearray(4096)
        for _ in range(4):                        # drop the startup click
            mic.readinto(junk)
        mic.readinto(buf)
    finally:
        mic.deinit()
    return buf

def record_while(pin, max_seconds, on_start=None, stop=None):
    """Record mono while `pin` reads 0 (button held); return the bytes captured, or None if `stop()` fired."""
    buf = bytearray(RATE * 2 * max_seconds)
    mv = memoryview(buf)
    mic = _i2s(I2S.RX, DIN, I2S.MONO)
    _es7210_init()
    n = 0
    try:
        junk = bytearray(2048)
        for _ in range(4):                        # drop the startup click
            mic.readinto(junk)
        if on_start:
            on_start()                            # I2S buffers ~1 s while this draws
        while n < len(buf) and not pin.value():
            if stop and stop():
                return None
            n += mic.readinto(mv[n:n + 2048])
    finally:
        mic.deinit()
    return mv[:n]

@micropython.viper
def _mean_abs(buf: ptr16, n: int) -> int:
    total = 0
    for i in range(n):
        v = int(buf[i])
        if v >= 32768:
            v = 65536 - v
        total += v
    return total // n if n else 0

def record_speech(max_seconds, heard, stop=None):
    """After the wake phrase (`heard` from woke()): the listener's audio from 3 s before it was
    recognised, which holds the phrase and maybe the whole question ("easy, what's the weather"),
    until ~0.8 s of quiet follows new speech, or 4 s pass with none. Speech = louder than 3x the
    room's background level. Returns mono PCM, or None if `stop()` fired."""
    floor, preroll = heard[2], heard[3]
    buf = bytearray(RATE * 2 * max_seconds)
    mv = memoryview(buf)
    loud = max(3 * floor, 40)
    n = 0
    spoke = False
    quiet = 0                                     # quiet 64 ms frames since the last loud one
    frame = 2048                                  # bytes: 1024 samples, 64 ms
    try:
        while n + frame <= len(buf):
            if stop and stop():
                return None
            got = 0
            while got < frame:                    # read() never blocks; fill one frame
                got += wake.read(mv[n + got:n + frame])
                if got < frame:
                    time.sleep_ms(20)
            if n >= preroll:                      # only speech after the phrase decides when to stop
                if _mean_abs(mv[n:n + frame], frame // 2) > loud:
                    spoke, quiet = True, 0
                else:
                    quiet += 1
            n += frame
            if quiet >= (12 if spoke else 62):    # 0.8 s after speech, or 4 s of none
                break
    finally:
        wake.stop()                               # free core 0 for Wi-Fi while the reply comes back
    return mv[:n]

def tone(freqs=(523, 659, 784), ms=250, amp=9000):
    n = RATE * ms // 1000
    buf = bytearray(n * 4 * len(freqs))
    i = 0
    for f in freqs:
        step = 2 * math.pi * f / RATE
        for k in range(n):
            fade = min(1, k / 400, (n - k) / 400)
            s = int(amp * fade * math.sin(k * step))
            struct.pack_into("<hh", buf, i, s, s)
            i += 4
    return buf

def level(buf):
    """Peak of the louder channel as 0-100 (percent of full scale)."""
    peak = 0
    for i in range(0, len(buf) - 3, 16):         # sample every 4th frame; plenty for a meter
        l, rr = struct.unpack_from("<hh", buf, i)
        a = max(abs(l), abs(rr))
        if a > peak:
            peak = a
    return peak * 100 // 32768

@micropython.viper
def _scale(buf: ptr16, n: int, gain: int):
    for i in range(n):
        v = int(buf[i])
        if v >= 32768:
            v -= 65536
        v = (v * gain) >> 8
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        buf[i] = v & 0xFFFF

def boost(buf, peak_pct):
    """Amplify a quiet recording in place so the playback peaks near 70%."""
    gain = 256 * 70 // max(peak_pct, 1)
    _scale(buf, len(buf) // 2, min(gain, 256 * 30))
