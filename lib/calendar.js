// The owner's calendar from its private iCal (.ics) link: Google Calendar's "Secret address in iCal
// format", an iCloud shared-calendar link or an Outlook published calendar. Pasted on the board's
// remote page; the board sends it with X-Calendar. Never logged.
import ical from 'node-ical';

// The owner's time zone, for every day and clock time the gadget hears or shows. The board's own
// setting (board/room.py TZ) must match. 'Europe/London' / 'UK' when back home.
export const TZ = 'Asia/Kolkata';
export const TZ_PLACE = 'India';
const parts = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

// {day: 'YYYY-MM-DD', min: minutes since local midnight}
export function local(date) {
  const p = Object.fromEntries(parts.formatToParts(date).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, min: Number(p.hour) * 60 + Number(p.minute) };
}

const dayName = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short' });
// 'YYYY-MM-DD' as the board labels a day: "Fri 3 Oct".
export const label = (ymd) => dayName.format(new Date(`${ymd}T12:00:00Z`)).replace(',', '').replace('Sept', 'Sep');

const UPCOMING = 8;      // events after today the board lists, up to 30 days ahead

const text = (v) => String(v?.val ?? v ?? '').trim();

export function validUrl(u) {
  try {
    const url = new URL(String(u).trim().replace(/^webcal:/i, 'https:'));
    return url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
}

/**
 * Today's and tomorrow's events (local time, TZ), in order:
 * {today: [{s, e, t, all_day}], tomorrow: [...]}; s/e = minutes since midnight (e may pass 1440).
 * Plus `upcoming`: the next events starting after today, within 30 days:
 * [{day: "Tomorrow" | "Fri 3 Oct", date: 'YYYY-MM-DD', s, t, all_day}].
 */
export async function getCalendar(icsUrl, now = new Date()) {
  const url = validUrl(icsUrl);
  if (!url) throw new Error('not a calendar link');
  const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`calendar ${res.status}`);
  const data = ical.parseICS(await res.text());
  const today = local(now).day;
  const tomorrow = local(new Date(now.getTime() + 86400000)).day;
  const from = new Date(now.getTime() - 36 * 3600000), to = new Date(now.getTime() + 31 * 86400000);
  const last = local(new Date(now.getTime() + 30 * 86400000)).day;
  const out = { today: [], tomorrow: [], upcoming: [] };
  const ahead = (date, s, t, allDay) => {
    if (date > today && date <= last) {
      out.upcoming.push({ day: date === tomorrow ? 'Tomorrow' : label(date), date, s, t, ...(allDay && { all_day: true }) });
    }
  };
  for (const ev of Object.values(data)) {
    if (ev.type !== 'VEVENT' || text(ev.status).toUpperCase() === 'CANCELLED') continue;
    let instances;
    try {
      instances = ical.expandRecurringEvent(ev, { from, to, expandOngoing: true });
    } catch {
      continue;
    }
    for (const inst of instances) {
      const start = new Date(inst.start), end = new Date(inst.end || inst.start);
      if (inst.isFullDay) {
        // Date-only events: their calendar date(s), no times.
        // node-ical makes date-only values local midnight, so read them back in local time.
        const ymd = (x) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
        const d = ymd(start), e = ymd(new Date(Math.max(start.getTime(), end.getTime() - 1)));
        for (const [day, list] of [[today, out.today], [tomorrow, out.tomorrow]]) {
          if (d <= day && day <= e) list.push({ s: 0, e: 1440, t: text(inst.summary) || 'Busy', all_day: true });
        }
        ahead(d, 0, text(inst.summary) || 'Busy', true);
        continue;
      }
      const s = local(start), e = local(end);
      const span = Math.round((end - start) / 60000);
      for (const [day, list] of [[today, out.today], [tomorrow, out.tomorrow]]) {
        if (s.day === day) list.push({ s: s.min, e: s.min + span, t: text(inst.summary) || 'Busy' });
        else if (s.day < day && e.day >= day && e.min > 0) list.push({ s: 0, e: e.day === day ? e.min : 1440, t: text(inst.summary) || 'Busy' });
      }
      ahead(s.day, s.min, text(inst.summary) || 'Busy', false);
    }
  }
  for (const list of [out.today, out.tomorrow]) list.sort((a, b) => a.s - b.s);
  out.upcoming = soonest(out.upcoming);
  return out;
}

/**
 * Several calendars (X-Calendar: links separated by spaces) merged into one day plan. Calendars that
 * fail are counted in `failed`; it throws only if every one fails.
 */
export async function getCalendars(links, now = new Date()) {
  const urls = String(links || '').split(/\s+/).filter(Boolean).slice(0, 3);
  if (!urls.length) throw new Error('not a calendar link');
  const results = await Promise.allSettled(urls.map((u) => getCalendar(u, now)));
  const ok = results.filter((r) => r.status === 'fulfilled').map((r) => r.value);
  if (!ok.length) throw results[0].reason;
  const out = { today: ok.flatMap((c) => c.today), tomorrow: ok.flatMap((c) => c.tomorrow),
    upcoming: soonest(ok.flatMap((c) => c.upcoming)), failed: urls.length - ok.length };
  for (const list of [out.today, out.tomorrow]) list.sort((a, b) => a.s - b.s);
  return out;
}

// The first UPCOMING events by date, then time (all-day ones first on their day).
function soonest(list) {
  return list.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.s - b.s)).slice(0, UPCOMING);
}

// 12-hour, as the board shows and says times: "9:05am".
export const hhmm = (m) => {
  const h = Math.floor(m / 60) % 24;
  return `${(h + 11) % 12 + 1}:${String(m % 60).padStart(2, '0')}${h < 12 ? 'am' : 'pm'}`;
};

/** Plain-English day for the voice assistant. */
export function describe(cal) {
  const day = (list) => list.map((ev) => (ev.all_day ? `${ev.t} (all day)` : `${hhmm(ev.s)}-${hhmm(ev.e)} ${ev.t}`));
  return { today: day(cal.today), tomorrow: day(cal.tomorrow) };
}
