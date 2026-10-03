// FlightAware fallback in lib/track.js, with adsb.lol, adsbdb, Nominatim and AeroAPI faked.
import test from 'node:test';
import assert from 'node:assert/strict';
import { track, schedule } from '../lib/track.js';

const H = 3600000;
const route = { callsign_icao: 'AFR12', callsign_iata: 'AF12', airline: { name: 'Air France' },
  origin: { municipality: 'Paris', iata_code: 'CDG', latitude: 49.01, longitude: 2.55 },
  destination: { municipality: 'New York', iata_code: 'JFK', latitude: 40.64, longitude: -73.78 } };

function fake({ flights = [], heardAs = null, sea = true } = {}) {
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push(String(url));
    const json = (body) => ({ ok: true, json: async () => body });
    if (url.includes('adsbdb')) return json({ response: { flightroute: route } });
    if (url.includes('adsb.lol')) {
      const cs = url.split('/').pop();
      return json({ ac: cs === heardAs ? [{ lat: 45, lon: -40, alt_baro: 36000, gs: 480, track: 260 }] : [] });
    }
    if (url.includes('nominatim')) return json(sea ? { error: 'Unable to geocode' } : { address: { country: 'Ireland' } });
    if (url.includes('aeroapi')) {
      assert.equal(opts.headers['x-apikey'], 'test-key');
      return json({ flights });
    }
    throw new Error('unexpected ' + url);
  };
  return calls;
}

test.beforeEach(() => { process.env.FLIGHTAWARE_KEY = 'test-key'; });

test('not heard but in the air: estimated position over the sea, landing time', async () => {
  const now = Date.now();
  const calls = fake({ flights: [{ actual_off: new Date(now - 4 * H).toISOString(), estimated_on: new Date(now + 4 * H).toISOString(), status: 'En Route' }] });
  const t = await track('AF012', { fa: true });
  assert.equal(t.seen, false);
  assert.equal(t.est, true);
  assert.equal(t.schedule.state, 'air');
  assert.equal(t.over, 'the open sea');
  assert.ok(t.lon < -20 && t.lon > -50, `halfway across the Atlantic, got ${t.lon}`);
  assert.ok(Math.abs(t.eta_min - 240) <= 1);
  assert.ok(t.track > 240 && t.track < 300, 'heading west');
  assert.equal(calls.filter((u) => u.includes('aeroapi')).length, 1);
});

test('no fa: FlightAware is not asked (each lookup costs)', async () => {
  const calls = fake();
  const t = await track('AF12');
  assert.equal(t.seen, false);
  assert.equal(calls.some((u) => u.includes('aeroapi')), false);
});

test('heard by receivers: FlightAware is not asked', async () => {
  const calls = fake({ heardAs: 'AFR12' });
  const t = await track('AF12', { fa: true });
  assert.equal(t.seen, true);
  assert.equal(calls.some((u) => u.includes('aeroapi')), false);
});

test('flying under another ATC callsign: found under that one', async () => {
  const now = Date.now();
  fake({ heardAs: 'AFR53GU', flights: [{ atc_ident: 'AFR53GU', actual_off: new Date(now - H).toISOString(), estimated_on: new Date(now + 7 * H).toISOString() }] });
  const t = await track('AF12', { fa: true });
  assert.equal(t.seen, true);
  assert.equal(t.callsign, 'AFR53GU');
});

test('schedule picks the flight nearest now: tomorrow\'s departure over last week\'s landing', async () => {
  const now = Date.now();
  fake({ flights: [
    { actual_off: new Date(now - 30 * H).toISOString(), actual_on: new Date(now - 22 * H).toISOString() },
    { scheduled_off: new Date(now + 3 * H).toISOString(), scheduled_on: new Date(now + 11 * H).toISOString() },
    { cancelled: true, scheduled_off: new Date(now + H).toISOString() },
  ] });
  const s = await schedule('AFR12', now);
  assert.equal(s.state, 'scheduled');
  assert.match(s.off_uk, /^\d{1,2}:\d\d(am|pm)$/);
});

test('landed recently: state landed', async () => {
  const now = Date.now();
  fake({ flights: [{ actual_off: new Date(now - 9 * H).toISOString(), actual_on: new Date(now - H / 2).toISOString() },
    { scheduled_off: new Date(now + 23 * H).toISOString() }] });
  assert.equal((await schedule('AFR12', now)).state, 'landed');
});

test('no key: no lookup', async () => {
  delete process.env.FLIGHTAWARE_KEY;
  const calls = fake();
  assert.equal(await schedule('AFR12'), null);
  assert.equal(calls.length, 0);
});
