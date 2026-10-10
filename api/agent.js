// Agent pager mailbox for the glasses app (lib/pager.js). ?k=VOICE_KEY on both:
//   POST {agent, project, kind: 'done'|'needs', message}  from mac/deskpal-notify.py
//   GET  ?since=<ms>  -> {events: [...oldest first], now}  polled by the iPhone app
import { cleanEvent, eventsSince, pushEvent } from '../lib/pager.js';

const allowed = (url) => process.env.VOICE_KEY && url.searchParams.get('k') === process.env.VOICE_KEY;

export async function POST(request) {
  if (!allowed(new URL(request.url))) return new Response('unauthorized', { status: 401 });
  let event;
  try { event = cleanEvent(await request.json()); } catch { event = null; }
  if (!event) return new Response('bad event', { status: 400 });
  await pushEvent(event);
  return Response.json({ ok: true });
}

export async function GET(request) {
  const url = new URL(request.url);
  if (!allowed(url)) return new Response('unauthorized', { status: 401 });
  const since = Number(url.searchParams.get('since')) || 0;
  return Response.json({ events: await eventsSince(since), now: Date.now() }, { headers: { 'Cache-Control': 'no-store' } });
}
