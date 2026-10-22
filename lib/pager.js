// Agent events for the glasses (api/agent.js): the Mac's Claude Code / Codex hooks post them, the
// iPhone app polls and speaks them. The newest KEEP live in one Upstash Redis list for a day. Plain
// REST calls (KV_REST_API_URL / KV_REST_API_TOKEN) so desk-voice needs no Redis client.
const KEY = 'glasses:agent-events';
const KEEP = 20;
const DAY_S = 86400;
// Claude's permission questions carry an id; the answer said through the glasses waits here for the Mac hook.
const REPLY_S = 600;
// The app marks the glasses as on every ~25 s while they're connected; the Mac hook only waits for a
// spoken answer while they are, so at the desk the usual prompt isn't held up.
const LIVE_KEY = 'glasses:live';
const LIVE_S = 60;
export const ID = /^[a-z0-9]{8,40}$/;

async function redis(commands, fetchImpl = fetch) {
  const url = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) throw new Error('agent event storage is not configured');
  const res = await fetchImpl(`${url}/pipeline`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(commands),
    signal: AbortSignal.timeout(4000),
  });
  if (!res.ok) throw new Error(`storage answered ${res.status}`);
  return (await res.json()).map((r) => r.result);
}

const clip = (v, n) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, n);

// {agent, project, kind: 'done'|'needs', message} -> the stored event, stamped with `at` (ms).
export function cleanEvent(e, now = Date.now()) {
  if (!e || typeof e !== 'object' || !['done', 'needs'].includes(e.kind)) return null;
  const agent = clip(e.agent, 40), project = clip(e.project, 80);
  if (!agent) return null;
  const event = { agent, project, kind: e.kind, message: clip(e.message, 240), at: now };
  if (e.kind === 'needs' && typeof e.id === 'string' && ID.test(e.id)) event.id = e.id;
  return event;
}

export async function pushEvent(event, fetchImpl = fetch) {
  await redis([['LPUSH', KEY, JSON.stringify(event)], ['LTRIM', KEY, 0, KEEP - 1], ['EXPIRE', KEY, DAY_S]], fetchImpl);
}

// Oldest first, only those after `since` (ms).
export async function eventsSince(since = 0, fetchImpl = fetch) {
  const [raw] = await redis([['LRANGE', KEY, 0, KEEP - 1]], fetchImpl);
  return (raw || []).map((s) => { try { return JSON.parse(s); } catch { return null; } })
    .filter((e) => e && e.at > since).reverse();
}

export async function markLive(fetchImpl = fetch) {
  await redis([['SET', LIVE_KEY, '1', 'EX', LIVE_S]], fetchImpl);
}

export async function isLive(fetchImpl = fetch) {
  const [v] = await redis([['GET', LIVE_KEY]], fetchImpl);
  return v === '1';
}

export async function setReply(id, choice, fetchImpl = fetch) {
  await redis([['SET', `glasses:agent-reply:${id}`, choice, 'EX', REPLY_S]], fetchImpl);
}

export async function getReply(id, fetchImpl = fetch) {
  const [v] = await redis([['GET', `glasses:agent-reply:${id}`]], fetchImpl);
  return v || null;
}

// The answer to "Allow, deny, or always allow?". Any "no" wins, so "don't allow" denies; anything
// unclear is no answer at all and the question stays on the Mac.
const DENY = /\b(no|nope|deny|denied|don'?t|do not|stop|cancel|reject|block)\b/i;
const ALWAYS = /\balways\b/i;
const ALLOW = /\b(yes|yeah|yep|yup|allow|allowed|approve|go ahead|do it|run it)\b/i;
export function replyFrom(heard) {
  return DENY.test(heard) ? 'deny' : ALWAYS.test(heard) ? 'always' : ALLOW.test(heard) ? 'allow' : null;
}

// "Claude needs you in ezmeta. Wants to run: npm test." (the iPhone app's Pager.sentence, for "what did Claude say?")
export function sentence(e) {
  const project = e.project ? ` in ${e.project}` : '';
  return e.kind === 'needs' ? `${e.agent} needs you${project}. ${e.message}`.trim()
    : `${e.agent} finished${project}.` + (e.message ? ` ${e.message}` : '');
}
