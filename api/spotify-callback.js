// Spotify sends the browser here after sign-in. The refresh token is handed straight to the board on
// the home Wi-Fi (top-level navigation to http://deskpal.local is allowed from an https page), so this
// service never stores it.
import { exchangeCode } from '../lib/spotify.js';

export async function GET(request) {
  const url = new URL(request.url);
  const code = url.searchParams.get('code');
  if (!code) return new Response(`Spotify sign-in failed: ${url.searchParams.get('error') || 'no code'}`, { status: 400 });
  try {
    const { refresh_token } = await exchangeCode(code);
    const q = new URLSearchParams({ k: process.env.VOICE_KEY, refresh: refresh_token });
    return Response.redirect(`http://deskpal.local/spotify-token?${q}`, 302);
  } catch (e) {
    return new Response(`Spotify sign-in failed: ${e.message}`, { status: 502 });
  }
}
