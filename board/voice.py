# Voice assistant: record while KEY is held (or after the wake phrase, until you stop talking),
# send to desk-voice, show + speak the reply.
import json, time, requests, _thread
import audio, dashboard, secrets, flights, music, home

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

def _request(pcm, box, wake):
    """Worker thread: POST the recording, fill `box`, set box['done'].
    `wake` names the wake phrase the recording starts with (the server checks it's really there)."""
    try:
        hdrs = {"Content-Type": "application/octet-stream"}
        if wake:
            hdrs["X-Wake"] = wake
        hdrs.update(music.headers())               # lets "play something chill" reach Spotify
        r = requests.post(URL + flights.params() + home.query(), data=pcm, timeout=60, headers=hdrs)
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

def ask(key, boot, connect, heard=None):
    """One question: record while `key` is held, or after the wake phrase when `heard` (audio.woke())
    is given, then show and speak the reply.
    Returns "back" as soon as `boot` is pressed at any stage, else {"radar": moved?, "board": [commands]}."""
    back = lambda: not boot.value()
    if heard:
        screen("Listening...", hint="Stop talking to send   BOOT: back")
        pcm = audio.record_speech(MAX_SECONDS, heard, stop=back)
    else:
        pcm = audio.record_while(key, MAX_SECONDS, stop=back,
                                 on_start=lambda: screen("Listening...", hint="Let go of KEY to send   BOOT: back"))
    if pcm is None or back():
        return "back"
    if len(pcm) < audio.RATE * 2 // 2:               # under half a second: treat as a slip
        return None
    screen("Thinking...")
    if not connect():
        screen("No Wi-Fi")
        time.sleep(3)
        return None
    box = {}
    _thread.stack_size(32 * 1024)                    # TLS needs more than the default stack
    _thread.start_new_thread(_request, (bytes(pcm), box, audio.WAKE_PHRASES[heard[0]] if heard else ""))
    while "done" not in box:                         # the worker keeps going if we leave; its result is dropped
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
    nl = body.find(b"\n")
    meta = json.loads(body[:nl])
    if meta.get("ignored"):                          # a look-alike woke it, or nothing followed the phrase
        return "back"
    screen("", meta.get("heard", ""), meta.get("reply", ""), hint="BOOT: back   KEY: ask again")
    if meta.get("radar"):
        flights.set_view(meta["radar"])
    if not audio.play(memoryview(body)[nl + 1:], volume=0xBF, mono=True, stop=back):
        return "back"
    return {"radar": bool(meta.get("radar")), "board": meta.get("board") or []}
