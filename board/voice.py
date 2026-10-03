# Voice assistant: record while KEY is held (or after the wake phrase, until you stop talking),
# send to desk-voice, show + speak the reply.
import json, time, requests, _thread, socket, ssl, network, binascii
import adpcm, audio, secrets, flights, music, home, phone, pal, tracker, memories, alerts, schedule, plan, mac

MAX_SECONDS = 12
URL = secrets.VOICE_URL + "?k=" + secrets.VOICE_KEY
FOLLOWUP_MS = 6000        # after an answer, how long it listens for a reply without "gee gee"
REPLY_TIMEOUT = 310      # server allows 300 s to generate longer answers and speech

# Conversation memory: the last few exchanges go with each question so "and tomorrow?" makes sense.
# Kept in RAM on the board only (a restart clears it) and sent to desk-voice with the question.
HISTORY_TURNS = 6
HISTORY_MS = 10 * 60 * 1000
history = []              # [(ticks_ms, question, answer)], newest last; question "" = it spoke up itself

def remember(question, answer):
    history.append((time.ticks_ms(), question, answer[:400]))
    del history[:-HISTORY_TURNS]

def _recent():
    now = time.ticks_ms()
    return [[q, a] for at, q, a in history if time.ticks_diff(now, at) < HISTORY_MS]

# Spanish practice ("gee gee, let's practice Spanish"): desk-voice answers as a tutor while this is on.
# Ends on "stop practicing", or HISTORY_MS after the last practice exchange.
PRACTICE_FOLLOWUP_MS = 15000   # longer to think of a reply in Spanish
_practice_at = None

def practicing():
    return _practice_at is not None and time.ticks_diff(time.ticks_ms(), _practice_at) < HISTORY_MS

def _context_header(value):
    return binascii.b2a_base64(json.dumps(value).encode()).decode().strip()

def _headers(wake, followup=False):
    hdrs = {"X-Audio": "adpcm"}       # ADPCM both ways: a quarter of the bytes of 16-bit PCM
    if wake:
        hdrs["X-Wake"] = wake         # the recording starts with this phrase; the server checks it's there
    if followup:
        hdrs["X-Followup"] = "1"      # a reply with no wake phrase: silence or noise is ignored, not answered
    recent = _recent()
    if recent:
        hdrs["X-History"] = _context_header(recent)
    saved = memories.list_all()
    if saved:
        encoded = _context_header(saved)
        while len(encoded) > 2500 and len(saved) > 1:
            saved.pop(0)
            encoded = _context_header(saved)
        if len(encoded) <= 2500:
            hdrs["X-Memories"] = encoded
    alert = alerts.latest_needs()
    if alert:
        limited = {"kind": "needs", "agent": str(alert.get("agent", ""))[:80],
                   "project": str(alert.get("project", ""))[:80],
                   "message": str(alert.get("message", ""))[:500],
                   "at": str(alert.get("at", ""))[:16]}
        encoded = _context_header(limited)
        for field in ("message", "project", "agent"):
            while len(encoded) > 1800 and limited[field]:
                limited[field] = limited[field][:-20]
                encoded = _context_header(limited)
        if len(encoded) <= 1800:
            hdrs["X-Agent-Alert"] = encoded
    hdrs.update(music.headers())      # lets "play something chill" reach Spotify
    hdrs.update(tracker.headers())    # "how's the flight doing?"
    hdrs.update(schedule.headers())   # "what's on today?"
    hdrs.update(plan.headers())       # "what's on my list?"
    hdrs.update(mac.headers())        # "lock my Mac", "what's Claude doing?"
    hdrs["X-Volume"] = str(audio.volume)   # "turn it up a bit"
    if practicing():
        hdrs["X-Practice"] = "es"
    return hdrs

def _request(data, box, hdrs, url=None):
    """Worker thread: POST `data` (the recording as 4-bit ADPCM, or text for /api/say), fill `box`,
    set box['done']."""
    try:
        hdrs = dict(hdrs, **{"Content-Type": "application/octet-stream"})
        r = requests.post(url or (URL + flights.params() + home.query()), data=data, timeout=REPLY_TIMEOUT, headers=hdrs)
        box["status"] = r.status_code
        size = int({k.lower(): v for k, v in r.headers.items()}.get("content-length", 0))
        try:
            body = _read_body(r.raw, size) if size else r.content
        finally:
            r.close()
        box["body"] = body
    except Exception as e:
        box["error"] = str(e)
    box["done"] = True

def _read_head(s):
    """Status code and Content-Length (None if absent) of an HTTP response."""
    status = int(s.readline().split(None, 2)[1])
    length = None
    while True:
        line = s.readline()
        if not line or line == b"\r\n":
            return status, length
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value)

def _read_body(s, length, stop=None):
    if length is None:                            # Connection: close, so the body runs to EOF
        body = bytearray()
        while True:
            if stop and stop():
                raise OSError("Reply canceled")
            b = s.read(16384)
            if not b:
                return body
            body += b
    body = bytearray(length)
    mv, got = memoryview(body), 0
    while got < length:
        if stop and stop():
            raise OSError("Reply canceled")
        n = s.readinto(mv[got:got + 16384])
        if not n:
            raise OSError("Incomplete reply: %d of %d bytes" % (got, length))
        got += n
    return body

class _Stream:
    """Sends the question while you're still asking it. A worker thread connects (TLS) and pings the
    server awake (a cold function takes ~0.6-0.9 s longer) the moment recording starts, then uploads
    the ADPCM as it's recorded (chunked), so when you stop only the last ~0.5 s is left to send.
    Raises OSError if no thread fits; ask() then sends the whole recording afterwards as before."""
    def __init__(self, hdrs):
        self.mv, self.n, self.end, self.quit, self.box = None, 0, None, False, {}
        host, path = URL.split("/")[2], "/" + URL.split("/", 3)[3]
        self.host, self.path = host, path
        self.post = ("POST %s%s%s HTTP/1.1\r\nHost: %s\r\nContent-Type: application/octet-stream\r\n%s"
                     "Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n" % (
                         path, flights.params(), home.query(), host,
                         "".join("%s: %s\r\n" % kv for kv in hdrs.items()))).encode()
        _thread.stack_size(20 * 1024)
        _thread.start_new_thread(self._run, ())

    def progress(self, mv, n):                    # called by the recorder after each block
        self.mv, self.n = mv, n

    def _connect(self):
        s = socket.socket()
        s.settimeout(REPLY_TIMEOUT)
        s.connect(socket.getaddrinfo(self.host, 443)[0][-1])
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_NONE           # as requests does on this board: no CA bundle here
        return ctx.wrap_socket(s, server_hostname=self.host)

    def _run(self):
        box, s = self.box, None
        try:
            s = self._connect()
            s.write(("GET %s HTTP/1.1\r\nHost: %s\r\n\r\n" % (self.path, self.host)).encode())
            status, length = _read_head(s)
            if status != 204 and length is None:  # can't tell where that reply ends: start afresh
                s.close()
                s = self._connect()
            elif length:
                _read_body(s, length)
            s.write(self.post)
            enc, sent = adpcm.Encoder(), 0
            while not self.quit:
                end = self.end
                n = self.n if end is None else end
                if end is None:
                    if n - sent < 16000:          # send ~0.5 s at a time while recording
                        time.sleep_ms(30)
                        continue
                    n -= (n - sent) % 4           # whole sample pairs, so the ADPCM bytes split evenly
                if n > sent:
                    piece = enc.encode(self.mv[sent:n])
                    s.write(("%x\r\n" % len(piece)).encode())
                    s.write(piece)
                    s.write(b"\r\n")
                    sent = n
                if end is not None:
                    s.write(b"0\r\n\r\n")
                    status, length = _read_head(s)
                    if status != 200 or not length:
                        box["body"], box["status"] = _read_body(s, length, stop=lambda: self.quit), status
                        break
                    # ask() starts speaking once ~1 s of the reply is in and plays the rest as it arrives
                    body = bytearray(length)
                    box["body"], box["got"], box["status"] = body, 0, status
                    mv, got = memoryview(body), 0
                    while got < length and not self.quit:
                        n = s.readinto(mv[got:got + 4096])
                        if not n:
                            raise OSError("Incomplete reply: %d of %d bytes" % (got, length))
                        got += n
                        box["got"] = got
                    break
        except Exception as e:
            box["error"] = str(e) or repr(e)
        finally:
            if s:
                s.close()
            box["done"] = True

def _head_end(body):
    """Find the JSON line without copying the audio or limiting long answer text to 4 KB."""
    for start in range(0, len(body), 1024):
        at = bytes(body[start:start + 1024]).find(b"\n")
        if at >= 0:
            return start + at
    raise OSError("Reply metadata is missing")

def _enough(box):
    """True once the reply's first line and ~1 s of its ADPCM audio have arrived."""
    got = box.get("got", 0)
    try:
        nl = _head_end(memoryview(box["body"])[:got]) if got else -1
    except OSError:
        return False
    return nl >= 0 and (got - nl - 1 >= 8000 or got == len(box["body"]))

def _arriving(box, start):
    """16-bit PCM of a reply still downloading, ~0.13 s at a time, waiting for more as needed. No
    pause while audio is ready: the speaker must be fed faster than it plays, and the download thread
    gets its turns while audio.play() waits for room in the speaker buffer."""
    dec, body, pos = adpcm.Decoder(), box["body"], start
    while True:
        got, done = box.get("got", 0), "done" in box
        if got - pos >= 1024 or (done and got > pos):
            end = min(got, pos + 1024)
            yield dec.decode(memoryview(body)[pos:end])
            pos = end
        elif done:
            if "error" in box:                        # the connection dropped: stop, don't pad
                print("reply cut short:", box["error"])
            return
        else:
            time.sleep_ms(10)

def _decoded(body, start):
    """Decode completed ADPCM in small pieces; a long reply never needs a full PCM copy."""
    dec, mv = adpcm.Decoder(), memoryview(body)
    for pos in range(start, len(body), 1024):
        yield dec.decode(mv[pos:pos + 1024])

def _start_stream(hdrs):
    if not network.WLAN(network.STA_IF).isconnected():
        return None                               # ask() joins Wi-Fi after recording, as before
    try:
        return _Stream(hdrs)
    except OSError:                               # no stack fits right now
        return None

class _Face:
    """The Pal while a question is on: listening (bars follow your voice), thinking, then speaking with
    its mouth following its own voice. Frames are paced to ~10 a second."""
    def __init__(self, keep=False):
        self.keep = keep          # over a screen an answer opened: the header Pal, not the full one
        self.bars, self.next, self.levels, self.caption = [], 0, [], []
        self.lines, self.page, self.played, self.total, self.huh = [], [], 0, 0, False

    def _due(self, ms=100):
        now = time.ticks_ms()
        if time.ticks_diff(now, self.next) < 0:
            return False
        self.next = time.ticks_add(now, ms)
        return True

    def listening(self, mv=None, n=0):
        if n >= 2048:
            self.bars.append(min(1.0, audio.mean_level(mv[n - 2048:n]) / 80))
            del self.bars[:-25]
        if self._due():
            if self.keep:
                pal.header("listen")
            else:
                pal.draw("listen", self.bars[-1] if self.bars else 0, self.caption, bars=self.bars)

    def thinking(self):
        if self._due(150 if self.keep else 100):
            if self.keep:
                pal.header("think")
            else:
                pal.draw("think")

    def waiting(self, left):
        if self._due(200):
            if self.keep:
                pal.header("wait", left=left)
            else:
                pal.draw("waiting", left)

    def speaking(self, reply, huh, total):
        """First speaking frame. `total`: bytes of PCM to come (0 if unknown), to page long captions."""
        self.lines = pal.wrap(reply) if pal.CAPTIONS and not self.keep else []
        self.huh, self.total, self.played, self.levels = huh, total, 0, []
        self.page = pal.caption_page(self.lines, 0)
        if self.keep:
            self.next = 0
            pal.header("talk")
        else:
            pal.draw("huh" if huh else "speak", 0, self.page)

    def voiced(self, chunks):
        """Pass the reply's PCM through, noting each chunk's loudness for the mouth."""
        for chunk in chunks:
            self.levels.append(audio.mean_level(chunk))
            del self.levels[:-(audio.TX_BUF // 4096)]
            self.played += len(chunk)
            yield chunk

    def mouth(self):
        """Between chunks (~0.13 s of voice each). What you hear now was queued `lag` chunks ago: the
        speaker buffer holds that much."""
        lag = audio.TX_BUF // 4096
        level = min(1.0, (self.levels[-lag] if len(self.levels) >= lag else 0) / 3000)
        if self.keep:
            if self._due(250):                       # ~4 frames a second is plenty at this size
                pal.header("talk", level)
            return
        page = self.page
        if self.total:
            page = pal.caption_page(self.lines, max(0, self.played - audio.TX_BUF) / self.total)
        if page != self.page:
            self.page = page
            pal.draw("huh" if self.huh else "speak", level, page)
        else:
            pal.speak_update(level, self.huh)

def _chunks(buf):
    mv = memoryview(buf)
    for i in range(0, len(mv), 4096):
        yield mv[i:i + 4096]

def _problem(text, back):
    """Show what went wrong under a puzzled Pal for a few seconds (BOOT skips)."""
    pal.draw("huh", caption=pal.wrap(text))
    end = time.ticks_add(time.ticks_ms(), 5000)
    while time.ticks_diff(end, time.ticks_ms()) > 0 and not back():
        time.sleep_ms(50)

def _run_board_commands(cmds, run):
    global _practice_at
    problem = None
    for cmd in cmds:
        if cmd.get("do") == "practice":
            _practice_at = time.ticks_ms() if cmd.get("on") else None
            continue
        result = run(cmd)
        if result is False and cmd.get("do") == "memory_add":
            problem = "Memory not saved"
        elif result is False and cmd.get("do") in ("memory_delete", "memory_clear"):
            problem = "Memory not removed"
        elif result is False and cmd.get("do") == "mac":
            problem = "Mac not connected"
    return problem

def _sound(box, body, nl):
    """The reply's audio as PCM chunks, and how many PCM bytes there are in all."""
    if box.get("adpcm") is False:                   # plain PCM (an older server)
        return _chunks(memoryview(body)[nl + 1:]), len(body) - nl - 1
    total = (len(body) - nl - 1) * 4
    if "got" in box:
        return _arriving(box, nl + 1), total        # decode and play it as it downloads
    return _decoded(body, nl + 1), total

def _post(job, box, back, face):
    """Run _request(*job) on a worker thread (the main thread if no stack fits) while the Pal thinks.
    False if BOOT was pressed."""
    try:
        # TLS needs more than the default stack; 20 KB is plenty (tested on the board), and a task
        # stack must be one block of internal RAM, which Bluetooth (phone.py) shares.
        _thread.stack_size(20 * 1024)
        _thread.start_new_thread(_request, job)
    except OSError:
        # No block big enough for the stack ("can't create thread"): ask from this thread instead.
        # BOOT then only works once the answer is back.
        _request(*job)
    while "done" not in box:                     # the worker keeps going if we leave; its result is dropped
        if back():
            return False
        face()
        time.sleep_ms(20)
    return True

def _speak(sound, back, tapped, between):
    """Play a reply: "done", "back" (BOOT) or "interrupt" (KEY tapped: stop talking and listen)."""
    if tapped:
        tapped()                                     # forget the press that asked the question
    why = []
    def stop():
        if back():
            why.append("back")
        elif tapped and tapped():
            why.append("interrupt")
        return bool(why)
    if audio.play(sound, volume=0xBF, mono=True, stop=stop, between=between):
        return "done"
    return why[0] if why else "back"

def ask(key, boot, connect, run, tick, heard=None, followup=False, keep_screen=False, tapped=None,
        opened=None):
    """One question: record while `key` is held, or after the wake phrase when `heard` (audio.woke())
    is given, or with `followup`, whatever you say in the FOLLOWUP_MS after an answer (no wake phrase;
    `keep_screen`: an earlier answer opened the screen that's up, and the little header Pal listens,
    thinks and speaks over it; `opened()` says whether an answer has opened a screen, so this one's
    reply goes over it the same way). Otherwise the Pal listens, thinks, then speaks the
    reply with its words underneath. If the reply comes with board commands (a screen for the weather,
    flights or music, a timer...) they `run` first, `tick(False)` draws that screen, and the reply is
    spoken over it with `tick(True)` keeping it up to date. `tapped()` (True once per KEY press)
    stops the reply so you can talk.
    Returns "back" as soon as `boot` is pressed at any stage, "quiet" if no follow-up came, None after
    a problem or a slip of the KEY, "interrupt" if KEY cut the reply short, else {"board": [commands run]}."""
    back = lambda: not boot.value()
    face = _Face(keep_screen)
    if heard:
        face.listening()                             # show it heard you before the headers and connection
    wake = audio.WAKE_PHRASES[heard[0]] if heard else ""
    hdrs = _headers(wake, followup)
    streams = []                                     # the upload that starts as you start talking
    def on_audio(mv, n):
        if streams and streams[0]:
            streams[0].progress(mv, n)
        face.listening(mv, n)
    phone.hush(True)                                 # Bluetooth advertising slows Wi-Fi 2-8x
    try:
        if followup:
            while not key.value():                   # let go of the KEY that interrupted the last reply
                time.sleep_ms(10)
            audio.listen()                           # its ring buffer holds whatever you say next
            pcm = audio.record_followup(MAX_SECONDS, PRACTICE_FOLLOWUP_MS if practicing() else FOLLOWUP_MS, stop=lambda: back() or not key.value(),
                                        progress=on_audio, on_start=lambda: streams.append(_start_stream(hdrs)),
                                        waiting=face.waiting)
            if pcm is None:
                return "back" if back() or not key.value() else "quiet"
        else:
            streams.append(_start_stream(hdrs))
            if heard:
                pcm = audio.record_speech(MAX_SECONDS, heard, stop=back, progress=on_audio)
            else:
                face.caption = ["let go of KEY to send"]
                pcm = audio.record_while(key, MAX_SECONDS, stop=back, progress=on_audio, on_start=face.listening)
        stream = streams[0] if streams else None
        if pcm is None or back() or len(pcm) < audio.RATE * 2 // 2:   # under half a second: a slip
            if stream:
                stream.quit = True
            return "back" if pcm is None or back() else None
        face.next = 0
        face.thinking()
        box = {}
        if stream:
            stream.end = len(pcm)                    # the worker sends the last piece and waits for the reply
            box = stream.box
            while "done" not in box and not _enough(box):
                if back():
                    stream.quit = True
                    return "back"
                face.thinking()
                time.sleep_ms(20)
            if "error" in box and "got" not in box:  # streaming broke before the reply: send it all again
                box = {}
        if not box:
            if not connect():
                _problem("No Wi-Fi", back)
                return None
            if not _post((adpcm.encode(pcm), box, hdrs), box, back, face.thinking):
                return "back"
        if "error" in box:
            _problem("Couldn't reach the assistant: %s" % box["error"], back)
            return None
        body = box["body"]
        if box["status"] != 200:
            _problem("Assistant error %d: %s" % (box["status"], bytes(body[:80]).decode("utf-8", "ignore")), back)
            return None
        nl = _head_end(body)
        meta = json.loads(body[:nl])
        if meta.get("ignored"):                      # a look-alike woke it, or nothing followed the phrase
            if stream:
                stream.quit = True
            return "quiet" if followup else "back"
        if meta.get("forget"):                       # "forget that"
            history.clear()
        reply = meta.get("reply", "")
        huh = bool(meta.get("huh")) or reply.startswith("Sorry, I didn't catch")
        cmds = meta.get("board") or []
        if meta.get("radar"):
            flights.set_view(meta["radar"])
            cmds.append({"do": "screen", "name": "flights"})   # "show flights near London": go look
        memory_error = _run_board_commands(cmds, run)
        box["adpcm"] = meta.get("audio") == "adpcm"
        sound, total = _sound(box, body, nl)
        face.keep = keep_screen or bool(opened and opened())
        if face.keep:
            tick(False)
        face.speaking(reply, huh, total)
        between = (lambda: (tick(True), face.mouth())) if face.keep else face.mouth
        ended = _speak(face.voiced(sound), back, tapped, between)
        if audio.starved:
            print("voice: speaker ran dry (chunk, ms):", audio.starved)
        if ended != "done" and stream:
            stream.quit = True
        if ended == "back":
            return "back"
        if memory_error:
            if ended == "interrupt":
                pal.draw("huh", caption=pal.wrap(memory_error))
            else:
                _problem(memory_error, back)
        if meta.get("heard") and not huh and not meta.get("forget"):
            remember(meta["heard"], reply)
        return "interrupt" if ended == "interrupt" else {"board": cmds}
    finally:
        phone.hush(False)

SAY_URL = secrets.VOICE_URL.replace("/api/voice", "/api/say") + "?k=" + secrets.VOICE_KEY

def say(text, boot, connect, tapped=None):
    """Speak up unprompted (companion.py): the Pal hops with a "!" while desk-voice turns `text` into
    Ara's voice, then says it with the words underneath. False if it couldn't (no Wi-Fi, a server
    without /api/say) or BOOT stopped it, "interrupt" if a KEY tap did (you want to talk)."""
    back = lambda: not boot.value()
    lines = pal.caption_page(pal.wrap(text), 0)
    pal.draw("alert", 0, lines)
    if not connect():
        return False
    box = {}
    face = _Face()
    phone.hush(True)
    try:
        if not _post((text.encode(), box, {"X-Audio": "adpcm"}, SAY_URL), box, back,
                     lambda: face._due() and pal.draw("alert", 0, lines)):
            return False
        if "error" in box or box["status"] != 200:
            print("say failed:", box.get("error") or box["status"])
            return False
        body = box["body"]
        nl = _head_end(body)
        box["adpcm"] = json.loads(body[:nl]).get("audio") == "adpcm"
        sound, total = _sound(box, body, nl)
        face.speaking(text, False, total)
        ended = _speak(face.voiced(sound), back, tapped, face.mouth)
        if ended == "back":
            return False
        remember("", text)
        return "interrupt" if ended == "interrupt" else True
    finally:
        phone.hush(False)
