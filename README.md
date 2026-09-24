# desk-voice

Firmware + backend for a Waveshare ESP32-S3-RLCD-4.2 desk gadget (MicroPython v1.29).

- `board/` — MicroPython app. Screens (BOOT cycles): agent usage limits, room (time + temp/humidity), Pixel Pal game, flight radar (`api/flights.js` -> adsb.lol). KEY tap refreshes limits; KEY hold = talk to the assistant.
- `api/voice.js` — Vercel function: 15625 Hz mono PCM in -> transcribe (openai/gpt-4o-mini-transcribe) -> openai/gpt-5-mini (free tier; Claude needs paid credits) -> TTS (openai/tts-1) -> PCM out, all via AI Gateway (OIDC).

`board/rlcd.py` is adapted from micheleaiello/ESP32-S3-4.2inch-RLCD-Driver (GPL-3.0); `show()` was rewritten in viper (~36 ms/frame).

Fonts: `board/font_*.bin` are 1-bit bitmaps of MS Gothic (small), Departure Mono (text) and ABC Areal Mono Bold (headings), made by `python3 tools/make_fonts.py` from the TTFs in ~/Library/Fonts; `board/bitfont.py` draws them.

Upload: `python3 -m mpremote cp board/*.py board/*.bin : + cp secrets.py :secrets.py + reset`
