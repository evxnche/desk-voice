// Shared flight lookup for the radar screen (/api/flights) and the voice assistant's tools.
// Positions from adsb.lol; airline, route and aircraft names from adsbdb; place names from
// OpenStreetMap Nominatim. All free, no keys.
const MAX_AIRCRAFT = 80; // enough to fill a 100 km radius around a busy area
const UA = { 'User-Agent': 'desk-voice/1.0 (+https://github.com/evxnche)' }; // adsb.lol 403s Node's default UA
export const KM_PER_NM = 1.852;
export const DEFAULT_RADIUS_NM = 100 / KM_PER_NM; // 100 km, so the rings read 50 / 100 km

const KIND = {
  A1: 'Small plane', A2: 'Small plane', A3: 'Airliner', A4: 'Large jet', A5: 'Heavy jet',
  A6: 'Fast jet', A7: 'Helicopter', B1: 'Glider', B2: 'Balloon', B4: 'Microlight', B6: 'Drone',
};
const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
// ICAO type designators -> the names people know (kept to 7 chars for the board's table).
const TYPE_NAME = {
  A388: 'A380', A359: 'A350-9', A35K: 'A350-10', A339: 'A330neo', A333: 'A330-3', A332: 'A330-2',
  A319: 'A319', A320: 'A320', A321: 'A321', A19N: 'A319neo', A20N: 'A320neo', A21N: 'A321neo',
  BCS1: 'A220-1', BCS3: 'A220-3', B737: '737-700', B738: '737-800', B739: '737-900', B38M: '737MAX8',
  B39M: '737MAX9', B744: '747-400', B748: '747-8', B752: '757-200', B763: '767-300', B772: '777-200',
  B77W: '777-300', B77L: '777LR', B788: '787-8', B789: '787-9', B78X: '787-10', E190: 'E190',
  E195: 'E195', E75L: 'E175', AT76: 'ATR72', AT75: 'ATR72', DH8D: 'Dash 8', CRJ9: 'CRJ900',
};

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

const RAD = Math.PI / 180;

function kmBetween(lat1, lon1, lat2, lon2) {
  const a = Math.sin(((lat2 - lat1) * RAD) / 2) ** 2 +
    Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(((lon2 - lon1) * RAD) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

function bearing(lat1, lon1, lat2, lon2) {
  const y = Math.sin((lon2 - lon1) * RAD) * Math.cos(lat2 * RAD);
  const x = Math.cos(lat1 * RAD) * Math.sin(lat2 * RAD) - Math.sin(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.cos((lon2 - lon1) * RAD);
  return (Math.atan2(y, x) / RAD + 360) % 360;
}

// adsbdb maps a callsign to its usual route, but charter callsigns (TUI's TOM2BJ, etc.) get reused:
// TOM2BJ was listed Belfast > Reus while flying Palma > Bournemouth. Accept the route only if the
// plane is roughly on the way between the airports and pointing at the destination.
function routeFits(a, origin, dest) {
  const nums = [origin?.latitude, origin?.longitude, dest?.latitude, dest?.longitude, a.lat, a.lon];
  if (nums.some((v) => typeof v !== 'number')) return true; // can't check, don't guess
  const total = kmBetween(origin.latitude, origin.longitude, dest.latitude, dest.longitude);
  const fromOrigin = kmBetween(origin.latitude, origin.longitude, a.lat, a.lon);
  const toDest = kmBetween(a.lat, a.lon, dest.latitude, dest.longitude);
  if (fromOrigin + toDest > total * 1.25 + 100) return false; // well off the path
  // Low and descending means it's landing nearby; low and climbing means it just took off nearby.
  const rate = a.baro_rate ?? a.geom_rate ?? 0;
  if (typeof a.alt_baro === 'number' && a.alt_baro < 10000) {
    if (rate < -300 && toDest > 150) return false;
    if (rate > 300 && fromOrigin > 150) return false;
  }
  if (typeof a.track === 'number' && fromOrigin > 80 && toDest > 80) {
    // Away from both airports (departure turns, approach patterns) it should head for the destination.
    const off = Math.abs(((a.track - bearing(a.lat, a.lon, dest.latitude, dest.longitude)) + 540) % 360 - 180);
    if (off > 75) return false;
  }
  return true;
}

function city(ap) {
  return (ap?.municipality || ap?.name || ap?.iata_code || '').split(/[/,(]/)[0].trim();
}

async function describe(a) {
  const callsign = (a.flight || '').trim();
  const [routeInfo, craftInfo] = await Promise.all([
    callsign ? adsbdb(`callsign/${callsign}`, routeCache, callsign) : null,
    adsbdb(`aircraft/${a.hex}`, aircraftCache, a.hex),
  ]);
  const known = routeInfo?.flightroute;
  // Keep the airline even when the route is stale; only the from/to is dropped. Airlines often reuse
  // one number both ways, so a route that fits backwards is shown backwards.
  let flightroute = null;
  if (known && routeFits(a, known.origin, known.destination)) flightroute = known;
  else if (known && routeFits(a, known.destination, known.origin))
    flightroute = { ...known, origin: known.destination, destination: known.origin };
  const craft = craftInfo?.aircraft;
  const kind = KIND[a.category] || 'Plane';

  const icao = a.t || craft?.icao_type || '';
  return {
    who: known?.airline?.name || craft?.registered_owner || kind,
    flight: callsign || a.r || a.hex,
    type: TYPE_NAME[icao] || icao || kind,
    from: flightroute ? city(flightroute.origin) : '',
    to: flightroute ? city(flightroute.destination) : '',
    // Fuller detail for the voice assistant only.
    kind,
    model: craft ? `${craft.manufacturer || ''} ${craft.type || ''}`.trim() : icao,
  };
}

/** Radar centre for a request: explicit lat/lon (+ place) in the query, else Vercel's IP geolocation. */
export function centreFrom(url, headers) {
  if (url.searchParams.has('lat')) {
    return {
      lat: Number(url.searchParams.get('lat')),
      lon: Number(url.searchParams.get('lon')),
      place: url.searchParams.get('place') || '',
      custom: true,
    };
  }
  return {
    lat: Number(headers.get('x-vercel-ip-latitude')),
    lon: Number(headers.get('x-vercel-ip-longitude')),
    place: decodeURIComponent(headers.get('x-vercel-ip-city') ?? ''),
    custom: false,
  };
}

export function clampRadius(nm) {
  return Math.min(100, Math.max(4, Number(nm) || DEFAULT_RADIUS_NM));
}

/** Place name -> {lat, lon, name} via OpenStreetMap, or null. */
export async function geocode(query) {
  const res = await fetch(
    `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`,
    { headers: UA, signal: AbortSignal.timeout(5000) },
  );
  const [hit] = res.ok ? await res.json() : [];
  if (!hit) return null;
  return { lat: Number(hit.lat), lon: Number(hit.lon), name: hit.name || query };
}

/**
 * Aircraft within `radius` nm of (lat, lon), nearest first. The nearest `detailed` get plain-English
 * details; `full` also keeps the extra fields the voice assistant uses.
 */
export async function getFlights({ lat, lon, radius, place, detailed = 10, full = false }) {
  const res = await fetch(`https://api.adsb.lol/v2/point/${lat.toFixed(4)}/${lon.toFixed(4)}/${radius}`, {
    headers: UA,
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error(`adsb.lol ${res.status}`);
  const { ac = [] } = await res.json();

  const near = ac
    .filter((a) => typeof a.alt_baro === 'number' && a.dst != null && a.dir != null)
    .sort((a, b) => a.dst - b.dst)
    .slice(0, MAX_AIRCRAFT);
  const details = await Promise.all(near.slice(0, detailed).map((a) => describe(a)));

  const aircraft = near.map((a, i) => {
    const rate = a.baro_rate ?? a.geom_rate ?? 0;
    const d = details[i];
    return {
      dist: Math.round(a.dst * 10) / 10, // nm, for plotting
      bearing: Math.round(a.dir),
      track: Math.round(a.track ?? 0),
      speed: Math.round(a.gs ?? 0), // knots; the board uses it to glide planes between refreshes
      ...(d && {
        who: d.who,
        flight: d.flight,
        type: d.type,
        from: d.from,
        to: d.to,
        ...(full && { kind: d.kind, model: d.model }),
        km: Math.round(a.dst * KM_PER_NM),
        // `dir` is what the board's DIR column prints: which way the plane is flying. (Boards running
        // older code read only `dir`, so it carries the heading rather than a new field name.)
        dir: COMPASS[Math.round((a.track ?? 0) / 45) % 8],
        heading: COMPASS[Math.round((a.track ?? 0) / 45) % 8],
        from_centre: COMPASS[Math.round(a.dir / 45) % 8], // where it is, seen from the radar centre
        alt: a.alt_baro,
        trend: rate > 300 ? 'up' : rate < -300 ? 'down' : '',
      }),
    };
  });
  return { place, radius, km: Math.round(radius * KM_PER_NM), aircraft };
}
