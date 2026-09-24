// Voice assistant for the ESP32-S3 RLCD desk board.
// POST raw 16-bit little-endian mono PCM at 15625 Hz, ?k=VOICE_KEY.
// Optional radar state from the board: &lat=..&lon=..&place=.. (custom centre) and &r=nm (range).
// Replies with one JSON line ({heard, reply[, radar]}) + "\n" + raw PCM in the same format.
// `radar` tells the board to move/zoom its radar screen: {lat, lon, place, r} or {home: true, r}.
import { generateSpeech, generateText, jsonSchema, stepCountIs, tool, transcribe } from 'ai';
import { gateway } from '@ai-sdk/gateway';
import { centreFrom, clampRadius, geocode, getFlights, KM_PER_NM } from '../lib/flights.js';
import { getWeather } from '../lib/weather.js';

const RATE = 15625;
// Claude models need paid AI Gateway credits; the free tier allows gpt-5-mini.
// After topping up, switch to 'anthropic/claude-haiku-4.5' (and drop providerOptions).
const CHAT_MODEL = 'openai/gpt-5-mini';
const MAX_BYTES = RATE * 2 * 15; // 15 s of audio

function toWav(samples, rate) {
  const data = Buffer.from(samples.buffer, samples.byteOffset, samples.byteLength);
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + data.length, 4); h.write('WAVE', 8);
  h.write('fmt ', 12); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22);
  h.writeUInt32LE(rate, 24); h.writeUInt32LE(rate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34);
  h.write('data', 36); h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}

// The board's mics are quiet; scale the recording so its peak sits near 80%.
function normalize(samples) {
  let peak = 1;
  for (const s of samples) peak = Math.max(peak, Math.abs(s));
  const gain = Math.min(30, (0.8 * 32767) / peak);
  return Int16Array.from(samples, (s) => Math.max(-32768, Math.min(32767, Math.round(s * gain))));
}

function parseWav(buf) {
  let rate = 24000, channels = 1, off = 12;
  while (off + 8 <= buf.length) {
    const id = buf.toString('ascii', off, off + 4);
    const size = buf.readUInt32LE(off + 4);
    if (id === 'fmt ') { channels = buf.readUInt16LE(off + 10); rate = buf.readUInt32LE(off + 12); }
    if (id === 'data') {
      const end = Math.min(buf.length, off + 8 + size);
      const all = new Int16Array(buf.buffer.slice(buf.byteOffset + off + 8, buf.byteOffset + end - ((end - off - 8) % 2)));
      const mono = channels === 1 ? all : Int16Array.from({ length: all.length / channels }, (_, i) => all[i * channels]);
      return { rate, samples: mono };
    }
    off += 8 + size + (size % 2);
  }
  throw new Error('no data chunk in TTS audio');
}

function resample(samples, from, to) {
  if (from === to) return samples;
  const out = new Int16Array(Math.floor((samples.length * to) / from));
  for (let i = 0; i < out.length; i++) {
    const pos = (i * from) / to, j = Math.floor(pos), f = pos - j;
    out[i] = Math.round(samples[j] * (1 - f) + (samples[j + 1] ?? samples[j]) * f);
  }
  return out;
}

async function limitsSummary() {
  if (!process.env.LIMITS_URL) return '';
  try {
    const res = await fetch(process.env.LIMITS_URL, { signal: AbortSignal.timeout(3000) });
    const data = await res.json();
    return (data.providers || [])
      .map((p) => `${p.name}: ` + p.windows.map((w) => `${w.label} ${w.used}% used, resets in ${w.resets}`).join('; '))
      .join('. ');
  } catch {
    return '';
  }
}

// Radar tools. `view` is this request's radar state; set_radar mutates it so a follow-up
// get_nearby_flights in the same answer looks at the new place.
function radarTools(view, changes) {
  return {
    get_nearby_flights: tool({
      description:
        "List the aircraft currently on the desk gadget's flight radar, nearest first. Entries 1-10 are the " +
        'numbered planes the owner sees on screen. Use for any question about planes nearby, overhead or on the radar.',
      inputSchema: jsonSchema({ type: 'object', properties: {}, additionalProperties: false }),
      execute: async () => {
        const data = await getFlights({ ...view, detailed: 10, full: true });
        return {
          centre: view.place || 'home',
          range_km: data.km,
          total_aircraft: data.aircraft.length,
          nearest: data.aircraft
            .filter((a) => a.who)
            .map((a, i) => ({
              number_on_screen: i + 1,
              operator: a.who, flight: a.flight, kind: a.kind, aircraft: a.model,
              route: a.from ? `${a.from} to ${a.to}` : 'unknown',
              altitude_ft: a.alt, km_away: a.km, direction_from_centre: a.dir,
              heading_deg: a.track, speed_kmh: Math.round(a.speed * KM_PER_NM),
              climbing_or_descending: a.trend || 'level',
            })),
        };
      },
    }),
    get_weather: tool({
      description:
        "Current weather plus today's and tomorrow's forecast. Leave `place` empty for the owner's own location " +
        '(what the gadget shows); give a city or place name for anywhere else.',
      inputSchema: jsonSchema({
        type: 'object',
        properties: { place: { type: 'string' } },
        additionalProperties: false,
      }),
      execute: async ({ place }) => {
        const where = place ? await geocode(place) : { ...view.home, name: view.home.place };
        if (!where) return { ok: false, error: `couldn't find "${place}"` };
        return { place: where.name || 'home', ...(await getWeather(where.lat, where.lon)) };
      },
    }),
    set_radar: tool({
      description:
        'Move and/or zoom the flight radar screen. Give `place` to centre it somewhere (a city, airport or landmark; ' +
        "include the country if ambiguous), `home: true` to go back to the owner's own location, and/or " +
        '`range_km` (8-185) to zoom. The board switches to the radar screen afterwards.',
      inputSchema: jsonSchema({
        type: 'object',
        properties: {
          place: { type: 'string' },
          home: { type: 'boolean' },
          range_km: { type: 'number' },
        },
        additionalProperties: false,
      }),
      execute: async ({ place, home, range_km }) => {
        if (range_km) view.radius = clampRadius(range_km / KM_PER_NM);
        if (home) {
          Object.assign(view, view.home);
          changes.home = true;
        } else if (place) {
          const hit = await geocode(place);
          if (!hit) return { ok: false, error: `couldn't find "${place}"` };
          Object.assign(view, { lat: hit.lat, lon: hit.lon, place: hit.name });
          changes.home = false;
        }
        changes.set = true;
        return { ok: true, centre: view.place || 'home', range_km: Math.round(view.radius * KM_PER_NM) };
      },
    }),
  };
}

function reply(heard, text, pcm = new Int16Array(0), radar = null) {
  const head = Buffer.from(JSON.stringify({ heard, reply: text, ...(radar && { radar }) }) + '\n');
  const body = Buffer.concat([head, Buffer.from(pcm.buffer, pcm.byteOffset, pcm.byteLength)]);
  // An explicit length avoids chunked encoding, which MicroPython decodes at ~13 KB/s.
  return new Response(body, {
    headers: { 'Content-Type': 'application/octet-stream', 'Content-Length': String(body.length) },
  });
}

async function speak(text) {
  const speech = await generateSpeech({
    model: gateway.speechModel('openai/tts-1'),
    text,
    voice: 'alloy',
    outputFormat: 'wav',
  });
  const { rate, samples } = parseWav(Buffer.from(speech.audio.uint8Array));
  return resample(samples, rate, RATE);
}

const NEWSY = /\b(latest|news|headlines?|updates?|today|tonight|yesterday|this (week|month|year)|current(ly)?|recent(ly)?|right now|happening|war|election|president|prime minister|score|won|stock|price|release[ds]?)\b/i;
const OWN_TOOLS = /\b(weather|temperature|rain|forecast|sunny|wind|flights?|planes?|aircraft|radar|zoom|limits?)\b/i;

function needsSearch(question) {
  return NEWSY.test(question) && !OWN_TOOLS.test(question);
}

export async function POST(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  const body = Buffer.from(await request.arrayBuffer());
  if (body.length < RATE || body.length > MAX_BYTES) {
    return new Response('audio must be 0.5-15 s', { status: 400 });
  }
  const pcm = normalize(new Int16Array(body.buffer.slice(body.byteOffset, body.byteOffset + body.length - (body.length % 2))));

  const [{ text: heard }, limits] = await Promise.all([
    // Silence or mumbling makes the SDK throw NoTranscriptGeneratedError; treat it as "didn't catch that".
    transcribe({ model: gateway.transcriptionModel('openai/gpt-4o-mini-transcribe'), audio: toWav(pcm, RATE) })
      .catch(() => ({ text: '' })),
    limitsSummary(),
  ]);
  if (!heard.trim()) {
    const text = "Sorry, I didn't catch that.";
    return reply('', text, await speak(text));
  }

  const now = new Date().toLocaleString('en-GB', { timeZone: 'Europe/London', dateStyle: 'full', timeStyle: 'short' });
  const centre = centreFrom(url, request.headers);
  const ipHome = centreFrom(new URL('http://x/'), request.headers);
  const view = {
    lat: centre.lat, lon: centre.lon, place: centre.place,
    radius: clampRadius(url.searchParams.get('r')),
    home: { lat: ipHome.lat, lon: ipHome.lon, place: ipHome.place },
  };
  const changes = {};
  let text;
  try {
    ({ text } = await generateText({
      model: CHAT_MODEL,
      providerOptions: { openai: { reasoningEffort: 'minimal' } },
      system:
        'You are a friendly voice assistant living in a small desk gadget with a black-and-white screen. ' +
        'Your reply is spoken aloud and shown on a tiny screen, so answer in one to three short sentences of plain speech: ' +
        'no markdown, lists, emoji or URLs. This is a one-shot voice gadget: never ask the owner a follow-up or ' +
        'clarifying question, just give your best answer. Never say you are unaware of an event without searching first. ' +
        'Use get_weather for any weather question. Use metric units: km, km/h and Celsius (plane altitudes stay in feet). ' +
      'Use web_search for news, current events, prices, sports, or anything else that may have changed recently; ' +
        'otherwise answer from what you know. ' +
        'The gadget also has a flight radar screen, currently centred on ' +
        `${view.place || 'home'} with a ${Math.round(view.radius * KM_PER_NM)} km range. ` +
        'Use get_nearby_flights for questions about planes nearby, overhead or on the radar (planes 1 to 10 are numbered on screen). ' +
        'Use set_radar when asked to show, move or zoom the radar or to look at flights somewhere, then just confirm it in one ' +
        "short sentence; don't list the flights unless asked. " +
        `It is ${now} in London.` +
        (limits ? ` The owner's AI coding agent usage limits right now: ${limits}.` : ''),
      prompt: heard,
      tools: {
        web_search: gateway.tools.perplexitySearch({ maxResults: 5, maxTokensPerPage: 512 }),
        ...radarTools(view, changes),
      },
      // The free-tier model sometimes skips searching for news and answers from stale memory, so
      // news-shaped questions must use a tool on the first step (web_search is the only one that fits).
      // Naming web_search directly fails: the gateway maps it to OpenAI's 'web_search_preview'.
      prepareStep: ({ stepNumber }) => (stepNumber === 0 && needsSearch(heard) ? { toolChoice: 'required' } : {}),
      stopWhen: stepCountIs(4),
      maxOutputTokens: 400,
    }));
  } catch (e) {
    // The free tier allows ~5 model calls a minute, and a tool-using answer takes 2-3 of them.
    const limited = /rate limit/i.test(String(e?.message)) || e?.lastError?.statusCode === 429;
    text = limited
      ? "I've hit the free tier's limit of a few questions a minute. Try again in a minute."
      : 'Sorry, something went wrong answering that.';
    console.error(e);
  }
  // A zoom alone keeps whatever centre the board had: automatic (home) or a named place.
  const atHome = changes.home ?? !centre.custom;
  const radar = !changes.set ? null
    : atHome ? { home: true, r: view.radius }
    : { lat: view.lat, lon: view.lon, place: view.place, r: view.radius };
  return reply(heard, text, await speak(text), radar);
}
