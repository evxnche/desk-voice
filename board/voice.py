# Voice assistant: record while KEY is held (or after the wake phrase, until you stop talking),
# send to desk-voice, show + speak the reply.
import json, time, requests, _thread, socket, ssl, network
import adpcm, audio, dashboard, secrets, flights, music, home, phone

MAX_SECONDS = 12
URL = secrets.VOICE_URL + "?k=" + secrets.VOICE_KEY

def wrap(text, width):
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines

def screen(title, heard="", reply="", hint="BOOT: back"):
    d = dashboard.display()
    d.clear(0)
    d.text_large("ASK AI", 10, 8, 2)
    d.line(0, 32, 400, 32, 1)
    y = 44
    if heard:
        for line in wrap("You: " + heard, 48)[:3]:
            d.text(dashboard.ascii(line), 10, y, 1)
            y += 11
        y += 8
    if reply:
        big = wrap(reply, 24)
        if len(big) * 22 <= 286 - y:
            for line in big:
                d.text_large(dashboard.ascii(line), 10, y, 2)
                y += 22
        else:
            for line in wrap(reply, 48)[:(286 - y) // 11]:
                d.text(dashboard.ascii(line), 10, y, 1)
                y += 11
    else:
        d.text_large(title, 10, 120, 3)
    d.fill_rect(0, 286, 400, 14, 1)
    d.text(hint, 4, 289, 0)
    d.show()

def _request(data, box, wake):
    """Worker thread: POST the recording (4-bit ADPCM), fill `box`, set box['done'].
    `wake` names the wake phrase the recording starts with (the server checks it's really there)."""
    try:
        # ADPCM both ways: a quarter of the bytes of 16-bit PCM over this board's flaky Wi-Fi
        hdrs = {"Content-Type": "application/octet-stream", "X-Audio": "adpcm"}
        if wake:
            hdrs["X-Wake"] = wake
        hdrs.update(music.headers())               # lets "play something chill" reach Spotify
        r = requests.post(URL + flights.params() + home.query(), data=data, timeout=60, headers=hdrs)
        box["status"] = r.status_code
        size = int({k.lower(): v for k, v in r.headers.items()}.get("content-length", 0))
        if size:                                  # big reads: r.content crawls at ~13 KB/s
            body = bytearray(size)
            mv, got = memoryview(body), 0
            while got < size:
                n = r.raw.readinto(mv[got:got + 16384])
                if not n:
                    break
                got += n
        else:
            body = r.content
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

def _read_body(s, length):
    if length is None:                            # Connection: close, so the body runs to EOF
        body = bytearray()
        while True:
            b = s.read(16384)
            if not b:
                return body
            body += b
    body = bytearray(length)
    mv, got = memoryview(body), 0
    while got < length:
        n = s.readinto(mv[got:got + 16384])
        if not n:
            break
        got += n
    return body

class _Stream:
    """Sends the question while you're still asking it. A worker thread connects (TLS) and pings the
    server awake (a cold function takes ~0.6-0.9 s longer) the moment recording starts, then uploads
    the ADPCM as it's recorded (chunked), so when you stop only the last ~0.5 s is left to send.
    Raises OSError if no thread fits; ask() then sends the whole recording afterwards as before."""
    def __init__(self, wake):
        self.mv, self.n, self.end, self.quit, self.box = None, 0, None, False, {}
        host, path = URL.split("/")[2], "/" + URL.split("/", 3)[3]
        hdrs = {"X-Audio": "adpcm"}
        if wake:
            hdrs["X-Wake"] = wake
        hdrs.update(music.headers())               # lets "play something chill" reach Spotify
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
        s.settimeout(65)                          # the server may take up to its 60 s limit
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
                        box["body"], box["status"] = _read_body(s, length), status
                        break
                    # ask() starts speaking once ~1 s of the reply is in and plays the rest as it arrives
                    body = bytearray(length)
                    box["body"], box["got"], box["status"] = body, 0, status
                    mv, got = memoryview(body), 0
                    while got < length and not self.quit:
                        n = s.readinto(mv[got:got + 4096])
                        if not n:
                            break
                        got += n
                        box["got"] = got
                    break
        except Exception as e:
            box["error"] = str(e) or repr(e)
        finally:
            if s:
                s.close()
            box["done"] = True

def _enough(box):
    """True once the reply's first line and ~1 s of its ADPCM audio have arrived."""
    got = box.get("got", 0)
    if not got:
        return False
    nl = bytes(box["body"][:min(got, 4096)]).find(b"\n")
    return nl >= 0 and (got - nl - 1 >= 8000 or got == len(box["body"]))

def _arriving(box, start):
    """16-bit PCM of a reply still downloading, ~0.13 s at a time, waiting for more as needed."""
    dec, body, pos = adpcm.Decoder(), box["body"], start
    while True:
        got, done = box.get("got", 0), "done" in box
        if got - pos >= 1024 or (done and got > pos):
            end = min(got, pos + 1024)
            if not done:
                time.sleep_ms(30)                 # let the download thread in: speaker writes hold it up
            yield dec.decode(memoryview(body)[pos:end])
            pos = end
        elif done:
            return
        else:
            time.sleep_ms(10)

def _start_stream(wake):
    if not network.WLAN(network.STA_IF).isconnected():
        return None                               # ask() joins Wi-Fi after recording, as before
    try:
        return _Stream(wake)
    except OSError:                               # no stack fits right now
        return None

def ask(key, boot, connect, run, tick, heard=None):
    """One question: record while `key` is held, or after the wake phrase when `heard` (audio.woke())
    is given, then show and speak the reply. If the reply comes with board commands (a screen for
    the weather, flights or music, a timer...) they `run` first, `tick(False)` draws the screen,
    and the reply is spoken over it with `tick(True)` keeping it up to date.
    Returns "back" as soon as `boot` is pressed at any stage, else {"board": [commands run]}."""
    back = lambda: not boot.value()
    wake = audio.WAKE_PHRASES[heard[0]] if heard else ""
    phone.hush(True)                                 # Bluetooth advertising slows Wi-Fi 2-8x
    stream = _start_stream(wake)
    try:
        if heard:
            screen("Listening...", hint="Stop talking to send   BOOT: back")
            pcm = audio.record_speech(MAX_SECONDS, heard, stop=back, progress=stream and stream.progress)
        else:
            pcm = audio.record_while(key, MAX_SECONDS, stop=back, progress=stream and stream.progress,
                                     on_start=lambda: screen("Listening...", hint="Let go of KEY to send   BOOT: back"))
        if pcm is None or back() or len(pcm) < audio.RATE * 2 // 2:   # under half a second: a slip
            if stream:
                stream.quit = True
            return "back" if pcm is None or back() else None
        screen("Thinking...")
        box = {}
        if stream:
            stream.end = len(pcm)                    # the worker sends the last piece and waits for the reply
            box = stream.box
            while "done" not in box and not _enough(box):
                if back():
                    stream.quit = True
                    return "back"
                time.sleep_ms(20)
            if "error" in box:                       # streaming broke: send the whole recording instead
                box = {}
        if not box:
            if not connect():
                screen("No Wi-Fi")
                time.sleep(3)
                return None
            job = (adpcm.encode(pcm), box, wake)
            try:
                # TLS needs more than the default stack; 20 KB is plenty (tested on the board), and a
                # task stack must be one block of internal RAM, which Bluetooth (phone.py) shares.
                _thread.stack_size(20 * 1024)
                _thread.start_new_thread(_request, job)
            except OSError:
                # No block big enough for the stack ("can't create thread"): ask from this thread
                # instead. BOOT then only works once the answer is back.
                _request(*job)
            while "done" not in box:                 # the worker keeps going if we leave; its result is dropped
                if back():
                    return "back"
                time.sleep_ms(20)
        if "error" in box:
            screen("", reply="Couldn't reach the assistant: %s" % box["error"])
            return None
        body = box["body"]
        if box["status"] != 200:
            screen("", reply="Assistant error %d: %s" % (box["status"], bytes(body[:80]).decode("utf-8", "ignore")))
            return None
        nl = bytes(body[:min(box.get("got", len(body)), 4096)]).find(b"\n")
        meta = json.loads(body[:nl])
        if meta.get("ignored"):                      # a look-alike woke it, or nothing followed the phrase
            if stream:
                stream.quit = True
            return "back"
        cmds = meta.get("board") or []
        if meta.get("radar"):
            flights.set_view(meta["radar"])
            cmds.append({"do": "screen", "name": "flights"})   # "show flights near London": go look
        for cmd in cmds:
            run(cmd)
        if cmds:
            tick(False)
        else:
            screen("", meta.get("heard", ""), meta.get("reply", ""), hint="BOOT: back   KEY: ask again")
        if meta.get("audio") != "adpcm":
            while "done" not in box:                 # plain PCM (an older server): wait for all of it
                time.sleep_ms(20)
            sound = memoryview(body)[nl + 1:]
        elif "got" in box:
            sound = _arriving(box, nl + 1)           # decode and play it as it downloads
        else:
            sound = adpcm.decode(memoryview(body)[nl + 1:])   # ~0.1 s for 6 s of speech
        if not audio.play(sound, volume=0xBF, mono=True, stop=back,
                          between=(lambda: tick(True)) if cmds else None):
            if stream:
                stream.quit = True
            return "back"
        return {"board": cmds}
    finally:
        phone.hush(False)
