// Follow one flight by its number (BA36, BAW036...) for the board's track screen and the voice
// assistant. Position from adsb.lol, route from adsbdb, "over Germany" from OpenStreetMap.
// Over oceans and remote land there are no receivers, so a flight can drop out for hours: then
// FlightAware's schedule (FLIGHTAWARE_KEY) says whether it has taken off, when it lands, and so
// where it should be by now.
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
    return null;                            // unknown, as opposed to '' (no country: the sea)
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

async function heard(callsign) {
  const { ac = [] } = await getJson(`https://api.adsb.lol/v2/callsign/${callsign}`, UA, 6000);
  return ac.find((x) => typeof x.lat === 'number');
}

const ukTime = (iso) => new Date(iso).toLocaleTimeString('en-GB', { timeZone: 'Europe/London', hour: 'numeric', minute: '2-digit', hour12: true }).replace(/\s/g, '');

/** FlightAware's take on the flight nearest now: the one in the air, else the closest take-off or
 * landing. AeroAPI personal tier: $0.005 a lookup against $5 free a month, so only on request. */
export async function schedule(callsign, now = Date.now()) {
  const key = process.env.FLIGHTAWARE_KEY;
  if (!key) return null;
  let flights;
  try {
    ({ flights = [] } = await getJson(`https://aeroapi.flightaware.com/aeroapi/flights/${callsign}`, { ...UA, 'x-apikey': key }, 6000));
  } catch {
    return null;
  }
  const at = (s) => (s ? Date.parse(s) : Infinity);
  const live = flights.filter((f) => !f.cancelled && !f.position_only);
  const f = live.find((x) => x.actual_off && !x.actual_on) ||
    live.map((x) => [Math.abs((x.actual_on ? at(x.actual_on) : at(x.estimated_off || x.scheduled_off)) - now), x])
      .sort((p, q) => p[0] - q[0])[0]?.[1];
  if (!f) return null;
  const off = f.actual_off || f.estimated_off || f.scheduled_off, on = f.actual_on || f.estimated_on || f.scheduled_on;
  return {
    state: f.actual_on ? 'landed' : f.actual_off ? 'air' : 'scheduled',
    status: f.status || '',
    off, on, off_uk: off ? ukTime(off) : '', on_uk: on ? ukTime(on) : '',
    atc: f.atc_ident || '',               // the callsign it broadcasts, when not the usual one
  };
}

// Point `frac` of the way along the great circle a -> b, and the heading there.
function along(a, b, frac) {
  const v = (la, lo) => [Math.cos(la * RAD) * Math.cos(lo * RAD), Math.cos(la * RAD) * Math.sin(lo * RAD), Math.sin(la * RAD)];
  const p = v(a.lat, a.lon), q = v(b.lat, b.lon);
  const d = Math.acos(Math.min(1, p[0] * q[0] + p[1] * q[1] + p[2] * q[2]));
  const s = d < 1e-9 ? [1 - frac, frac] : [Math.sin((1 - frac) * d) / Math.sin(d), Math.sin(frac * d) / Math.sin(d)];
  const w = [0, 1, 2].map((k) => s[0] * p[k] + s[1] * q[k]);
  const lat = Math.atan2(w[2], Math.hypot(w[0], w[1])) / RAD, lon = Math.atan2(w[1], w[0]) / RAD;
  const y = Math.sin((b.lon - lon) * RAD) * Math.cos(b.lat * RAD);
  const x = Math.cos(lat * RAD) * Math.sin(b.lat * RAD) - Math.sin(lat * RAD) * Math.cos(b.lat * RAD) * Math.cos((b.lon - lon) * RAD);
  return { lat, lon, track: (Math.atan2(y, x) / RAD + 360) % 360 };
}

/** Where `flight` is now. {flight, callsign, airline, from, to, seen, ...position when seen}.
 * `fa`: ask FlightAware when no receiver hears it. `cs`: the callsign it was last heard under. */
export async function track(flight, { fa = false, cs = '' } = {}) {
  flight = cleanFlight(flight);
  if (!flight) return { ok: false, error: 'not a flight number' };
  const r = await route(flight);
  let callsign = /^[A-Z0-9]{3,8}$/.test(cs) ? cs : r?.callsign_icao || flight;
  let a = await heard(callsign);
  let sched = null;
  if (!a && fa) {
    sched = await schedule(r?.callsign_icao || flight);
    // Airlines often fly under another ATC callsign (Air France: AFR16UE): look again under that.
    if (sched?.atc && sched.atc !== callsign) {
      a = await heard(sched.atc);
      if (a) callsign = sched.atc;
    }
  }
  const out = {
    ok: true,
    flight: r?.callsign_iata || flight,
    callsign,
    airline: r?.airline?.name || '',
    from: airport(r?.origin),
    to: airport(r?.destination),
    seen: Boolean(a),
  };
  if (sched) out.schedule = sched;
  if (!a) {
    const { from, to } = out;
    if (sched?.state === 'air' && from && to && sched.off && sched.on) {
      // Not heard (over the sea, most likely), but in the air: where the timetable puts it.
      const t0 = Date.parse(sched.off), t1 = Date.parse(sched.on), now = Date.now();
      const p = along(from, to, Math.max(0, Math.min(1, (now - t0) / (t1 - t0))));
      const total = kmBetween(from.lat, from.lon, to.lat, to.lon), left = kmBetween(p.lat, p.lon, to.lat, to.lon);
      const where = await over(p.lat, p.lon);
      Object.assign(out, {
        est: true, ...p, on_ground: false,
        speed_kmh: Math.round(total / Math.max(0.5, (t1 - t0) / 3600000)),
        over: where === '' ? 'the open sea' : where || '',
        km_left: Math.round(left), km_total: Math.round(total),
        eta_min: Math.max(0, Math.round((t1 - now) / 60000)),
      });
    }
    return out;
  }
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
