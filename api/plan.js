// The plan for the Xteink reader (ezOS): Tasks, Projects and Calendar screens from the Desk Pal note
// and the calendars in PLAN_CALENDARS (private iCal links, space-separated). GET ?k=PLAN_KEY: the reader's
// own key, so it never holds the voice server's VOICE_KEY.
import { fetchNotyNotes } from '../lib/noty.js';
import { buildPlan } from '../lib/plan.js';

export async function GET(request) {
  const url = new URL(request.url);
  if (!process.env.PLAN_KEY || url.searchParams.get('k') !== process.env.PLAN_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  const plan = await buildPlan(await fetchNotyNotes(), process.env.PLAN_CALENDARS);
  const body = Buffer.from(JSON.stringify(plan));
  return new Response(body, {
    headers: { 'Content-Type': 'application/json', 'Content-Length': String(body.length), 'Cache-Control': 'no-store' },
  });
}
