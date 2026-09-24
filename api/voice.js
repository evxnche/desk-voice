// Voice assistant for the ESP32-S3 RLCD desk board.
// POST raw 16-bit little-endian mono PCM at 15625 Hz, ?k=VOICE_KEY.
// Replies with one JSON line ({heard, reply}) + "\n" + raw PCM in the same format.
import { generateSpeech, generateText, stepCountIs, transcribe } from 'ai';
import { gateway } from '@ai-sdk/gateway';

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

function reply(heard, text, pcm = new Int16Array(0)) {
  const head = Buffer.from(JSON.stringify({ heard, reply: text }) + '\n');
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
    transcribe({ model: gateway.transcriptionModel('openai/gpt-4o-mini-transcribe'), audio: toWav(pcm, RATE) }),
    limitsSummary(),
  ]);
  if (!heard.trim()) {
    const text = "Sorry, I didn't catch that.";
    return reply('', text, await speak(text));
  }

  const now = new Date().toLocaleString('en-GB', { timeZone: 'Europe/London', dateStyle: 'full', timeStyle: 'short' });
  const { text } = await generateText({
    model: CHAT_MODEL,
    providerOptions: { openai: { reasoningEffort: 'minimal' } },
    system:
      'You are a friendly voice assistant living in a small desk gadget with a black-and-white screen. ' +
      'Your reply is spoken aloud and shown on a tiny screen, so answer in one to three short sentences of plain speech: ' +
      'no markdown, lists, emoji or URLs. ' +
      'Use web_search for news, current events, prices, weather, sports, or anything that may have changed recently; ' +
      'otherwise answer from what you know. ' +
      `It is ${now} in London.` +
      (limits ? ` The owner's AI coding agent usage limits right now: ${limits}.` : ''),
    prompt: heard,
    tools: { web_search: gateway.tools.perplexitySearch({ maxResults: 5, maxTokensPerPage: 512 }) },
    stopWhen: stepCountIs(3),
    maxOutputTokens: 400,
  });
  return reply(heard, text, await speak(text));
}
