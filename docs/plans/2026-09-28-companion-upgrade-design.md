# Desk Pal Companion Upgrade Design

## Goal

Make Desk Pal feel like one continuous companion across its utility screens and conversations. It should understand the agent alert it just delivered, remember a few explicit owner preferences, defer ordinary interruptions during focus sessions, and communicate more clearly through the monochrome display.

## Interaction design

Utility screens receive a compact contextual Pal badge drawn from the same rectangular pixel language as the full-size crab. The badge uses a small set of poses: focus, music, weather, flights, tracking, alert, and celebration. Dense screens keep the badge in deliberately reserved whitespace; the Pixel Pal game and full Pal screen already have character presence and do not need a second badge.

Voice captions use up to three larger lines per page. During the six-second follow-up window, the full Pal screen shows a visible `say your reply` cue and countdown. The ambient footer rotates between weather and agent usage instead of compressing all status into one dense line.

## Companion context

The board retains the latest agent alert as structured data: agent, project, message, kind, and local time. Each voice request sends this bounded context to the backend. The backend treats it as factual device state, allowing natural follow-ups such as “What does it need?” and “Show me the alert.” Showing it means returning the board to its alert-detail screen; opening a desktop Codex or Claude task is outside the board’s current one-way LAN protocol.

The companion announcement queue deduplicates identical events, caps its length, and expires every kind after thirty minutes. While a running timer is labelled `Focus`, ordinary greetings, weather, limit, and flight announcements wait. Agent input requests remain urgent and may interrupt.

## Persistent memory

`board/memories.py` stores at most twelve short explicit memories in `memories.json`. Memory changes happen only through an explicit voice request or the local remote page. The voice backend receives the current list and can call add, remove, or clear tools. The remote page lists each entry with a delete button and includes a small add field. Values are length-limited and rendered with `textContent` in the browser.

## Boundaries and verification

The change adds no dependency. Host-side Python tests stub hardware modules and cover memory persistence, alert deduplication, focus scheduling, and Pal-badge geometry. Node tests cover header context parsing and voice command generation. Existing Node tests, Python syntax compilation, and JavaScript syntax checks remain required. Hardware display timing, audio quality, and the flashed board remain manual checks because the board is currently unreachable on the LAN.
