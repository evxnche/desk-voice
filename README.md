# desk-voice

Firmware + backend for a Waveshare ESP32-S3-RLCD-4.2 desk gadget (MicroPython v1.29).

- `board/` — MicroPython app. Screens (BOOT cycles): agent usage limits, room (time + temp/humidity), Pixel Pal game, flight radar (`api/flights.js` -> adsb.lol). KEY tap refreshes limits; KEY hold = talk to the assistant.
- `api/voice.js` — Vercel function: 15625 Hz mono PCM in -> transcribe (openai/gpt-4o-mini-transcribe) -> openai/gpt-oss-120b (fastest free-tier model; `CHAT_MODEL` env overrides it) -> TTS (openai/tts-1) -> PCM out, all via AI Gateway (OIDC). With `X-Audio: adpcm` (the board sends it) audio goes both ways as 4-bit IMA ADPCM, a quarter of the bytes (`lib/adpcm.js`, `board/adpcm.py`).

`board/rlcd.py` is adapted from micheleaiello/ESP32-S3-4.2inch-RLCD-Driver (GPL-3.0); `show()` was rewritten in viper (~36 ms/frame).

Fonts: `board/font_*.bin` are 1-bit bitmaps of MS Gothic (small), Departure Mono (text) and ABC Areal Mono Bold (headings), made by `python3 tools/make_fonts.py` from the TTFs in ~/Library/Fonts; `board/bitfont.py` draws them.

Upload: `python3 -m mpremote cp board/*.py board/*.bin : + cp secrets.py :secrets.py + reset`

WhatsApp notifications (`board/phone.py`): the board is a Bluetooth ANCS client (Apple's Notification Center Service). Pair once from the iPhone's Settings > Bluetooth ("deskpal"), allow it to share notifications, and new WhatsApp notifications pop up like the agent alerts (8 s). Bonding keys live in `ble_bonds.json` on the board. Bluetooth takes ~50 KB of internal RAM, which is why the voice request thread is 30 KB, not 32.

Wake phrase ("easy", i.e. "EZ"; `WAKE_PHRASES` in `board/audio.py`): needs Desk Pal's own MicroPython build, which adds a `wake` module (`firmware/wake/wake.c`: ESP-SR MultiNet7 English on core 0, fed by the mic at 15625 Hz resampled to 16 kHz, with a 16 s ring buffer so the question right after the phrase is kept). `firmware/build.sh` builds it (ESP-IDF v5.5.2 + MicroPython v1.29.0 under ~/esp) and prints the flash command; the new partition table (`firmware/board/partitions-deskpal.csv`) moves the filesystem, so back up board files before flashing and copy them back after. On stock MicroPython the board runs without the wake phrase.
