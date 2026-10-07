// The plan screen for the Xteink reader (ezOS): the Desk Pal note's tasks and project pipeline, and
// the calendar, as ready-made screens. The reader only draws rows, so what goes on each screen can
// change here without reflashing it. Note parsing follows board/noty_notes.py (_rows, project).
import { getCalendars, hhmm, label, local } from './calendar.js';

const STAGES = ['idea', 'building', 'testing', 'shipped'];
const MAX_ROWS = 80;      // per screen; the reader pages them
const MAX_TEXT = 200;

function heading(text) {
  let count = 0;
  while (count < text.length && text[count] === '#') count++;
  if (count < 1 || count > 6 || (count < text.length && !/\s/.test(text[count]))) return null;
  return { level: count, title: text.slice(count).trim().replace(/#+$/, '').trim().toLowerCase() };
}

/** Items under the "# to-do" and "# idea/building/testing/shipped" headings: [{section, text, done}]. */
export function noteRows(body) {
  const rows = [];
  let section = null, fence = null;
  for (const raw of String(body || '').split('\n')) {
    let text = raw.trim();
    if (text.startsWith('```') || text.startsWith('~~~')) {
      const marker = text.slice(0, 3);
      if (fence === null) fence = marker;
      else if (fence === marker) fence = null;
      continue;
    }
    if (fence) continue;
    const header = heading(text);
    if (header) {
      section = null;
      if (header.level === 1) {
        const t = header.title;
        section = ['todo', 'to-do', 'to do'].includes(t) ? 'todo' : t === 'shift' ? 'shipped' : t;
      }
      continue;
    }
    if (!text || !['todo', ...STAGES].includes(section)) continue;
    if (text.length > 1 && '-*+'.includes(text[0]) && /\s/.test(text[1])) text = text.slice(1).trimStart();
    let done = false;
    if (text.startsWith('☐') || text.startsWith('☑')) {
      done = text[0] === '☑';
      text = text.slice(1).trim();
    } else if (/^\[[ xX]\](\s|$)/.test(text)) {
      done = text[1].toLowerCase() === 'x';
      text = text.slice(3).trim();
    }
    if (text) rows.push({ section, text, done });
  }
  return rows;
}

/** The Desk Pal note; if its id is gone, the live note titled "Desk Pal" (as the board does). */
export function deskPalNote(snapshot) {
  const notes = snapshot?.notes || [];
  const id = String(snapshot?.deskPalId || '').toLowerCase();
  return notes.find((n) => id && n.id.toLowerCase() === id)
    || notes.find((n) => !n.archived && n.title.trim().toLowerCase() === 'desk pal') || null;
}

const row = (k, t, extra = {}) => ({ k, t: String(t).slice(0, MAX_TEXT), ...extra });
const cap = (rows) => (rows.length > MAX_ROWS ? [...rows.slice(0, MAX_ROWS - 1), row('note', `+${rows.length - MAX_ROWS + 1} more`)] : rows);

export function taskScreen(items) {
  const todo = items.filter((i) => i.section === 'todo' && !i.done);
  const done = items.filter((i) => i.section === 'todo' && i.done);
  const rows = [row('head', `To do (${todo.length})`), ...todo.map((i) => row('task', i.text))];
  if (!todo.length) rows.push(row('note', 'Nothing to do'));
  if (done.length) rows.push(row('head', `Done (${done.length})`), ...done.map((i) => row('task', i.text, { done: true })));
  return { title: 'Tasks', rows: cap(rows) };
}

export function projectScreen(items) {
  const rows = [];
  for (const stage of STAGES) {
    const names = items.filter((i) => i.section === stage).map((i) => i.text);
    if (names.length) rows.push(row('head', `${stage[0].toUpperCase()}${stage.slice(1)} (${names.length})`), ...names.map((n) => row('item', n)));
  }
  return { title: 'Projects', rows: cap(rows.length ? rows : [row('note', 'No projects yet')]) };
}

const when = (ev) => (ev.all_day ? 'all day' : hhmm(ev.s));

/** What's left of today (or "No events today"), then the next events, under their day (local time). */
export function calendarScreen(cal, now = new Date()) {
  const here = local(now);
  const rows = [row('head', `Today, ${label(here.day)}`)];
  const left = cal.today.filter((ev) => ev.all_day || ev.e > here.min);
  rows.push(...left.map((ev) => row('event', ev.t, { time: when(ev) })));
  if (!left.length) rows.push(row('note', 'No events today'));
  let day = null;
  for (const ev of cal.upcoming) {
    if (ev.day !== day) rows.push(row('head', (day = ev.day)));
    rows.push(row('event', ev.t, { time: when(ev) }));
  }
  if (cal.failed) rows.push(row('note', `${cal.failed} calendar(s) could not be read`));
  return { title: 'Calendar', rows: cap(rows) };
}

/** {screens: [Tasks, Projects, Calendar]}; a part that fails shows why on its own screen. */
export async function buildPlan(snapshot, calendarLinks, now = new Date()) {
  let items = null, noteError = '';
  if (!snapshot?.ok) noteError = snapshot?.error || 'Noty notes are unavailable.';
  else {
    const note = deskPalNote(snapshot);
    if (note) items = noteRows(note.body);
    else noteError = 'No note titled "Desk Pal" in Noty.';
  }
  const failed = (title) => ({ title, rows: [row('note', noteError)] });

  let calendar;
  if (!String(calendarLinks || '').trim()) {
    calendar = { title: 'Calendar', rows: [row('note', 'No calendars connected (PLAN_CALENDARS on desk-voice).')] };
  } else {
    try {
      calendar = calendarScreen(await getCalendars(calendarLinks, now), now);
    } catch {
      calendar = { title: 'Calendar', rows: [row('note', 'Calendar could not be read.')] };
    }
  }
  return { screens: [items ? taskScreen(items) : failed('Tasks'), items ? projectScreen(items) : failed('Projects'), calendar] };
}
