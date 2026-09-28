// Follow one flight by its number (BA36, BAW036...) for the board's track screen and the voice
// assistant. Position from adsb.lol, route from adsbdb, "over Germany" from OpenStreetMap.
// Over oceans and remote land there are no receivers, so a flight can drop out for hours: the board
// keeps the last position it saw.
import { TYPE_NAME } from './flights.js';

const UA = { 'User-Agent': 'desk-voice/1.0 (+https://github.com/evxnche)' };
const RAD = Math.PI / 180;
const KM_PER_NM = 1.852;

function kmBetween(lat1, lon1, lat2, lon2) {
  const a = Math.sin(((lat2 - lat1) * RAD) / 2) ** 2 +
    Math.cos(lat1 * RAD) * Math.cos(lat2 * RAD) * Math.sin(((lon2 - lon1) * RAD) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

async function getJson(url, headers = UA, ms = 5000) {
  const res = await fetch(url, { headers, signal: AbortSignal.timeout(ms) });
  if (!res.ok) throw new Error(`${new URL(url).host} ${res.status}`);
  return res.json();
}

// "BAW036", "ba 36", "BA036" -> "BAW36" / "BA36" (no spaces, no leading zeros in the number).
export function cleanFlight(s) {
  const m = /^([a-z]{2,3}|[a-z]\d|\d[a-z])\s*0*(\d{1,4}[a-z]?)$/i.exec(String(s || '').replace(/[\s-]/g, ''));
  return m ? (m[1] + m[2]).toUpperCase() : '';
}

const routes = new Map();   // warm instances reuse these
const countries = new Map();

// Route + the ICAO callsign aircraft broadcast (adsbdb answers for BA36 and BAW36 alike).
async function route(flight) {
  if (routes.has(flight)) return routes.get(flight);
  let r = null;
  try {
    const res = await getJson(`https://api.adsbdb.com/v0/callsign/${flight}`);
    if (typeof res.response === 'object') r = res.response.flightroute;
  } catch {
    return null;
  }
  routes.set(flight, r);
  return r;
}

async function over(lat, lon) {
  const key = `${Math.round(lat)},${Math.round(lon)}`;
  if (countries.has(key)) return countries.get(key);
  let name = '';
  try {
    const a = await getJson(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=3&lat=${lat}&lon=${lon}`,
      { ...UA, 'Accept-Language': 'en' }, 4000);
    name = a.address?.country || '';
  } catch {
    return '';
  }
  countries.set(key, name);
  return name;
}

function airport(ap) {
  if (!ap) return null;
  return {
    city: (ap.municipality || ap.name || ap.iata_code || '').split(/[/,(]/)[0].trim(),
    code: ap.iata_code || ap.icao_code || '',
    lat: ap.latitude, lon: ap.longitude,
  };
}

/** Where `flight` is now. {flight, callsign, airline, from, to, seen, ...position when seen}. */
export async function track(flight) {
  flight = cleanFlight(flight);
  if (!flight) return { ok: false, error: 'not a flight number' };
  const r = await route(flight);
  const callsign = r?.callsign_icao || flight;
  const { ac = [] } = await getJson(`https://api.adsb.lol/v2/callsign/${callsign}`, UA, 6000);
  const a = ac.find((x) => typeof x.lat === 'number');
  const out = {
    ok: true,
    flight: r?.callsign_iata || flight,
    callsign,
    airline: r?.airline?.name || '',
    from: airport(r?.origin),
    to: airport(r?.destination),
    seen: Boolean(a),
  };
  if (!a) return out;
  const ground = a.alt_baro === 'ground';
  const to = out.to, from = out.from;
  const kmLeft = to ? kmBetween(a.lat, a.lon, to.lat, to.lon) : null;
  const kmTotal = to && from ? kmBetween(from.lat, from.lon, to.lat, to.lon) : null;
  const kmh = Math.round((a.gs || 0) * KM_PER_NM);
  Object.assign(out, {
    lat: a.lat, lon: a.lon,
    alt_ft: ground ? 0 : a.alt_baro,
    on_ground: ground,
    speed_kmh: kmh,
    track: Math.round(a.track ?? 0),
    vrate: a.baro_rate ?? a.geom_rate ?? 0,
    type: TYPE_NAME[a.t] || a.t || '',
    reg: a.r || '',
    over: await over(a.lat, a.lon),
    km_left: kmLeft == null ? null : Math.round(kmLeft),
    km_total: kmTotal == null ? null : Math.round(kmTotal),
    // Straight line at today's speed, plus ~10 min for the approach and landing.
    eta_min: kmLeft != null && kmh > 150 && !ground ? Math.round((kmLeft / kmh) * 60 + (kmLeft > 60 ? 10 : 3)) : null,
  });
  return out;
}
