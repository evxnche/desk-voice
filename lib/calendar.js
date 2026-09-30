// The owner's calendar from its private iCal (.ics) link: Google Calendar's "Secret address in iCal
// format", an iCloud shared-calendar link or an Outlook published calendar. Pasted on the board's
// remote page; the board sends it with X-Calendar. Never logged.
import ical from 'node-ical';

const TZ = 'Europe/London';
const parts = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

// {day: 'YYYY-MM-DD', min: minutes since London midnight}
function london(date) {
  const p = Object.fromEntries(parts.formatToParts(date).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, min: Number(p.hour) * 60 + Number(p.minute) };
}

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
 * Today's and tomorrow's events (London time), in order:
 * {today: [{s, e, t, all_day}], tomorrow: [...]}; s/e = minutes since midnight (e may pass 1440).
 */
export async function getCalendar(icsUrl, now = new Date()) {
  const url = validUrl(icsUrl);
  if (!url) throw new Error('not a calendar link');
  const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
  if (!res.ok) throw new Error(`calendar ${res.status}`);
  const data = ical.parseICS(await res.text());
  const today = london(now).day;
  const tomorrow = london(new Date(now.getTime() + 86400000)).day;
  const from = new Date(now.getTime() - 36 * 3600000), to = new Date(now.getTime() + 60 * 3600000);
  const out = { today: [], tomorrow: [] };
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
        continue;
      }
      const s = london(start), e = london(end);
      const span = Math.round((end - start) / 60000);
      for (const [day, list] of [[today, out.today], [tomorrow, out.tomorrow]]) {
        if (s.day === day) list.push({ s: s.min, e: s.min + span, t: text(inst.summary) || 'Busy' });
        else if (s.day < day && e.day >= day && e.min > 0) list.push({ s: 0, e: e.day === day ? e.min : 1440, t: text(inst.summary) || 'Busy' });
      }
    }
  }
  for (const list of [out.today, out.tomorrow]) list.sort((a, b) => a.s - b.s);
  return out;
}

// 12-hour, as the board shows and says times: "9:05am".
const hhmm = (m) => {
  const h = Math.floor(m / 60) % 24;
  return `${(h + 11) % 12 + 1}:${String(m % 60).padStart(2, '0')}${h < 12 ? 'am' : 'pm'}`;
};

/** Plain-English day for the voice assistant. */
export function describe(cal) {
  const day = (list) => list.map((ev) => (ev.all_day ? `${ev.t} (all day)` : `${hhmm(ev.s)}-${hhmm(ev.e)} ${ev.t}`));
  return { today: day(cal.today), tomorrow: day(cal.tomorrow) };
}
