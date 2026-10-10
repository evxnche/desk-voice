import assert from 'node:assert/strict';
import test from 'node:test';
import { noteText, READY, stamp, TASKY } from '../api/glasses.js';
import { addNotyTask, saveNotyNote } from '../lib/noty-write.js';
import { cleanEvent, eventsSince } from '../lib/pager.js';

test('notes are recognised without the model', () => {
  assert.equal(noteText('Note: buy solder.'), 'buy solder');
  assert.equal(noteText('Take a note, call mum about Sunday'), 'call mum about Sunday');
  assert.equal(noteText('note to self pick up the parcel'), 'pick up the parcel');
  assert.equal(noteText('Write down a note: the lamp idea'), 'the lamp idea');
  assert.equal(noteText('Notes app is slow'), null);
  assert.equal(noteText('What did my note say?'), null);
  assert.equal(noteText('Note'), null);
});

test('task and reading requests', () => {
  for (const s of ['Add buy solder to my tasks', 'put call the bank on my to-do list', 'Remind me to water the plants']) assert.ok(TASKY.test(s), s);
  for (const s of ["What's on my to-do list?", 'How many tasks do I have?']) assert.ok(!TASKY.test(s), s);
  for (const s of ['Read my articles', 'start ezRead', 'play my reading list', 'EZ read']) assert.ok(READY.test(s), s);
  for (const s of ['What article did I save last?', 'Read me the weather']) assert.ok(!READY.test(s), s);
});

test('Inbox lines are stamped in local time', () => {
  assert.equal(stamp(new Date('2026-10-10T16:11:00Z')), '10 Oct 9:41 pm');
});

function fakeNoty(state) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    const path = new URL(url).pathname, body = init.body && JSON.parse(init.body);
    calls.push({ path, method: init.method, body, auth: init.headers.Authorization });
    const json = path === '/api/notes' ? (body ? { notes: [], conflicts: [] } : { notes: state.notes, deskPalId: state.deskPalId })
      : body ? { tasks: [], conflicts: [] } : { tasks: state.tasks };
    return { ok: true, json: async () => json };
  };
  return { calls, fetchImpl };
}

const DESK = { id: '12A8FD27-0000-4000-8000-000000000001', title: 'desk pal', body: '# to-do\n☐ A', archived: false, deleted: false, version: 3, taskIds: [] };

test('a task is added at the end of the Desk Pal list', async () => {
  process.env.NOTY_SYNC_TOKEN = 'tok';
  const { calls, fetchImpl } = fakeNoty({ notes: [DESK], deskPalId: DESK.id.toLowerCase(),
    tasks: [{ noteId: DESK.id, position: 0, deleted: false }, { noteId: DESK.id, position: 4, deleted: true }, { noteId: 'other', position: 9, deleted: false }] });
  assert.deepEqual(await addNotyTask('buy solder', fetchImpl), { list: 'desk pal' });
  const post = calls.at(-1);
  assert.equal(post.path, '/api/sync');
  assert.equal(post.auth, 'Bearer tok');
  const { task, base } = post.body.changes[0];
  assert.equal(base, null);
  assert.deepEqual({ ...task, id: 'x' }, { id: 'x', noteId: DESK.id, listTitle: 'desk pal', text: 'buy solder',
    completed: false, position: 1, deleted: false, version: 0 });
});

test('notes append to Inbox, which is made on first use', async () => {
  process.env.NOTY_SYNC_TOKEN = 'tok';
  const inbox = { ...DESK, id: 'AAAAAAAA-0000-4000-8000-000000000002', title: 'Inbox', body: 'old line\n\n' };
  let { calls, fetchImpl } = fakeNoty({ notes: [DESK, inbox] });
  await saveNotyNote('lamp idea', '10 Oct 9:41 pm', fetchImpl);
  assert.deepEqual(calls.at(-1).body.changes, [{ note: { ...inbox, body: 'old line\n10 Oct 9:41 pm lamp idea' }, base: inbox }]);

  ({ calls, fetchImpl } = fakeNoty({ notes: [DESK] }));
  await saveNotyNote('lamp idea', '10 Oct 9:41 pm', fetchImpl);
  const { note, base } = calls.at(-1).body.changes[0];
  assert.equal(base, null);
  assert.deepEqual({ ...note, id: 'x' }, { id: 'x', title: 'Inbox', body: '10 Oct 9:41 pm lamp idea', archived: false, deleted: false, version: 0, taskIds: [] });
});

test('agent events are cleaned and returned oldest first after `since`', async () => {
  assert.equal(cleanEvent({ agent: 'Claude', kind: 'other' }), null);
  assert.equal(cleanEvent({ agent: '', kind: 'done' }), null);
  assert.deepEqual(cleanEvent({ agent: 'Codex', project: ' ezmeta ', kind: 'needs', message: 'a\n b' }, 5),
    { agent: 'Codex', project: 'ezmeta', kind: 'needs', message: 'a b', at: 5 });
  process.env.KV_REST_API_URL = 'https://kv.example';
  process.env.KV_REST_API_TOKEN = 'kv';
  const stored = [{ at: 30 }, { at: 20 }, { at: 10 }].map((e) => JSON.stringify(e));   // LPUSH: newest first
  const fetchImpl = async () => ({ ok: true, json: async () => [{ result: stored }] });
  assert.deepEqual(await eventsSince(10, fetchImpl), [{ at: 20 }, { at: 30 }]);
});
