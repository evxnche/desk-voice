// Spotify for the desk board.
//   GET  ?action=login&k=KEY      -> Spotify sign-in (open from the board's remote page)
//   GET  ?action=now&k=KEY        -> now playing        (header X-Spotify-Refresh)
//   POST ?action=control&do=X&k=  -> play/pause/toggle/next/previous, returns now playing
//   GET  ?action=art&url=U&k=      -> album cover as a 1-bit 150x150 bitmap (MONO_HLSB, 2812 bytes)
import { configured, control, nowPlaying, REDIRECT_URI, SCOPES } from '../lib/spotify.js';
import { ditheredCover } from '../lib/art.js';

function json(data, status = 200) {
  const body = Buffer.from(JSON.stringify(data));
  return new Response(body, { status, headers: { 'Content-Type': 'application/json', 'Content-Length': String(body.length) } });
}

async function handle(request) {
  const url = new URL(request.url);
  if (!process.env.VOICE_KEY || url.searchParams.get('k') !== process.env.VOICE_KEY) {
    return new Response('unauthorized', { status: 401 });
  }
  if (url.searchParams.get('action') === 'art') {
    try {
      const size = Math.min(200, Math.max(32, Number(url.searchParams.get('size')) || 150)) & ~7;
      const bits = await ditheredCover(url.searchParams.get('url') || '', size);
      return new Response(bits, { headers: { 'Content-Type': 'application/octet-stream', 'Content-Length': String(bits.length), 'Cache-Control': 'public, max-age=86400' } });
    } catch (e) {
      return new Response(e.message, { status: 400 });
    }
  }
  if (!configured()) return json({ error: 'Spotify app not set up on the server yet' }, 503);
  const action = url.searchParams.get('action');

  if (action === 'login') {
    // `board` is the board's LAN address; it rides through Spotify as `state` so the callback can hand
    // the token straight back to it without relying on the deskpal.local name.
    const board = url.searchParams.get('board') || '';
    const q = new URLSearchParams({ client_id: process.env.SPOTIFY_CLIENT_ID, response_type: 'code', redirect_uri: REDIRECT_URI, scope: SCOPES, state: board });
    return Response.redirect(`https://accounts.spotify.com/authorize?${q}`, 302);
  }

  const refresh = request.headers.get('x-spotify-refresh');
  if (!refresh) return json({ error: 'not signed in to Spotify' }, 401);
  try {
    if (action === 'now') return json(await nowPlaying(refresh));
    if (action === 'control') return json(await control(refresh, url.searchParams.get('do') || 'toggle'));
  } catch (e) {
    return json({ error: e.message }, 200); // the board shows the message on screen
  }
  return json({ error: 'unknown action' }, 400);
}

export const GET = handle;
export const POST = handle;
