// Current weather at the board's location (Vercel IP geolocation) for its today screen.
// GET ?k=VOICE_KEY
import { centreFrom } from '../lib/flights.js';
import { getWeather } from '../lib/weather.js';

export async function GET(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  // Home only (never the radar's place): the phone location the board saved, else IP geolocation.
  const home = new URL('http://x/');
  for (const k of ['home_lat', 'home_lon', 'home_place']) if (url.searchParams.has(k)) home.searchParams.set(k, url.searchParams.get(k));
  const { lat, lon, place } = centreFrom(home, request.headers);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return new Response('no location', { status: 400 });
  }
  let data;
  try {
    data = { place, ...(await getWeather(lat, lon)) };
  } catch (e) {
    return new Response(String(e.message), { status: 502 });
  }
  const body = Buffer.from(JSON.stringify(data));
  return new Response(body, {
    headers: { 'Content-Type': 'application/json', 'Content-Length': String(body.length) },
  });
}
