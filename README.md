# desk-voice

Firmware + backend for a Waveshare ESP32-S3-RLCD-4.2 desk gadget (MicroPython v1.29).

- `board/` — MicroPython app. Screens (BOOT cycles): the Pal (Claude's pixel crab, the start screen: `pal.py`; reacts when it hears talking, asleep 22:00-08:00, and is the assistant's face while it listens, thinks and speaks), agent usage limits, room (time + temp/humidity), Pixel Pal game, flight radar (`api/flights.js` -> adsb.lol). KEY tap refreshes limits; KEY hold = talk to the assistant. After an answer it listens 6 s for a reply without the wake phrase and remembers the last 6 exchanges for 10 minutes (RAM only). `companion.py` speaks up on its own via `api/say.js`: Claude/Codex needs you, a limit passes 90%, rain within the hour, a morning hello.
- `api/voice.js` — Vercel function: 15625 Hz mono PCM in -> transcribe (spacexai/grok-stt; `STT_MODEL` env overrides it) -> openai/gpt-oss-120b (fastest free-tier model; `CHAT_MODEL` env overrides it) -> TTS (spacexai/grok-tts, voice Ara; `TTS_MODEL` / `TTS_VOICE` env override them) -> PCM out, all via AI Gateway (OIDC). With `X-Audio: adpcm` (the board sends it) audio goes both ways as 4-bit IMA ADPCM, a quarter of the bytes (`lib/adpcm.js`, `board/adpcm.py`).

`board/rlcd.py` is adapted from micheleaiello/ESP32-S3-4.2inch-RLCD-Driver (GPL-3.0); `show()` was rewritten in viper (~36 ms/frame).

Fonts: `board/font_*.bin` are 1-bit bitmaps of MS Gothic (small), Departure Mono (text) and ABC Areal Mono Bold (headings), made by `python3 tools/make_fonts.py` from the TTFs in ~/Library/Fonts; `board/bitfont.py` draws them.

Upload: `python3 -m mpremote cp board/*.py board/*.bin : + cp secrets.py :secrets.py + reset`

WhatsApp notifications (`board/phone.py`): the board is a Bluetooth ANCS client (Apple's Notification Center Service). Pair once from the iPhone's Settings > Bluetooth ("deskpal"), allow it to share notifications, and new WhatsApp notifications pop up like the agent alerts (8 s). Bonding keys live in `ble_bonds.json` on the board. Bluetooth takes ~50 KB of internal RAM, which is why the voice request thread is 30 KB, not 32.

Wake phrase ("gee gee", i.e. "gg" said "gigi"; `WAKE_PHRASES` in `board/audio.py`): needs Desk Pal's own MicroPython build, which adds a `wake` module (`firmware/wake/wake.c`: ESP-SR MultiNet7 English on core 0, fed by the mic at 15625 Hz resampled to 16 kHz, with a 16 s ring buffer so the question right after the phrase is kept). `firmware/build.sh` builds it (ESP-IDF v5.5.2 + MicroPython v1.29.0 under ~/esp) and prints the flash command; the new partition table (`firmware/board/partitions-deskpal.csv`) moves the filesystem, so back up board files before flashing and copy them back after. On stock MicroPython the board runs without the wake phrase.
