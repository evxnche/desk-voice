import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getCalendar, validUrl } from '../lib/calendar.js';

const ICS = `BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTIMEZONE
TZID:Europe/London
BEGIN:DAYLIGHT
TZOFFSETFROM:+0000
TZOFFSETTO:+0100
TZNAME:BST
DTSTART:19700329T010000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0100
TZOFFSETTO:+0000
TZNAME:GMT
DTSTART:19701025T020000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:weekly
SUMMARY:Team sync
DTSTART;TZID=Europe/London:20260907T140000
DTEND;TZID=Europe/London:20260907T143000
RRULE:FREQ=WEEKLY;BYDAY=MO
EXDATE;TZID=Europe/London:20260921T140000
END:VEVENT
BEGIN:VEVENT
UID:oneoff
SUMMARY:Dentist
DTSTART:20260928T163000Z
DTEND:20260928T171500Z
END:VEVENT
BEGIN:VEVENT
UID:cancelled
SUMMARY:Old thing
STATUS:CANCELLED
DTSTART:20260928T120000Z
DTEND:20260928T130000Z
END:VEVENT
BEGIN:VEVENT
UID:allday
SUMMARY:Cousins visiting
DTSTART;VALUE=DATE:20260929
DTEND;VALUE=DATE:20260930
END:VEVENT
END:VCALENDAR
`;

test('today and tomorrow in London time, recurring, cancelled and all-day handled', async () => {
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(ICS);
  try {
    const cal = await getCalendar('webcal://example.com/basic.ics', new Date('2026-09-28T09:00:00Z'));
    assert.deepEqual(cal.today, [
      { s: 14 * 60, e: 14 * 60 + 30, t: 'Team sync' },
      { s: 17 * 60 + 30, e: 18 * 60 + 15, t: 'Dentist' },
    ]);
    assert.deepEqual(cal.tomorrow, [{ s: 0, e: 1440, t: 'Cousins visiting', all_day: true }]);
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('only https (or webcal) links', () => {
  assert.equal(validUrl('http://x.com/a.ics'), '');
  assert.equal(validUrl('nonsense'), '');
  assert.equal(validUrl('webcal://p01.icloud.com/x'), 'https://p01.icloud.com/x');
});
