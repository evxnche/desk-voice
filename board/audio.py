# ES8311 (speaker DAC) + ES7210 (mic ADC) on the Waveshare ESP32-S3-RLCD-4.2.
# Register sequences ported from Espressif's esp_codec_dev (slave mode, 16-bit I2S,
# MCLK = 256 x fs). MicroPython's I2S has no MCLK output, so PWM drives GPIO16 at
# 4 MHz (80 MHz / 20, exact) and the rate is 4 MHz / 256 = 15625 Hz, which keeps
# the I2S clocks on the same exact ratio. Both codecs share BCLK/WS, so the
# board records and plays one after the other, never at once.
import math, struct, time, micropython, json
from machine import I2C, I2S, PWM, Pin
try:
    import wake          # built into Desk Pal's own firmware (firmware/); stock MicroPython has no wake word
except ImportError:
    wake = None

WAKE_PHRASES = ["gee gee"]  # "gg"; any English phrase works; "hey ava" wasn't waking it reliably
# How sure MultiNet must be. Evan's "gee gee" at the desk scored 0.14-0.18 (only when said loudly; the
# Mac's voice scores 0.3-0.4), so the default missed it. At 0.08, 1 false wake in 12 spoken sentences
# ("gigantic genes"); the server drops a wake whose transcript has no wake phrase. Extra spellings
# ("g g", "gigi") made it worse: 0 of 4.
WAKE_THRESHOLD = 0.08

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
        _pause_listener()                         # the listener holds I2S0 while idle
    _mclk()
    return I2S(0, sck=Pin(SCK), ws=Pin(WS), sd=Pin(sd), mode=mode,
               bits=16, format=fmt, rate=RATE, ibuf=ibuf)

_wake_ready = False                               # wake.init() run since the listener last stopped

def _pause_listener():
    """Stop the listener; the next listen() re-runs wake.init() (~10 ms), which also resets MultiNet.
    Restarted as it was, MultiNet was still mid-way through the last question and missed a wake phrase
    said right after the answer (2 of 3 tries on the board; 0 of 3 with the reset)."""
    global _wake_ready
    wake.stop()
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
            wake.threshold(WAKE_THRESHOLD)        # init makes a new MultiNet, at its default
        except Exception as e:                    # e.g. no speech model flashed: run without it
            print("wake phrase off:", e)
            wake = None
            return
        _wake_ready = True
    _mclk()
    if wake.start():
        _es7210_init()                            # needs BCLK, which wake.start() just started

_level_buf = bytearray(4096)

def level_now():
    """Mean |sample| of the newest ~0.1 s at the mic while the listener runs (quiet room ~5-10,
    talking at the desk 20-50), else None. Reads the listener's ring buffer; the audio isn't kept.
    Mean, not peak: a key tap or a knock peaks as high as a voice."""
    if not (wake and _wake_ready):
        return None
    last = 0
    while True:
        n = wake.read(_level_buf)
        if not n:
            break
        last = n
    if last < 1024:                               # too little new audio to judge (called too soon)
        return None
    return _mean_abs(memoryview(_level_buf)[last - 1024:last], 512)

def woke():
    """(phrase index, probability, background level, pre-roll bytes) once the wake phrase is heard."""
    return wake.heard() if wake else None

TX_BUF = 32000     # speaker buffer: ~1 s of mono voice, slack for screen redraws and download turns
starved = []       # gaps in the last play(): (chunk number, ms the speaker sat empty)

# Speaker volume 0 (silent) - 10, saved on the board; 7 plays each sound at the loudness it was tuned
# at, and each step is 3 dB (the ES8311's volume register moves 0.5 dB per unit).
VOLUME_FILE = "volume.json"
DEFAULT_VOLUME = 7
try:
    volume = json.load(open(VOLUME_FILE))["level"]
except Exception:
    volume = DEFAULT_VOLUME

def set_volume(level):
    global volume
    volume = max(0, min(10, int(level)))
    with open(VOLUME_FILE, "w") as f:
        json.dump({"level": volume}, f)
    return volume

def _volume_reg(tuned):
    """The ES8311 register value for a sound tuned at `tuned` (volume 7), at the current volume."""
    return 0 if volume == 0 else max(1, min(0xFF, tuned + (volume - DEFAULT_VOLUME) * 6))

def play(buf, volume=0xD0, mono=False, stop=None, between=None):
    """Play 16-bit PCM: a buffer, or an iterable of decoded chunks (voice.py).
    `stop()` is polled between chunks; returns False if it cut playback short.
    `between()` (keeping a screen up to date) runs after each 4 KB chunk, followed by a short
    sleep so other threads (screen fetches) run too. The buffer holds ~1 s of mono, so a chunk's
    between() plus waiting for audio may take up to ~0.8 s before you'd hear a gap.
    `starved` lists the gaps: chunks that came after everything queued had played (allowing for the
    ~50 ms the I2S DMA buffers add)."""
    global starved
    out = _i2s(I2S.TX, DOUT, I2S.MONO if mono else I2S.STEREO, TX_BUF)
    _es8311_init(_volume_reg(volume))
    pa(1)
    finished = True
    starved, queued, t0, per_ms, n = [], 0, None, RATE * (2 if mono else 4) / 1000, 0
    try:
        if isinstance(buf, (bytes, bytearray, memoryview)):
            mv = memoryview(buf)
            buf = (mv[i:i + 4096] for i in range(0, len(mv), 4096))
        for chunk in buf:
            if stop and stop():
                finished = False
                break
            now = time.ticks_ms()
            if t0 is None:
                t0 = now
            else:
                late = time.ticks_diff(now, t0) - queued / per_ms - 50
                if late > 0:                      # everything queued had played before this chunk
                    starved.append((n, int(late)))
                    t0, queued = now, 0           # a gap: time restarts from here
            out.write(chunk)
            queued += len(chunk)
            n += 1
            if between:
                between()
                time.sleep_ms(5)                  # yield without starving the speaker during screen draws
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

def record_while(pin, max_seconds, on_start=None, stop=None, progress=None):
    """Record mono while `pin` reads 0 (button held); return the bytes captured, or None if `stop()` fired.
    `progress(mv, n)` hears about each new block (voice.py uploads it as it's recorded)."""
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
            if progress:
                progress(mv, n)
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

def record_speech(max_seconds, heard, stop=None, progress=None):
    """After the wake phrase (`heard` from woke()): the listener's audio from 3 s before it was
    recognised, which holds the phrase and maybe the whole question ("gee gee, what's the weather"),
    until ~0.8 s of quiet follows speech, or 4 s pass with none. Speech = louder than 3x the room's
    background level (and than 15: in a quiet room speech measured only 20-50, so the old floor of 40
    cut questions short or waited out the 4 s). Returns mono PCM, or None if `stop()` fired.
    `progress(mv, n)` hears about each new frame (voice.py uploads it as it's recorded)."""
    floor, preroll = heard[2], heard[3]
    buf = bytearray(RATE * 2 * max_seconds)
    mv = memoryview(buf)
    loud = None
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
                if loud is None:
                    loud = max(3 * _background(mv, n, frame, floor), 15)
                    # Still talking when the phrase was recognised (MultiNet reports it ~2 s in, often
                    # mid-question)? Then that counts as speech, and it stops ~0.8 s after you do.
                    spoke = any(_mean_abs(mv[i:i + frame], frame // 2) > loud
                                for i in range(max(0, n - 6 * frame), n, frame))
                if _mean_abs(mv[n:n + frame], frame // 2) > loud:
                    spoke, quiet = True, 0
                else:
                    quiet += 1
            n += frame
            if progress:
                progress(mv, n)
            if quiet >= (12 if spoke else 62):    # 0.8 s after speech, or 4 s of none
                break
    finally:
        _pause_listener()                         # free core 0 for Wi-Fi while the reply comes back
    return mv[:n]

def mean_level(mv):
    """Mean |sample| of 16-bit PCM: ~5-10 for a quiet room at the mic, 20-50 for speech."""
    return _mean_abs(mv, len(mv) // 2)

def record_followup(max_seconds, wait_ms, stop=None, progress=None, on_start=None, waiting=None):
    """After an answer: wait up to `wait_ms` for you to start talking (no wake phrase needed), then
    record until ~0.8 s of quiet. Returns mono PCM from ~0.5 s before you started, or None if nobody
    spoke (or `stop()` fired). Reads the listener's ring buffer, so listen() must have started it.
    `on_start()` runs when speech starts, then `progress(mv, n)` hears about each frame;
    `waiting(fraction of the wait left)` is called while nothing has been said."""
    frame = 2048                                  # 64 ms
    buf = bytearray(RATE * 2 * max_seconds + RATE * 2 * wait_ms // 1000 + frame)
    mv = memoryview(buf)
    while wake.read(mv[:32768]):                  # skip what the ring holds from before now
        pass
    n, start, quiet = 0, None, 0
    levels, loud = [], 15
    t0 = time.ticks_ms()
    try:
        while n + frame <= len(buf):
            if stop and stop():
                return None
            if start is None:
                left = 1 - time.ticks_diff(time.ticks_ms(), t0) / wait_ms
                if left <= 0:
                    return None
                if waiting:
                    waiting(left)
            got = 0
            while got < frame:
                got += wake.read(mv[n + got:n + frame])
                if got < frame:
                    time.sleep_ms(20)
            lv = _mean_abs(mv[n:n + frame], frame // 2)
            n += frame
            if start is None:
                levels.append(lv)
                if len(levels) > 3:               # the mic's first frames after a restart are near silent
                    # 3x the room (as after the wake phrase) missed replies: a room at 18 put the bar at
                    # 54, over half the frames of a reply from across the desk (30-72).
                    quiet_room = sorted(levels[3:])[(len(levels) - 3) // 10]
                    loud = max(quiet_room * 3 // 2 + 6, 15)
                if len(levels) > 6 and sum(1 for v in levels[-4:] if v > loud) >= 3:   # ~0.2 s of speech
                    start = max(0, n - 11 * frame)
                    sub = mv[start:]
                    if on_start:
                        on_start()
                continue
            quiet = 0 if lv > loud else quiet + 1
            if progress:
                progress(sub, n - start)
            if quiet >= 12 or n - start >= RATE * 2 * max_seconds:
                break
    finally:
        _pause_listener()
    return None if start is None else mv[start:n]

def _background(mv, n, frame, floor):
    """The room's background level: the 10th-percentile frame of the 3 s pre-roll (mv[:n]). The listener's
    own `floor` (the quietest frame in the 5 s before the phrase) read 1-11 instead of ~35 if it had
    restarted in that time, e.g. for a follow-up right after an answer: the mic's first frames are near
    silent. Room noise then counted as speech and it recorded for the full 12 s."""
    levels = sorted(_mean_abs(mv[i:i + frame], frame // 2) for i in range(0, n - frame + 1, frame))
    return levels[len(levels) // 10] if levels else floor

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
