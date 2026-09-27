# 4-bit IMA ADPCM for the voice assistant's audio (lib/adpcm.js is the server's copy): a quarter
# of the bytes of 16-bit PCM, so recordings upload and replies download ~4x faster over this
# board's flaky Wi-Fi. Two samples per byte, low nibble first; both ends start from pred 0, index 0.
import array, micropython

_STEPS = array.array("H", (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66,
    73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408,
    449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
    2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630,
    9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767))

@micropython.viper
def _encode(src: ptr16, n: int, dst: ptr8):
    steps = ptr16(_STEPS)
    pred = 0
    index = 0
    for i in range(n):
        v = int(src[i])
        if v >= 32768:
            v -= 65536
        step = int(steps[index])
        diff = v - pred
        code = 0
        if diff < 0:
            code = 8
            diff = 0 - diff
        delta = step >> 3
        if diff >= step:
            code |= 4
            diff -= step
            delta += step
        if diff >= (step >> 1):
            code |= 2
            diff -= step >> 1
            delta += step >> 1
        if diff >= (step >> 2):
            code |= 1
            delta += step >> 2
        if code & 8:
            pred -= delta
        else:
            pred += delta
        if pred > 32767:
            pred = 32767
        elif pred < -32768:
            pred = -32768
        if (code & 7) < 4:
            index -= 1
        else:
            index += ((code & 7) - 3) << 1
        if index < 0:
            index = 0
        elif index > 88:
            index = 88
        if i & 1:
            dst[i >> 1] = dst[i >> 1] | (code << 4)
        else:
            dst[i >> 1] = code

@micropython.viper
def _decode(src: ptr8, n: int, dst: ptr16):
    steps = ptr16(_STEPS)
    pred = 0
    index = 0
    for i in range(n):
        code = int(src[i >> 1])
        if i & 1:
            code >>= 4
        code &= 15
        step = int(steps[index])
        delta = step >> 3
        if code & 4:
            delta += step
        if code & 2:
            delta += step >> 1
        if code & 1:
            delta += step >> 2
        if code & 8:
            pred -= delta
        else:
            pred += delta
        if pred > 32767:
            pred = 32767
        elif pred < -32768:
            pred = -32768
        if (code & 7) < 4:
            index -= 1
        else:
            index += ((code & 7) - 3) << 1
        if index < 0:
            index = 0
        elif index > 88:
            index = 88
        dst[i] = pred & 0xFFFF

def encode(pcm):
    """16-bit mono PCM (bytes-like) -> ADPCM bytearray, a quarter the size."""
    n = len(pcm) // 2
    out = bytearray((n + 1) // 2)
    _encode(pcm, n, out)
    return out

def decode(data):
    """ADPCM (bytes-like) -> 16-bit mono PCM bytearray, four times the size."""
    n = len(data) * 2
    out = bytearray(n * 2)
    _decode(data, n, out)
    return out
