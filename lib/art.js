// Album covers for a 1-bit screen: resize, stretch contrast, Atkinson-dither, pack as MONO_HLSB
// (row-major, 8 px per byte, bit 7 = leftmost, 1 = black ink), which MicroPython's framebuf blits as-is.
import sharp from 'sharp';

const ALLOWED = /(^|\.)(scdn\.co|spotifycdn\.com)$/; // Spotify's image CDNs only

export async function ditheredCover(url, size) {
  const host = new URL(url).hostname;
  if (!ALLOWED.test(host)) throw new Error('not a Spotify image');
  const res = await fetch(url, { signal: AbortSignal.timeout(6000) });
  if (!res.ok) throw new Error(`cover ${res.status}`);
  const { data } = await sharp(Buffer.from(await res.arrayBuffer()))
    .resize(size, size, { fit: 'cover' })
    .greyscale()
    .normalise() // full black-to-white range before dithering keeps covers from going muddy
    .raw()
    .toBuffer({ resolveWithObject: true });

  // Atkinson dithering: spreads 6/8 of the error, so highlights and shadows stay clean.
  const px = Float32Array.from(data);
  const out = Buffer.alloc((size / 8) * size);
  const spread = [[1, 0], [2, 0], [-1, 1], [0, 1], [1, 1], [0, 2]];
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = y * size + x;
      const ink = px[i] < 128;
      if (ink) out[y * (size / 8) + (x >> 3)] |= 0x80 >> (x & 7);
      const err = (px[i] - (ink ? 0 : 255)) / 8;
      for (const [dx, dy] of spread) {
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && nx < size && ny < size) px[ny * size + nx] += err;
      }
    }
  }
  return out;
}
