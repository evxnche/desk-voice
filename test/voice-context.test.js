import assert from 'node:assert/strict';
import test from 'node:test';
import { applyBoardBackstops, boardTools, decodeDeviceContext, firstToolFor } from '../api/voice.js';

const header = (value) => Buffer.from(JSON.stringify(value)).toString('base64');
const request = (memories, alert) => new Request('https://example.test/', { headers: {
  ...(memories !== undefined && { 'x-memories': header(memories) }),
  ...(alert !== undefined && { 'x-agent-alert': header(alert) }),
} });

test('device context accepts bounded explicit memories and latest needs alert', () => {
  assert.deepEqual(decodeDeviceContext(request(['Focus is 40 minutes'],
    { agent: 'Claude', project: 'Desk', kind: 'needs', message: 'Approve change', at: '10:00' })), {
    memories: ['Focus is 40 minutes'],
    alert: { agent: 'Claude', project: 'Desk', kind: 'needs', message: 'Approve change', at: '10:00' },
  });
});

test('device context rejects malformed, oversized and wrong-shaped headers', () => {
  assert.deepEqual(decodeDeviceContext(new Request('https://example.test/', { headers: {
    'x-memories': 'not base64!', 'x-agent-alert': 'x'.repeat(5000),
  } })), { memories: [], alert: null });
  assert.deepEqual(decodeDeviceContext(request(Array(13).fill('x'), { kind: 'done', message: 'Done' })),
    { memories: [], alert: null });
  assert.deepEqual(decodeDeviceContext(request(['x'.repeat(141)], { kind: 'needs', message: 'x'.repeat(501) })),
    { memories: [], alert: null });
});

test('clear memory commands are routed to a named tool before chat', () => {
  assert.equal(firstToolFor('Remember that my focus is 40 minutes', false), 'save_memory');
  assert.equal(firstToolFor('Remember my usual focus session is 40 minutes', false), 'save_memory');
  assert.equal(firstToolFor('Forget my focus preference', false), 'forget_memory');
  assert.equal(firstToolFor('Forget everything you remember about me', false), 'forget_memory');
  assert.equal(firstToolFor('What does Claude need?', true), 'show_agent_alert');
  assert.equal(firstToolFor('Show the latest agent alert', false), 'show_agent_alert');
  assert.equal(firstToolFor('What does Claude need?', false), null);
});

test('memory and alert requests do not assemble unrelated timer, radar or screen commands', async () => {
  const heard = 'Remember my usual focus session is 40 minutes';
  const commands = [];
  await boardTools(commands, '', { memories: [], alert: null }).save_memory.execute({ text: 'My usual focus session is 40 minutes' });
  const view = { radius: 20 };
  const changes = {};
  applyBoardBackstops(heard, firstToolFor(heard, false), commands, view, changes, []);
  assert.deepEqual(commands, [{ do: 'memory_add', text: 'My usual focus session is 40 minutes' }]);
  assert.deepEqual(changes, {});
  applyBoardBackstops('Show the latest agent alert and the radar 100 km', 'show_agent_alert',
    commands, view, changes, ['get_nearby_flights']);
  assert.deepEqual(commands, [{ do: 'memory_add', text: 'My usual focus session is 40 minutes' }]);
  assert.deepEqual(changes, {});
  const normal = [];
  applyBoardBackstops('Start a 25 minute focus', null, normal, { radius: 20 }, {}, []);
  assert.deepEqual(normal, [{ do: 'timer', minutes: 25, label: 'Focus' }]);
});

test('save tool rejects a memory over 140 UTF-8 bytes', async () => {
  const commands = [];
  const result = await boardTools(commands, '', { memories: [], alert: null }).save_memory.execute({ text: '🦀'.repeat(36) });
  assert.equal(result.ok, false);
  assert.deepEqual(commands, []);
});

test('memory header uses UTF-8 bytes rather than JavaScript string length', () => {
  assert.deepEqual(decodeDeviceContext(request(['🦀'.repeat(35)])).memories, ['🦀'.repeat(35)]);
  assert.deepEqual(decodeDeviceContext(request(['🦀'.repeat(36)])).memories, []);
});
