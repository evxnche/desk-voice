// Agent events for the glasses (api/agent.js): the Mac's Claude Code / Codex hooks post them, the
// iPhone app polls and speaks them. The newest KEEP live in one Upstash Redis list for a day. Plain
// REST calls (KV_REST_API_URL / KV_REST_API_TOKEN) so desk-voice needs no Redis client.
const KEY = 'glasses:agent-events';
const KEEP = 20;
const DAY_S = 86400;

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
  return { agent, project, kind: e.kind, message: clip(e.message, 240), at: now };
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
