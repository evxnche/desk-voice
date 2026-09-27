// 4-bit IMA ADPCM, the voice assistant's audio format on the wire (board/adpcm.py is the board's
// copy): a quarter of the bytes of 16-bit PCM. Two samples per byte, low nibble first; both ends
// start from pred 0, index 0.
const STEPS = [
  7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66,
  73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408,
  449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
  2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630,
  9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
];
const INDEX_STEP = [-1, -1, -1, -1, 2, 4, 6, 8];

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export function encode(samples) {
  const out = Buffer.alloc(Math.ceil(samples.length / 2));
  let pred = 0, index = 0;
  for (let i = 0; i < samples.length; i++) {
    const step = STEPS[index];
    let diff = samples[i] - pred, code = 0;
    if (diff < 0) { code = 8; diff = -diff; }
    let delta = step >> 3;
    if (diff >= step) { code |= 4; diff -= step; delta += step; }
    if (diff >= step >> 1) { code |= 2; diff -= step >> 1; delta += step >> 1; }
    if (diff >= step >> 2) { code |= 1; delta += step >> 2; }
    pred = clamp(code & 8 ? pred - delta : pred + delta, -32768, 32767);
    index = clamp(index + INDEX_STEP[code & 7], 0, 88);
    out[i >> 1] |= i & 1 ? code << 4 : code;
  }
  return out;
}

export function decode(bytes) {
  const out = new Int16Array(bytes.length * 2);
  let pred = 0, index = 0;
  for (let i = 0; i < out.length; i++) {
    const code = i & 1 ? bytes[i >> 1] >> 4 : bytes[i >> 1] & 15;
    const step = STEPS[index];
    let delta = step >> 3;
    if (code & 4) delta += step;
    if (code & 2) delta += step >> 1;
    if (code & 1) delta += step >> 2;
    pred = clamp(code & 8 ? pred - delta : pred + delta, -32768, 32767);
    index = clamp(index + INDEX_STEP[code & 7], 0, 88);
    out[i] = pred;
  }
  return out;
}
