// One flight's position and progress for the board's track screen.
// GET ?k=VOICE_KEY&f=BA36 (any spelling: BAW036, ba 36...)[&fa=1: ask FlightAware if unheard][&cs=AFR16UE].
import { track } from '../lib/track.js';

export async function GET(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  let data;
  try {
    data = await track(url.searchParams.get('f'), { fa: url.searchParams.get('fa') === '1', cs: url.searchParams.get('cs') || '' });
  } catch (e) {
    return new Response(String(e.message), { status: 502 });
  }
  const body = Buffer.from(JSON.stringify(data));
  return new Response(body, {
    status: data.ok ? 200 : 400,
    headers: { 'Content-Type': 'application/json', 'Content-Length': String(body.length) },
  });
}
