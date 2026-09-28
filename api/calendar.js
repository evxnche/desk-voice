// Today's and tomorrow's calendar for the board (companion.py: meeting heads-ups, when to offer a
// focus session). GET ?k=VOICE_KEY with X-Calendar: the private iCal link.
import { getCalendar } from '../lib/calendar.js';

export async function GET(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  let data;
  try {
    data = await getCalendar(request.headers.get('x-calendar'));
  } catch (e) {
    return new Response(String(e.message), { status: 502 });
  }
  // Short titles: the board only has a few KB to spare and a 50-character line.
  for (const list of [data.today, data.tomorrow]) for (const ev of list) ev.t = ev.t.slice(0, 60);
  const body = Buffer.from(JSON.stringify(data));
  return new Response(body, {
    headers: { 'Content-Type': 'application/json', 'Content-Length': String(body.length) },
  });
}
