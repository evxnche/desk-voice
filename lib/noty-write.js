// Writing to Noty from the glasses (api/glasses.js). Tasks go to the Desk Pal note's to-do section
// through Noty's task API, which inserts them as ☐ rows the board and the Mac pick up. Notes are
// appended to a note titled "Inbox", made on first use. Same server-only NOTY_SYNC_TOKEN as lib/noty.js.
import { randomUUID } from 'node:crypto';

export const INBOX_TITLE = 'Inbox';

async function call(path, { method = 'GET', body, fetchImpl = fetch } = {}) {
  const token = process.env.NOTY_SYNC_TOKEN;
  const base = process.env.NOTY_NOTES_URL;
  if (!token || !base) throw new Error('Noty is not configured (set NOTY_NOTES_URL and NOTY_SYNC_TOKEN)');
  const url = new URL(path, base);
  const res = await fetchImpl(url.href, {
    method,
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json', ...(body && { 'Content-Type': 'application/json' }) },
    ...(body && { body: JSON.stringify(body) }),
    cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(6000),
  });
  if (!res.ok) throw new Error(`Noty ${path} answered ${res.status}`);
  return res.json();
}

const same = (a, b) => String(a).toLowerCase() === String(b).toLowerCase();
const newId = () => randomUUID().toUpperCase();

// Adds an unticked task to the end of the Desk Pal note's to-do list.
export async function addNotyTask(text, fetchImpl = fetch) {
  const { notes, deskPalId } = await call('/api/notes', { fetchImpl });
  const deskPal = deskPalId && notes.find((n) => same(n.id, deskPalId) && !n.deleted);
  if (!deskPal) throw new Error('No Desk Pal note is selected in Noty');
  const { tasks } = await call('/api/sync', { fetchImpl });
  const mine = tasks.filter((t) => same(t.noteId, deskPal.id) && !t.deleted);
  const position = mine.length ? Math.max(...mine.map((t) => t.position)) + 1 : 0;
  const task = { id: newId(), noteId: deskPal.id, listTitle: deskPal.title.trim() || 'Desk Pal', text,
    completed: false, position, deleted: false, version: 0 };
  const res = await call('/api/sync', { method: 'POST', body: { changes: [{ task, base: null }] }, fetchImpl });
  if (res.conflicts?.length) throw new Error('Noty reported a conflict');
  return { list: task.listTitle };
}

// Appends one timestamped line to the Inbox note.
export async function saveNotyNote(text, stamp, fetchImpl = fetch) {
  const { notes } = await call('/api/notes', { fetchImpl });
  const inbox = notes.find((n) => !n.deleted && same(n.title.trim(), INBOX_TITLE));
  const line = `${stamp} ${text}`;
  const change = inbox
    ? { note: { ...inbox, body: inbox.body.trimEnd() ? `${inbox.body.trimEnd()}\n${line}` : line }, base: inbox }
    : { note: { id: newId(), title: INBOX_TITLE, body: line, archived: false, deleted: false, version: 0, taskIds: [] }, base: null };
  const res = await call('/api/notes', { method: 'POST', body: { changes: [change] }, fetchImpl });
  if (res.conflicts?.length) throw new Error('Noty reported a conflict');
  return { note: INBOX_TITLE };
}
