// Nearby aircraft for the desk board's radar screen.
// GET ?k=VOICE_KEY[&lat=..&lon=..&place=..][&r=nm]. Without lat/lon, uses Vercel's IP geolocation.
import { centreFrom, clampRadius, getFlights } from '../lib/flights.js';

export async function GET(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  const { lat, lon, place } = centreFrom(url, request.headers);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return new Response('no location', { status: 400 });
  }
  let data;
  try {
    data = await getFlights({ lat, lon, radius: clampRadius(url.searchParams.get('r')), place });
  } catch (e) {
    return new Response(String(e.message), { status: 502 });
  }
  const body = Buffer.from(JSON.stringify(data));
  return new Response(body, {
    headers: { 'Content-Type': 'application/json', 'Content-Length': String(body.length) },
  });
}
