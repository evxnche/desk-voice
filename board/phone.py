# iPhone notifications over Bluetooth, via Apple's Notification Center Service (ANCS).
# The board advertises as "deskpal" asking for ANCS; the iPhone pairs once from Settings > Bluetooth,
# then reconnects by itself whenever it's in range and pushes every new notification. We keep the
# WhatsApp ones. The iPhone is the GATT server here; the board only subscribes and asks for details.
import bluetooth, struct, json, binascii, time
from micropython import const

_CONNECT, _DISCONNECT = const(1), const(2)
_SERVICE_RESULT, _SERVICE_DONE = const(9), const(10)
_CHAR_RESULT, _CHAR_DONE = const(11), const(12)
_DESC_RESULT, _DESC_DONE = const(13), const(14)
_WRITE_DONE, _NOTIFY = const(17), const(18)
_ENCRYPTED, _GET_SECRET, _SET_SECRET = const(28), const(29), const(30)

ANCS = bluetooth.UUID("7905F431-B5CE-4E99-A40F-4B1E122D00D0")
NOTIFICATION_SOURCE = bluetooth.UUID("9FBF120D-6301-42D9-8C58-25E699A21DBD")
CONTROL_POINT = bluetooth.UUID("69D1D8F3-45E1-49A8-9821-9BBDFDAAD9D9")
DATA_SOURCE = bluetooth.UUID("22EAC6E9-24D6-4BB5-BE44-B36ACE7C7BFB")
CCCD = bluetooth.UUID(0x2902)

APPS = ("net.whatsapp.WhatsApp", "net.whatsapp.WhatsAppSMB")
# Get Notification Attributes: app id, title (sender or chat) max 64 bytes, subtitle (group) 64, message 240.
_ASK = "<BIBBHBHBH"
_ATTRS = 4
BONDS_FILE = "ble_bonds.json"

ble = None
conn = None
chars = {}            # uuid -> (value_handle, end_handle)
cccds = {}            # uuid -> descriptor handle
service = None
subscribe = []        # CCCDs still to switch on, one write at a time
subscribing = None    # the CCCD write in flight
sharing = False       # the phone accepted the Notification Source subscription
encrypted = False
tried = 0             # when we last looked for ANCS on this connection
waiting = []          # notification UIDs to fetch details for
asking = None         # (uid, ticks) while the phone is answering
answer = b""
inbox = []            # finished WhatsApp notifications for main.py
bonds = {}

def _load_bonds():
    try:
        for kind, key, value in json.load(open(BONDS_FILE)):
            bonds[kind, binascii.a2b_base64(key)] = binascii.a2b_base64(value)
    except Exception:
        pass

def _save_bonds():
    b64 = lambda b: binascii.b2a_base64(b).decode().strip()
    with open(BONDS_FILE, "w") as f:
        json.dump([(kind, b64(key), b64(value)) for (kind, key), value in bonds.items()], f)

def _advertise():
    name = b"deskpal"
    adv = (b"\x02\x01\x06" + bytes((len(name) + 1, 0x09)) + name
           + bytes((17, 0x15)) + bytes(ANCS))                    # 0x15: "please connect me to ANCS"
    ble.gap_advertise(500000, adv_data=adv)

def _reset():
    global conn, service, asking, answer, subscribing, sharing, encrypted
    conn = service = asking = subscribing = None
    sharing = encrypted = False
    answer = b""
    chars.clear()
    cccds.clear()
    subscribe.clear()
    waiting.clear()

def _discover():
    """Find ANCS and subscribe; re-run from tick() until the phone agrees to share."""
    global service, tried
    service = None
    chars.clear()
    cccds.clear()
    tried = time.ticks_ms()
    ble.gattc_discover_services(conn, ANCS)

def _next_subscribe():
    global subscribing
    subscribing = subscribe.pop(0) if subscribe else None
    if subscribing:
        ble.gattc_write(conn, subscribing, b"\x01\x00", 1)

def _text(b):
    """UTF-8 cut at the byte limit can end mid-character; drop the stray tail."""
    for n in range(4):
        try:
            s = bytes(b[:len(b) - n]).decode()
            break
        except Exception:
            s = ""
    # Emoji and the invisible direction marks iOS puts around names would each become "-" on screen.
    s = "".join(c for c in s if ord(c) < 0x2190 and not 0x200B <= ord(c) <= 0x200F
                and not 0x202A <= ord(c) <= 0x202E and not 0x2060 <= ord(c) <= 0x206F)
    return " ".join(s.split())

def _parse(buf):
    """The phone's answer, or None until all of it has arrived (it comes in MTU-sized pieces)."""
    if len(buf) < 5:
        return None
    attrs, i = {}, 5
    while len(attrs) < _ATTRS:
        if i + 3 > len(buf):
            return None
        aid, n = buf[i], buf[i + 1] | buf[i + 2] << 8
        if i + 3 + n > len(buf):
            return None
        attrs[aid] = buf[i + 3:i + 3 + n]
        i += 3 + n
    return attrs

def _irq(event, data):
    global conn, service, asking, answer, sharing, encrypted
    if event == _CONNECT:
        _reset()
        conn = data[0]
        try:
            ble.gap_pair(conn)            # ANCS needs an encrypted link; bonded phones just re-encrypt
        except Exception:
            pass
    elif event == _DISCONNECT:
        _reset()
        _advertise()
    elif event == _ENCRYPTED:
        if data[0] == conn and data[1] and not encrypted:
            encrypted = True
            _discover()
    elif event == _SERVICE_RESULT:
        if data[3] == ANCS:
            service = (data[1], data[2])
    elif event == _SERVICE_DONE:
        if service:                       # no ANCS: not an iPhone, or notification sharing is off
            ble.gattc_discover_characteristics(conn, service[0], service[1])
    elif event == _CHAR_RESULT:
        # The module reuses one UUID object for every event: copy it before keeping it.
        chars[bluetooth.UUID(data[4])] = (data[2], data[1])
    elif event == _CHAR_DONE:
        ble.gattc_discover_descriptors(conn, service[0], service[1])
    elif event == _DESC_RESULT:
        if data[2] == CCCD:
            for uuid, (value, end) in chars.items():
                if value < data[1] <= end:
                    cccds[uuid] = data[1]
    elif event == _DESC_DONE:
        # Data Source first, so no answer arrives before we're listening for it.
        subscribe[:] = [cccds[u] for u in (DATA_SOURCE, NOTIFICATION_SOURCE) if u in cccds]
        _next_subscribe()
    elif event == _WRITE_DONE:
        if subscribing and data[1] == subscribing:
            if data[1] == cccds.get(NOTIFICATION_SOURCE):
                sharing = not data[2]
            _next_subscribe()
        elif asking and data[1] == chars[CONTROL_POINT][0] and data[2]:
            asking = None                 # the notification was already gone
    elif event == _NOTIFY:
        handle, value = data[1], bytes(data[2])
        if handle == chars.get(NOTIFICATION_SOURCE, (0,))[0]:
            event_id, flags, category, count, uid = struct.unpack("<BBBBI", value)
            if event_id == 0 and not flags & 4:          # new, not one already on the phone
                waiting.append(uid)
        elif handle == chars.get(DATA_SOURCE, (0,))[0] and asking:
            answer += value
            attrs = _parse(answer)
            if attrs is not None:
                asking, answer = None, b""
                if _text(attrs[0]) in APPS:
                    inbox.append({"title": _text(attrs[1]), "subtitle": _text(attrs[2]),
                                  "message": _text(attrs[3])})
    elif event == _SET_SECRET:
        kind, key, value = data
        key = (kind, bytes(key))
        if value:
            bonds[key] = bytes(value)
        elif key in bonds:
            del bonds[key]
        else:
            return False
        _save_bonds()
        return True
    elif event == _GET_SECRET:
        kind, index, key = data
        if key is None:
            found = [v for (k, _), v in bonds.items() if k == kind]
            return found[index] if index < len(found) else None
        return bonds.get((kind, bytes(key)))

def start():
    global ble
    _load_bonds()
    ble = bluetooth.BLE()
    ble.irq(_irq)
    ble.config(bond=True, le_secure=True, mitm=False, io=3)   # io 3: no screen/keys, "Just Works" pairing
    ble.active(True)
    ble.config(gap_name="deskpal", mtu=247)
    _advertise()

def hush(on):
    """Stop advertising while `on`: it slows Wi-Fi a lot (a 45 KB voice upload took 1.2-4.7 s while
    advertising, 0.6 s with Bluetooth off, 0.85 s on but quiet), so voice questions hush it until the
    answer is in. Nothing to do while the iPhone is connected: the board only advertises when it isn't."""
    if ble is None or conn is not None:
        return
    if on:
        ble.gap_advertise(None)
    else:
        _advertise()

def tick():
    """Ask the phone about the next new notification; call often from the main loop."""
    global asking, answer
    if asking and time.ticks_diff(time.ticks_ms(), asking[1]) > 3000:
        asking, answer = None, b""        # no answer; move on
    if (encrypted and not sharing and subscribing is None
            and time.ticks_diff(time.ticks_ms(), tried) > 10000):
        try:
            _discover()                   # sharing was off or still being allowed on the phone
        except Exception:
            pass
    if not sharing or asking or not waiting or CONTROL_POINT not in chars:
        return
    uid = waiting.pop(0)
    asking, answer = (uid, time.ticks_ms()), b""
    try:
        ble.gattc_write(conn, chars[CONTROL_POINT][0], struct.pack(_ASK, 0, uid, 0, 1, 64, 2, 64, 3, 240), 1)
    except Exception:
        asking = None

def status():
    return "sharing notifications" if sharing else "connected, not sharing yet" if conn is not None else "waiting for iPhone"
