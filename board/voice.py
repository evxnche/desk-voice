# Hold-to-talk assistant: record while KEY is held, send to desk-voice, show + speak the reply.
import json, time, requests
import audio, dashboard, secrets

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

def screen(title, heard="", reply=""):
    d = dashboard.display()
    d.clear(0)
    d.text_large("ASK CLAUDE", 10, 8, 2)
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
    d.show()

def ask(key, connect):
    """Run one question. `key` is the held button, `connect()` joins Wi-Fi."""
    pcm = audio.record_while(key, MAX_SECONDS,
                             on_start=lambda: screen("Listening..."))
    if len(pcm) < audio.RATE * 2 // 2:               # under half a second: treat as a slip
        return
    screen("Thinking...")
    if not connect():
        screen("No Wi-Fi")
        time.sleep(3)
        return
    try:
        r = requests.post(URL, data=bytes(pcm), timeout=60,
                          headers={"Content-Type": "application/octet-stream"})
        body = r.content
        status = r.status_code
        r.close()
    except Exception as e:
        screen("", reply="Couldn't reach the assistant: %s" % e)
        time.sleep(5)
        return
    if status != 200:
        screen("", reply="Assistant error %d: %s" % (status, body[:80].decode("utf-8", "ignore")))
        time.sleep(6)
        return
    nl = body.find(b"\n")
    meta = json.loads(body[:nl])
    screen("", meta.get("heard", ""), meta.get("reply", ""))
    audio.play(memoryview(body)[nl + 1:], volume=0xBF, mono=True)
