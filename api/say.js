// The Pal speaking up on its own (board/companion.py): POST the words as the body, ?k=VOICE_KEY,
// and get back the same format as /api/voice: one JSON line ({reply[, audio: 'adpcm']}) + "\n" +
// the words in the assistant's voice (4-bit ADPCM with X-Audio: adpcm, else 16-bit PCM, 15625 Hz).
import { reply, speak } from './voice.js';

export async function POST(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  const text = (await request.text()).trim().slice(0, 400);
  if (!text) return new Response('nothing to say', { status: 400 });
  return reply('', text, await speak(text), request.headers.get('x-audio') === 'adpcm');
}
