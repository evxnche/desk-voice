# desk-voice

Firmware + backend for a Waveshare ESP32-S3-RLCD-4.2 desk gadget (MicroPython v1.29).

Running your own copy for the Ray-Ban Meta glasses app (ezmeta)? See [Deploy your own](#deploy-your-own-glasses-server).

- `board/` — MicroPython app. Screens (BOOT cycles): the Pal (Claude's pixel crab, the start screen: `pal.py`; reacts when it hears talking, asleep 22:00-08:00, and is the assistant's face while it listens, thinks and speaks), agent usage limits, room (time + temp/humidity), Pixel Pal game, flight radar (`api/flights.js` -> adsb.lol). KEY tap refreshes limits; KEY hold = talk to the assistant. After an answer it listens 6 s for a reply without the wake phrase and remembers the last 6 exchanges for 10 minutes (RAM only). "Let's practice Spanish" turns it into a beginner Spanish tutor (no other features, 15 s to reply) until "stop practicing" or 10 quiet minutes. `companion.py` speaks up on its own via `/api/say` (handled in `api/voice.js`; the Hobby plan allows 12 functions): Claude/Codex needs you, a limit passes 90%, rain within the hour, a morning hello.
- `api/voice.js` — Vercel function: 15625 Hz mono PCM in -> transcribe (spacexai/grok-stt; `STT_MODEL` env overrides it) -> openai/gpt-oss-120b (fastest free-tier model; `CHAT_MODEL` env overrides it) -> TTS (spacexai/grok-tts, voice Ara; `TTS_MODEL` / `TTS_VOICE` env override them) -> PCM out, all via AI Gateway (OIDC). With `X-Audio: adpcm` (the board sends it) audio goes both ways as 4-bit IMA ADPCM, a quarter of the bytes (`lib/adpcm.js`, `board/adpcm.py`).
- `api/glasses.js` — Desk Pal on Ray-Ban Meta glasses, for the ezmeta iPhone app: 16 kHz PCM in -> the same transcriber, model and voice, with web search, weather, Noty notes (read; "note: ..." appends to an **Inbox** note, "add X to my tasks" adds a ☐ row to the Desk Pal note via Noty's task API), recent agent events and limits -> JSON line + 24 kHz WAV. "Read my articles" tells the app to start ezRead. "Dictation mode" returns `{dictate: true}`; while the app sends `X-Dictate: 1`, each recording is only transcribed and comes back as `{type}` (no audio) for the app to type through `mac/deskpal-mac.py`, until "stop dictation". It is also `/api/agent` (a rewrite): the agent pager mailbox that `mac/deskpal-notify.py` posts to and the app polls (Upstash, `KV_REST_API_URL` / `KV_REST_API_TOKEN`, newest 20 for a day).
- `api/plan.js` — the plan for the Xteink reader (ezOS firmware): GET `?k=PLAN_KEY` returns Tasks, Projects and Calendar screens as typed rows (`lib/plan.js`), from the Desk Pal note (same parsing as `board/noty_notes.py`) and the private iCal links in the `PLAN_CALENDARS` env var (space-separated).

`board/rlcd.py` is adapted from micheleaiello/ESP32-S3-4.2inch-RLCD-Driver (GPL-3.0); `show()` was rewritten in viper (~36 ms/frame).

Fonts: `board/font_*.bin` are 1-bit bitmaps of MS Gothic (small), Departure Mono (text) and ABC Areal Mono Bold (headings), made by `python3 tools/make_fonts.py` from the TTFs in ~/Library/Fonts; `board/bitfont.py` draws them.

Mac control (`mac/deskpal-mac.py`, copied to `~/.claude/deskpal/mac.py` and run by launchd from `mac/com.evan.deskpal-mac.plist`): checks in with the board every minute with its address and what each Claude Code session is doing (from the `turns/` files the hooks in `mac/deskpal-notify.py` keep), and takes the board's voice commands: "lock my Mac" (sleeps the display; the screen lock is set to immediately), "open ezwrite" (an app by name, or a site from `SITES`), "what's Claude doing?", "close calculator", "sleep my Mac", "hide everything", "Mac volume 30" / "mute my Mac", "put that on my clipboard", "what's this error?" (a screenshot goes to `api/look.js`, `openai/gpt-5-mini` or `VISION_MODEL`, and the Pal speaks the answer), and dictation ("dictation mode": KEY recordings are typed on the Mac until "stop dictation"; "type <words>" for one line). It's also the procrastination cop: 15 minutes on YouTube, X and co. in work hours and the Pal glares and tells you off; a focused workday gets a proud Pal at 5:30pm. macOS asks once each for Screen Recording, Accessibility and control of System Events and the browsers.

Upload: `python3 -m mpremote cp board/*.py board/*.bin : + cp secrets.py :secrets.py + reset`

Noty task sync (`board/noty_sync.py`) connects the Plan screen with the native
Mac Noty app and its private mobile page. Existing board tasks are added to their
own **Desk Pal** list; synced tasks are added alongside them. Task IDs, server
bases and pending requests survive restarts, and completed/deleted tasks sync
both ways. Existing projects stay local. The remote page shows sync status and
uses exact task IDs when several lists contain the same text.

`board/noty_notes.py` also caches full note text from `/api/notes`. The selected
Desk Pal note supplies Plan's five sections: `# to-do`, `# idea`, `# building`,
`# testing`, and `# shipped` (or `# shift`). Other notes are kept for context and
appear only after an explicit **show/open/display** request, such as “show my
work note”. KEY advances a shown note's page; BOOT returns to Plan. Scoped task
actions and clear-done cannot remove hidden work/buy note tasks. Project moves
edit the selected note's heading sections and sync back to Mac/mobile.

The voice server reads notes using its server-only `NOTY_SYNC_TOKEN` and
`NOTY_NOTES_URL` (the authenticated `/api/notes` address). All non-deleted notes,
including archived ones, are quoted reference data. Large bodies remain
available via explicit read/search pagination. A note question keeps the
screen unchanged; only a current spoken display request enables `show_note`.

Configure a private `noty-sync.json` on the board with `enabled`, the full HTTPS
`url` ending in `/api/sync`, the private task `token`, and optional `ca_file`
(default `noty-sync-ca.der`). Never commit that key or overwrite `secrets.py` for
this integration. The bundled CA comes from Google's public GTS Root R1 at
`https://pki.goog/repo/certs/gtsr1.der`; HTTPS verifies the certificate chain and
hostname. Polling runs every 30 seconds in a background thread, with local edits
debounced for 2 seconds. Requests and responses are capped at 128 KB and durable
state at 512 records; exceeding capacity reports an error and retains tasks.
The local 30-task add limit now refuses an extra task instead of deleting an old
one; synced imports can exceed that local limit without eviction.

Back up the board files and Mac notes before first pairing. Upload only
`main.py`, `plan.py`, `remote.py`, `noty_sync.py`, the CA and the separate sync
configuration when updating this feature. Leave `plan.json`, other data files,
and firmware/partitions in place. Sync state uses validated replacement files
and a recovery journal; unrecoverable files block sync rather than clearing
tasks. A new board must not receive another board's ledger or task IDs.

Run host checks with `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s test
-p 'test_*.py'`. `tools/verify_noty_sync.mjs` performs a live two-way check with one
disposable task and compares the original board tasks/projects and Mac note rows
against a saved baseline; it never edits an original task.

WhatsApp notifications (`board/phone.py`): the board is a Bluetooth ANCS client (Apple's Notification Center Service). Pair once from the iPhone's Settings > Bluetooth ("deskpal"), allow it to share notifications, and new WhatsApp notifications pop up like the agent alerts (8 s). Bonding keys live in `ble_bonds.json` on the board. Bluetooth takes ~50 KB of internal RAM, which is why the voice request thread is 30 KB, not 32.

Wake phrase ("gee gee", i.e. "gg"; `WAKE_PHRASES` in `board/audio.py`): needs Desk Pal's own MicroPython build, which adds a `wake` module (`firmware/wake/wake.c`: ESP-SR MultiNet7 English on core 0, fed by the mic at 15625 Hz resampled to 16 kHz, with a 16 s ring buffer so the question right after the phrase is kept). `firmware/build.sh` builds it (ESP-IDF v5.5.2 + MicroPython v1.29.0 under ~/esp) and prints the flash command; the new partition table (`firmware/board/partitions-deskpal.csv`) moves the filesystem, so back up board files before flashing and copy them back after. On stock MicroPython the board runs without the wake phrase.

Voice replies have no app-imposed token cap or sentence count: ask for a detailed explanation when you want one. The voice function has up to 300 seconds to generate the text and speech (not a playback-duration limit). The board starts speaking once ~1 s of the compressed reply has arrived and plays the rest as it downloads, decoding 4 KB PCM chunks so long answers never need a full uncompressed copy. The speaker buffer holds ~1 s, and nothing sleeps while audio is ready, so screen redraws and the download don't starve it; `audio.starved` counts any gaps (voice.py prints them). A download that breaks mid-reply stops playback instead of padding it.

If an answer opens a screen (limits, weather, radar...), the rest of that conversation stays on it: a little Pal in a blank stretch of that screen's header (never over any text) shows it's waiting for your reply, listening, thinking and talking. General questions use the full-screen Pal.

## Deploy your own (glasses server)

Your own copy, on your own Vercel, Upstash and AI Gateway: nothing here points at anyone else's server. The
ezmeta iPhone app needs two endpoints from it: `/api/glasses` (talk to Desk Pal) and `/api/agent` (the agent
pager). Everything else here (board, Spotify, flights, plan, limits, Mac control) is optional and can stay unset.
Every variable is listed, with a comment, in [`.env.example`](.env.example).

1. **Fork and import.** Fork github.com/evxnche/desk-voice, then Vercel → **Add New → Project** → import the
   fork. No build command; Vercel reads `vercel.json`. Hobby plan is fine (this repo stays at its 12 functions).
2. **Redis for the agent pager.** Project → **Storage** → **Upstash for Redis** (Marketplace) → free plan →
   connect it to the project. That sets `KV_REST_API_URL` and `KV_REST_API_TOKEN`.
3. **AI Gateway.** Vercel dashboard → **AI Gateway** → turn it on and add credits (the Grok, OpenAI and Perplexity calls are
   billed from them; the free monthly credit covers light use). On Vercel the functions authenticate with OIDC
   automatically, so no key is needed. Only outside Vercel, make an AI Gateway API key and set `AI_GATEWAY_API_KEY`.
   Default models, all through the gateway (override with the env vars in brackets):
   - speech to text: `spacexai/grok-stt` (`STT_MODEL`), falling back to `openai/gpt-4o-mini-transcribe`
   - chat: `openai/gpt-oss-120b` (`CHAT_MODEL`), with Perplexity web search as a gateway tool
   - text to speech: `spacexai/grok-tts`, voice `ara` (`TTS_MODEL`, `TTS_VOICE`)
4. **Noty (optional, for notes and tasks).** Deploy your own Noty sync server: the `web/` folder of your fork of
   github.com/evxnche/noty (its README has "Deploy your own"). Then `NOTY_NOTES_URL` is
   `https://<your-noty>.vercel.app/api/notes` and `NOTY_SYNC_TOKEN` is that server's `NOTY_SYNC_TOKEN`. There is
   no default server: without both, the glasses still answer but say notes can't be reached. "Add X to my tasks"
   also needs a Desk Pal note chosen in the Noty app.
5. **Make the key.** `openssl rand -hex 24` → that's your `VOICE_KEY`.
6. **Set the env vars** (Project → Settings → Environment Variables, Production): `VOICE_KEY`, the Noty pair,
   and `DESK_TZ` (e.g. `America/New_York`) + `DESK_PLACE` (e.g. `New York`) so times are yours, not India's.
7. **Deploy:** Deployments → **Redeploy** (env vars only apply to new deployments), or push to the fork.

Check it (replace the host and key):

```sh
H=https://your-desk-voice.vercel.app K=your-voice-key
curl -i "$H/api/glasses?k=$K"                      # 204 = key OK (401 = wrong key)
curl -s "$H/api/agent?k=$K"                        # {"events":[],"now":...} = Redis OK
curl -s -X POST "$H/api/agent?k=$K" -H 'Content-Type: application/json' \
  -d '{"agent":"Claude Code","project":"test","kind":"done","message":"hello"}'   # {"ok":true}
say -o q.wav --file-format=WAVE --data-format=LEI16@16000 "What time is it?"   # macOS; any 16 kHz 16-bit mono PCM works
curl -s -X POST "$H/api/glasses?k=$K" --data-binary @q.wav | head -1   # {"heard":"What time is it?","reply":"..."} = AI Gateway OK
```

A reply of "I've hit the free tier's limit" or "something went wrong" means AI Gateway needs credits; check the
function logs in Vercel.

**In the ezmeta iPhone app** (`Config/Secrets.xcconfig`): `VOICE_HOST` = your deployment's host with no
`https://` (e.g. `your-desk-voice.vercel.app`) and `VOICE_KEY` = the key from step 5.

**Agent alerts from your Mac (optional):** `mac/deskpal-notify.py` posts to `/api/agent`. Set
`DESKPAL_AGENT_URL=https://your-desk-voice.vercel.app/api/agent` in the environment your Claude Code hooks run
in, and put your `VOICE_KEY` in the `key` file next to the script.

Tests: `npm test` (JS) and `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s test -p 'test_*.py'` (board).
