// Disposable live fixture: never edit a pre-existing task or Mac note.
import { readFile, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { isDeepStrictEqual } from 'node:util';

const [boardURL, keyFile, backupDirectory] = process.argv.slice(2);
if (!boardURL || !keyFile || !backupDirectory) throw new Error('Usage: node tools/verify_noty_sync.mjs BOARD_URL KEY_FILE BACKUP_DIRECTORY');
const baseline = JSON.parse(await readFile(resolve(backupDirectory, 'baseline.json'), 'utf8'));
const key = (await readFile(keyFile, 'utf8')).trim();
const cloudURL = 'https://noty-task-sync.vercel.app/api/sync';
const name = 'Noty sync check ' + randomUUID().slice(0, 8);
let fixtureID;

async function board(path = '/plan') {
  const response = await fetch(new URL(path, boardURL), {
    method: path.includes('?') ? 'POST' : 'GET', signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) throw new Error('Board request failed: ' + response.status);
  return response.json();
}

async function cloud(changes) {
  const response = await fetch(cloudURL, {
    method: changes ? 'POST' : 'GET',
    headers: { Authorization: 'Bearer ' + key, ...(changes ? { 'Content-Type': 'application/json' } : {}) },
    ...(changes ? { body: JSON.stringify({ changes }) } : {}), signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error('Cloud request failed: ' + response.status);
  const value = await response.json();
  if (value.conflicts.length) throw new Error('Verification fixture conflicted; original tasks were not modified');
  return value;
}

function assertPreserved(plan) {
  if (!isDeepStrictEqual(plan.projects, baseline.boardProjects)) throw new Error('Original board projects changed');
  for (const original of baseline.boardTasks) {
    if (!plan.tasks.some(task => task.t === original.t && task.done === original.done)) throw new Error('An original board task changed');
  }
  const changed = execFileSync('sqlite3', [resolve(backupDirectory, 'mac/notes.db'),
    "ATTACH DATABASE '/Users/evancheriyan/Library/Application Support/Noty/notes.db' AS current; SELECT COUNT(*) FROM (SELECT * FROM main.notes EXCEPT SELECT * FROM current.notes);"], { encoding: 'utf8' }).trim();
  if (changed !== '0') throw new Error('An original Mac note row changed');
}

async function until(label, test) {
  const deadline = Date.now() + 100_000;
  while (Date.now() < deadline) {
    try {
      const result = await test();
      if (result) { console.log('PASS ' + label); return result; }
    } catch (error) {
      // These callbacks only read state. The existing voice loop can delay
      // the board HTTP server; retry a read without repeating a mutation.
      if (!['TimeoutError', 'AbortError'].includes(error.name)) throw error;
    }
    await new Promise(resolve => setTimeout(resolve, 2_000));
  }
  throw new Error('Timed out: ' + label);
}

try {
  assertPreserved(await board());
  const add = await board('/plan?do=task_add&text=' + encodeURIComponent(name));
  if (!add.ok) throw new Error('Board refused the disposable task');
  const uploaded = await until('board task reaches live Noty service', async () => {
    const state = await cloud();
    return state.tasks.find(task => task.text === name && !task.deleted);
  });
  fixtureID = uploaded.id;
  await cloud([{ task: { ...uploaded, text: name + ' edited', completed: true }, base: uploaded }]);
  await until('cloud edit and completion reach the physical board', async () => {
    const plan = await board(); assertPreserved(plan);
    return plan.tasks.find(task => task.id === fixtureID && task.t === name + ' edited' && task.done === true);
  });
  const remove = await board('/plan?do=task_remove&id=' + encodeURIComponent(fixtureID));
  if (!remove.ok) throw new Error('Board refused fixture cleanup');
  await until('board deletion reaches the live service', async () => (await cloud()).tasks.find(task => task.id === fixtureID && task.deleted));
  const final = await board(); assertPreserved(final);
  const shared = await cloud();
  if (final.tasks.some(task => task.id === fixtureID)) throw new Error('Fixture remained on the board');
  const result = { boardTasks: final.tasks.length, projects: final.projects.length,
    originalBoardTasksPreserved: baseline.boardTasks.length, originalMacNotesChanged: 0,
    activeCloudTasks: shared.tasks.filter(task => !task.deleted).length, fixtureDeleted: true, sync: final.sync };
  await writeFile(resolve(backupDirectory, 'live-verification.json'), JSON.stringify(result, null, 2), { mode: 0o600 });
  console.log(JSON.stringify(result));
} catch (error) {
  // Remove only the fixture this script created, using its unique exact identity.
  try {
    const plan = await board();
    const local = plan.tasks.find(task => fixtureID ? task.id === fixtureID : task.t === name);
    if (local) await board('/plan?do=task_remove&' + (local.id ? 'id=' + encodeURIComponent(local.id) : 'text=' + encodeURIComponent(name)));
    if (fixtureID) {
      const current = (await cloud()).tasks.find(task => task.id === fixtureID);
      if (current && !current.deleted) await cloud([{ task: { ...current, deleted: true }, base: current }]);
    }
  } catch { console.error('Disposable fixture cleanup needs retry; original tasks were not targeted'); }
  throw error;
}
