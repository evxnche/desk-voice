// Spotify sends the browser here after sign-in. The refresh token is handed straight to the board on
// the home Wi-Fi (top-level navigation to http://deskpal.local is allowed from an https page), so this
// service never stores it.
import { createSpotifyHandoffSignature, exchangeCode, verifySpotifyLoginState } from '../lib/spotify.js';

export async function GET(request) {
  const url = new URL(request.url);
  const code = url.searchParams.get('code');
  if (!code) return new Response(`Spotify sign-in failed: ${url.searchParams.get('error') || 'no code'}`, { status: 400 });
  const host = verifySpotifyLoginState(url.searchParams.get('state'));
  if (!host) return new Response('Spotify sign-in failed: invalid or expired login state', { status: 400 });
  try {
    const { refresh_token } = await exchangeCode(code);
    const q = new URLSearchParams({ refresh: refresh_token, sig: createSpotifyHandoffSignature(refresh_token) });
    // Send the token only to the signed private-LAN destination. The signature lets the board verify
    // that the handoff came from this service without putting its long-lived VOICE_KEY in the URL.
    return Response.redirect(`http://${host}/spotify-token?${q}`, 302);
  } catch (e) {
    return new Response(`Spotify sign-in failed: ${e.message}`, { status: 502 });
  }
}
