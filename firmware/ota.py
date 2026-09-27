#!/usr/bin/env python3
"""Update Desk Pal's firmware over USB, no BOOT button: streams the app built by build.sh straight
into the board's other app slot, one 4 KB block per ack, then boots from it. (mpremote cp manages
~5 KB/s here; this does the 2.5 MB in well under a minute.) The speech model and partition table
aren't touched; changing those needs a download-mode flash, see build.sh.

Usage: python3 firmware/ota.py [port]
"""
import glob, os, sys, time
import serial

APP = os.path.expanduser("~/esp/deskpal/out/micropython.bin")

RECEIVER = b"""
import esp32, sys, micropython
micropython.kbd_intr(-1)                 # the image contains 0x03 bytes
nxt = esp32.Partition(esp32.Partition.RUNNING).get_next_update()
size = int(sys.stdin.readline())
buf = bytearray(4096)
done = blk = 0
while done < size:
    want = min(4096, size - done)
    data = sys.stdin.buffer.read(want)
    buf[:want] = data
    if want < 4096:
        buf[want:] = b'\\xff' * (4096 - want)
    nxt.writeblocks(blk, buf)
    blk += 1
    done += want
    sys.stdout.write('.')
nxt.set_boot()
micropython.kbd_intr(3)
print('OK', nxt.info()[4])
"""

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("/dev/cu.usbmodem*"))[0]
    image = open(APP, "rb").read()
    s = serial.Serial(port, 115200, timeout=10)
    s.write(b"\r\x03\x03")                   # stop whatever is running
    time.sleep(0.3)
    s.write(b"\x01")                         # raw REPL
    time.sleep(0.3)
    s.reset_input_buffer()
    s.write(RECEIVER + b"\x04")
    if s.read(2) != b"OK":
        sys.exit("board didn't accept the receiver")
    s.write(b"%d\n" % len(image))
    t0 = time.time()
    for i in range(0, len(image), 4096):
        s.write(image[i:i + 4096])
        ack = s.read(1)
        if ack != b".":
            sys.exit("no ack at %d KB: %r %r" % (i // 1024, ack, s.read(200)))
        if (i // 4096) % 64 == 0:
            print("%4d / %d KB" % (i // 1024, len(image) // 1024), flush=True)
    reply = s.read_until(b"\x04")
    print(reply.decode(errors="replace").strip("\x04\r\n "), "in %.0f s" % (time.time() - t0))
    if b"OK ota_" not in reply:
        sys.exit("update failed")
    s.write(b"import machine; machine.reset()\x04")
    time.sleep(0.5)
    print("restarting into the new firmware")

main()
