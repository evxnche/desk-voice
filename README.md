# desk-voice

Firmware + backend for a Waveshare ESP32-S3-RLCD-4.2 desk gadget (MicroPython v1.29).

- `board/` — MicroPython app. Screens (BOOT cycles): agent usage limits, room (time + temp/humidity), pixel critter animation. KEY tap refreshes limits; KEY hold = talk to Claude.
- `api/voice.js` — Vercel function: 15625 Hz mono PCM in -> transcribe (openai/gpt-4o-mini-transcribe) -> Claude Haiku 4.5 -> TTS (openai/tts-1) -> PCM out, all via AI Gateway (OIDC).

`board/rlcd.py` is adapted from micheleaiello/ESP32-S3-4.2inch-RLCD-Driver (GPL-3.0); `show()` was rewritten in viper (~36 ms/frame).

Upload: `python3 -m mpremote cp board/*.py : + cp secrets.py :secrets.py + reset`
