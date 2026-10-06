import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildPlan, calendarScreen, deskPalNote, noteRows, projectScreen, taskScreen } from '../lib/plan.js';

const BODY = `# to-do
- [ ] Call the bank
- [x] Pay rent
☐ Book flights
# building
- ezOS plan screen
# shift
- desk pal
## notes
- not an item
\`\`\`
# idea
- fenced, ignored
\`\`\`
# idea
* reader articles`;

test('noteRows reads the same sections the board does', () => {
  assert.deepEqual(noteRows(BODY), [
    { section: 'todo', text: 'Call the bank', done: false },
    { section: 'todo', text: 'Pay rent', done: true },
    { section: 'todo', text: 'Book flights', done: false },
    { section: 'building', text: 'ezOS plan screen', done: false },
    { section: 'shipped', text: 'desk pal', done: false },
    { section: 'idea', text: 'reader articles', done: false },
  ]);
});

test('task and project screens group rows', () => {
  const items = noteRows(BODY);
  assert.deepEqual(taskScreen(items).rows.map((r) => [r.k, r.t, r.done]), [
    ['head', 'To do (2)', undefined], ['task', 'Call the bank', undefined], ['task', 'Book flights', undefined],
    ['head', 'Done (1)', undefined], ['task', 'Pay rent', true]]);
  assert.deepEqual(projectScreen(items).rows.map((r) => r.t),
    ['Idea (1)', 'reader articles', 'Building (1)', 'ezOS plan screen', 'Shipped (1)', 'desk pal']);
  assert.equal(taskScreen([]).rows[1].t, 'Nothing to do');
});

test('deskPalNote falls back to the title when the id is gone', () => {
  const note = { id: 'b', title: ' Desk pal ', body: '', archived: false };
  assert.equal(deskPalNote({ deskPalId: 'gone', notes: [{ id: 'a', title: 'x', archived: false }, note] }), note);
});

test('calendarScreen drops finished events and labels days', () => {
  const now = new Date('2026-10-07T12:00:00Z');   // 13:00 in London
  const cal = { today: [{ s: 540, e: 600, t: 'Gone' }, { s: 840, e: 900, t: 'Sync' }],
    upcoming: [{ day: 'Tomorrow', s: 600, t: 'Dentist' }], failed: 0 };
  assert.deepEqual(calendarScreen(cal, now).rows.map((r) => [r.k, r.time, r.t]), [
    ['head', undefined, 'Today, Wed 7 Oct'], ['event', '2:00pm', 'Sync'], ['head', undefined, 'Tomorrow'], ['event', '10:00am', 'Dentist']]);
});

test('buildPlan reports a missing note and missing calendars on their screens', async () => {
  const plan = await buildPlan({ ok: true, deskPalId: null, notes: [] }, '');
  assert.deepEqual(plan.screens.map((s) => s.title), ['Tasks', 'Projects', 'Calendar']);
  assert.match(plan.screens[0].rows[0].t, /Desk Pal/);
  assert.match(plan.screens[2].rows[0].t, /No calendars/);
});
