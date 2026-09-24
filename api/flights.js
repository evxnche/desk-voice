// Nearby aircraft for the desk board's radar screen.
// Positions from adsb.lol; airline, route and aircraft names from adsbdb (both free, no key).
// GET ?k=VOICE_KEY[&lat=..&lon=..][&r=nm]. Without lat/lon, uses Vercel's IP geolocation of the caller.
const MAX_AIRCRAFT = 40;
const DETAILED = 6; // the nearest few get plain-English details for the list
const UA = { 'User-Agent': 'desk-voice/1.0 (+https://github.com/evxnche)' }; // adsb.lol 403s Node's default UA

const KIND = {
  A1: 'Small plane', A2: 'Small plane', A3: 'Airliner', A4: 'Large jet', A5: 'Heavy jet',
  A6: 'Fast jet', A7: 'Helicopter', B1: 'Glider', B2: 'Balloon', B4: 'Microlight', B6: 'Drone',
};
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

// Warm function instances reuse these, so repeat refreshes rarely hit adsbdb.
const routeCache = new Map();
const aircraftCache = new Map();

async function adsbdb(path, cache, key) {
  if (cache.has(key)) return cache.get(key);
  let value = null;
  try {
    const res = await fetch(`https://api.adsbdb.com/v0/${path}`, { headers: UA, signal: AbortSignal.timeout(4000) });
    if (res.ok) value = (await res.json()).response ?? null;
  } catch {
    return null; // don't cache failures
  }
  if (typeof value !== 'object') value = null; // "unknown callsign" comes back as a string
  cache.set(key, value);
  return value;
}

function city(ap) {
  return (ap?.municipality || ap?.name || ap?.iata_code || '').split(/[/,(]/)[0].trim();
}

async function describe(a, place) {
  const callsign = (a.flight || '').trim();
  const [routeInfo, craftInfo] = await Promise.all([
    callsign ? adsbdb(`callsign/${callsign}`, routeCache, callsign) : null,
    adsbdb(`aircraft/${a.hex}`, aircraftCache, a.hex),
  ]);
  const route = routeInfo?.flightroute;
  const craft = craftInfo?.aircraft;
  const kind = KIND[a.category] || 'Plane';

  let where = '';
  if (route) {
    const from = city(route.origin), to = city(route.destination);
    // Arriving here reads better as "from X"; everything else as "to Y".
    where = place && to.toLowerCase() === place.toLowerCase() ? `from ${from}` : `to ${to}`;
  }
  // Short, screen-sized description: "Boeing 737MAX" for jets, "Small plane, Piper" otherwise.
  const maker = (craft?.manufacturer || '').split(' ')[0];
  const jet = ['Airliner', 'Large jet', 'Heavy jet'].includes(kind);
  const what = jet && craft ? `${maker} ${(craft.type || '').split(' ')[0]}`.trim() : maker ? `${kind}, ${maker}` : kind;
  return {
    who: route?.airline?.name || craft?.registered_owner || kind,
    where: where || what,
  };
}

export async function GET(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  const h = request.headers;
  const lat = Number(url.searchParams.get('lat') ?? h.get('x-vercel-ip-latitude'));
  const lon = Number(url.searchParams.get('lon') ?? h.get('x-vercel-ip-longitude'));
  const radius = Math.min(100, Math.max(5, Number(url.searchParams.get('r') ?? 26)));
  const place = url.searchParams.has('lat') ? '' : decodeURIComponent(h.get('x-vercel-ip-city') ?? '');
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return new Response('no location', { status: 400 });
  }

  const res = await fetch(`https://api.adsb.lol/v2/point/${lat.toFixed(4)}/${lon.toFixed(4)}/${radius}`, {
    headers: UA,
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) return new Response(`adsb.lol ${res.status}`, { status: 502 });
  const { ac = [] } = await res.json();

  const near = ac
    .filter((a) => typeof a.alt_baro === 'number' && a.dst != null && a.dir != null)
    .sort((a, b) => a.dst - b.dst)
    .slice(0, MAX_AIRCRAFT);
  const details = await Promise.all(near.slice(0, DETAILED).map((a) => describe(a, place)));

  const aircraft = near.map((a, i) => {
    const rate = a.baro_rate ?? a.geom_rate ?? 0;
    return {
      dist: Math.round(a.dst * 10) / 10, // nm, for plotting
      bearing: Math.round(a.dir),
      track: Math.round(a.track ?? 0),
      speed: Math.round(a.gs ?? 0), // knots; the board uses it to glide planes between refreshes
      ...(i < DETAILED && {
        ...details[i],
        miles: Math.round(a.dst * 1.15078),
        dir: COMPASS[Math.round(a.dir / 45) % 8],
        alt: a.alt_baro,
        trend: rate > 300 ? 'up' : rate < -300 ? 'down' : '',
      }),
    };
  });

  const body = Buffer.from(JSON.stringify({ place, radius, miles: Math.round(radius * 1.15078), aircraft }));
  return new Response(body, {
    headers: { 'Content-Type': 'application/json', 'Content-Length': String(body.length) },
  });
}
