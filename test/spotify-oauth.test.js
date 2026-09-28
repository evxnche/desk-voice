import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import test from 'node:test';

import { GET as spotify } from '../api/spotify.js';
import { GET as spotifyCallback } from '../api/spotify-callback.js';

process.env.VOICE_KEY = 'test-voice-key';
process.env.SPOTIFY_CLIENT_ID = 'test-client';
process.env.SPOTIFY_CLIENT_SECRET = 'test-secret';

test('Spotify login signs state before the callback returns credentials to the board', async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => Response.json({ refresh_token: 'test-refresh-token' });

  const login = await spotify(new Request(
    'https://desk-voice.test/api/spotify?action=login&k=test-voice-key&board=192.168.1.99',
  ));
  const state = new URL(login.headers.get('location')).searchParams.get('state');

  assert.notEqual(state, '192.168.1.99');

  const callback = await spotifyCallback(new Request(
    `https://desk-voice.test/api/spotify-callback?code=test-code&state=${encodeURIComponent(state)}`,
  ));
  const destination = new URL(callback.headers.get('location'));

  assert.equal(callback.status, 302);
  assert.equal(destination.hostname, '192.168.1.99');
  assert.equal(destination.searchParams.get('refresh'), 'test-refresh-token');
  assert.equal(destination.searchParams.has('k'), false);
  assert.equal(
    destination.searchParams.get('sig'),
    createHmac('sha256', 'test-voice-key').update('test-refresh-token').digest('hex'),
  );
});

test('Spotify callback rejects unsigned state before exchanging the code', async (t) => {
  const originalFetch = globalThis.fetch;
  let exchanges = 0;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => {
    exchanges += 1;
    return Response.json({ refresh_token: 'attacker-refresh-token' });
  };

  const response = await spotifyCallback(new Request(
    'https://desk-voice.test/api/spotify-callback?code=attacker-code&state=192.168.1.99',
  ));

  assert.equal(response.status, 400);
  assert.equal(exchanges, 0);
});
