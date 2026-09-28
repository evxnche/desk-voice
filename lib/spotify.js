// Spotify Web API helpers. The board keeps the user's refresh token and sends it with each request
// (X-Spotify-Refresh), so this service stores nothing. Needs SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET.
import { createHmac, timingSafeEqual } from 'node:crypto';

export const REDIRECT_URI = 'https://desk-voice.vercel.app/api/spotify-callback';
export const SCOPES = 'user-read-playback-state user-modify-playback-state user-read-currently-playing';

const LOGIN_STATE_TTL_MS = 15 * 60 * 1000;

function boardHost(value) {
  const parts = String(value || '').split('.').map(Number);
  const ipv4 = parts.length === 4 && parts.every((part) => Number.isInteger(part) && part >= 0 && part <= 255);
  if (ipv4 && (parts[0] === 10 || (parts[0] === 192 && parts[1] === 168)
    || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31))) return parts.join('.');
  return 'deskpal.local';
}

function stateSignature(payload) {
  return createHmac('sha256', process.env.VOICE_KEY).update(payload).digest();
}

export function createSpotifyLoginState(board) {
  const payload = Buffer.from(JSON.stringify({
    host: boardHost(board),
    expires: Date.now() + LOGIN_STATE_TTL_MS,
  })).toString('base64url');
  return `${payload}.${stateSignature(payload).toString('base64url')}`;
}

export function verifySpotifyLoginState(state) {
  try {
    const parts = String(state || '').split('.');
    if (parts.length !== 2) return null;
    const [payload, encodedSignature] = parts;
    const signature = Buffer.from(encodedSignature, 'base64url');
    const expected = stateSignature(payload);
    if (signature.length !== expected.length || !timingSafeEqual(signature, expected)) return null;
    const data = JSON.parse(Buffer.from(payload, 'base64url').toString());
    if (!Number.isFinite(data.expires) || data.expires < Date.now()) return null;
    return boardHost(data.host);
  } catch {
    return null;
  }
}

export function createSpotifyHandoffSignature(refreshToken) {
  return createHmac('sha256', process.env.VOICE_KEY).update(refreshToken).digest('hex');
}

const accessCache = new Map(); // refresh token -> { token, expires } (warm instances reuse it)

function basicAuth() {
  return 'Basic ' + Buffer.from(`${process.env.SPOTIFY_CLIENT_ID}:${process.env.SPOTIFY_CLIENT_SECRET}`).toString('base64');
}

export function configured() {
  return Boolean(process.env.SPOTIFY_CLIENT_ID && process.env.SPOTIFY_CLIENT_SECRET);
}

async function tokenRequest(params) {
  const res = await fetch('https://accounts.spotify.com/api/token', {
    method: 'POST',
    headers: { Authorization: basicAuth(), 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(params),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(`spotify token: ${data.error_description || data.error || res.status}`);
  return data;
}

export function exchangeCode(code) {
  return tokenRequest({ grant_type: 'authorization_code', code, redirect_uri: REDIRECT_URI });
}

async function accessToken(refresh) {
  const hit = accessCache.get(refresh);
  if (hit && hit.expires > Date.now() + 30_000) return hit.token;
  const data = await tokenRequest({ grant_type: 'refresh_token', refresh_token: refresh });
  accessCache.set(refresh, { token: data.access_token, expires: Date.now() + data.expires_in * 1000 });
  return data.access_token;
}

async function api(refresh, method, path, body) {
  const res = await fetch(`https://api.spotify.com/v1${path}`, {
    method,
    headers: { Authorization: `Bearer ${await accessToken(refresh)}`, ...(body && { 'Content-Type': 'application/json' }) },
    body: body && JSON.stringify(body),
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const reason = data?.error?.reason || data?.error?.message || res.status;
    throw new Error(reason === 'PREMIUM_REQUIRED' ? 'playback control needs Spotify Premium' : `spotify: ${reason}`);
  }
  return data;
}

/** Compact now-playing state for the board. */
export async function nowPlaying(refresh) {
  const p = await api(refresh, 'GET', '/me/player?additional_types=track,episode');
  const item = p?.item;
  if (!item) return { playing: false, title: '', device: p?.device?.name || '' };
  return {
    playing: Boolean(p.is_playing),
    title: item.name,
    artist: item.artists?.map((a) => a.name).join(', ') || item.show?.name || '',
    album: item.album?.name || '',
    progress_ms: p.progress_ms ?? 0,
    duration_ms: item.duration_ms ?? 0,
    device: p.device?.name || '',
    // ~300 px cover (Spotify lists 640/300/64); the board fetches its dithered version when this changes.
    art_url: (item.album?.images || item.images || []).find((i) => i.width && i.width <= 320)?.url
      || (item.album?.images || item.images || [])[0]?.url || '',
  };
}

// Play/transfer needs a device; if nothing is active, use the first one Spotify knows about.
async function deviceQuery(refresh) {
  const { devices = [] } = (await api(refresh, 'GET', '/me/player/devices')) || {};
  const d = devices.find((x) => x.is_active) || devices[0];
  if (!d) throw new Error('no Spotify device is open - start Spotify on your phone or Mac first');
  return d.is_active ? '' : `?device_id=${d.id}`;
}

/** play | pause | toggle | next | previous */
export async function control(refresh, what) {
  if (what === 'toggle') {
    const p = await api(refresh, 'GET', '/me/player');
    what = p?.is_playing ? 'pause' : 'play';
  }
  if (what === 'pause') await api(refresh, 'PUT', '/me/player/pause');
  else if (what === 'play') await api(refresh, 'PUT', `/me/player/play${await deviceQuery(refresh)}`);
  else if (what === 'next') await api(refresh, 'POST', '/me/player/next');
  else if (what === 'previous') await api(refresh, 'POST', '/me/player/previous');
  else throw new Error(`unknown control "${what}"`);
  await new Promise((r) => setTimeout(r, 400)); // let Spotify catch up before reporting state
  return nowPlaying(refresh);
}

/** Search and start playing: kind is playlist (moods like "something chill"), track, album or artist. */
export async function playSearch(refresh, query, kind = 'playlist') {
  const type = ['playlist', 'track', 'album', 'artist'].includes(kind) ? kind : 'playlist';
  const found = await api(refresh, 'GET', `/search?${new URLSearchParams({ q: query, type, limit: '5' })}`);
  const item = (found?.[`${type}s`]?.items || []).find(Boolean);
  if (!item) throw new Error(`nothing on Spotify for "${query}"`);
  const body = type === 'track' ? { uris: [item.uri] } : { context_uri: item.uri };
  await api(refresh, 'PUT', `/me/player/play${await deviceQuery(refresh)}`, body);
  return { playing: item.name, by: item.owner?.display_name || item.artists?.map((a) => a.name).join(', ') || '' };
}
