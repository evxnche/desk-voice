// Nearby aircraft for the desk board's radar screen, from adsb.lol (free, no key).
// GET ?k=VOICE_KEY[&lat=..&lon=..][&r=nm]. Without lat/lon, uses Vercel's IP geolocation of the caller.
const MAX_AIRCRAFT = 40;

export async function GET(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  const h = request.headers;
  const lat = Number(url.searchParams.get('lat') ?? h.get('x-vercel-ip-latitude'));
  const lon = Number(url.searchParams.get('lon') ?? h.get('x-vercel-ip-longitude'));
  const radius = Math.min(100, Math.max(5, Number(url.searchParams.get('r') ?? 25)));
  const place = url.searchParams.has('lat') ? '' : decodeURIComponent(h.get('x-vercel-ip-city') ?? '');
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return new Response('no location', { status: 400 });
  }

  const res = await fetch(`https://api.adsb.lol/v2/point/${lat.toFixed(4)}/${lon.toFixed(4)}/${radius}`, {
    signal: AbortSignal.timeout(8000),
    headers: { 'User-Agent': 'desk-voice/1.0 (+https://github.com/evxnche)' }, // adsb.lol 403s Node's default UA
  });
  if (!res.ok) return new Response(`adsb.lol ${res.status}`, { status: 502 });
  const { ac = [] } = await res.json();

  const aircraft = ac
    .filter((a) => typeof a.alt_baro === 'number' && a.dst != null && a.dir != null)
    .sort((a, b) => a.dst - b.dst)
    .slice(0, MAX_AIRCRAFT)
    .map((a) => ({
      id: (a.flight || a.r || a.hex || '').trim(),
      type: a.t || '',
      alt: a.alt_baro,
      dist: Math.round(a.dst * 10) / 10,
      bearing: Math.round(a.dir),
      track: Math.round(a.track ?? 0),
      speed: Math.round(a.gs ?? 0),
    }));

  const body = Buffer.from(JSON.stringify({ place, radius, total: ac.length, aircraft }));
  return new Response(body, {
    headers: { 'Content-Type': 'application/json', 'Content-Length': String(body.length) },
  });
}
