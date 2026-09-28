// The flight tracker's map (lib/trackmap.js).
// GET ?k=VOICE_KEY&lat=..&lon=..&kmpx=..&w=..&h=..[&route=lat1,lon1,lat2,lon2]
// Replies with one JSON line ({lat, lon, kmpx, w, h, labels}) + "\n" + the 1-bit MONO_HLSB bitmap.
import { renderMap } from '../lib/trackmap.js';

export async function GET(request) {
  const url = new URL(request.url);
  const q = (k) => Number(url.searchParams.get(k));
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  const route = (url.searchParams.get('route') || '').split(',').map(Number);
  const args = {
    lat: q('lat'), lon: q('lon'),
    kmpx: Math.min(50, Math.max(0.5, q('kmpx') || 5)),
    w: Math.min(400, Math.max(8, Math.round((q('w') || 248) / 8) * 8)),
    h: Math.min(300, Math.max(8, Math.round(q('h') || 250))),
    route: route.length === 4 && route.every(Number.isFinite) ? route : null,
  };
  if (!Number.isFinite(args.lat) || !Number.isFinite(args.lon)) return new Response('need lat, lon', { status: 400 });
  const { meta, bitmap } = await renderMap(args);
  const body = Buffer.concat([Buffer.from(JSON.stringify(meta) + '\n'), bitmap]);
  return new Response(body, {
    headers: { 'Content-Type': 'application/octet-stream', 'Content-Length': String(body.length) },
  });
}
