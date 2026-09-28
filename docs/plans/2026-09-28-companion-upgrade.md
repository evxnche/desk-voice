# Desk Pal Companion Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give Desk Pal coherent visual presence, useful continuity about agent alerts and preferences, and respectful proactive behavior during focus sessions.

**Architecture:** Keep durable state on the board in small JSON files and send bounded, base64-encoded context headers with voice requests. Keep visual additions hardware-cheap through a standalone compact pixel Pal renderer. Extend the existing command pipeline rather than adding a second service or protocol.

**Tech Stack:** MicroPython, Vercel Node functions, Vercel AI SDK, browser JavaScript, Python unittest, Node test runner.

---

### Task 1: Companion state and interruption policy

**Files:**
- Create: `board/memories.py`
- Modify: `board/alerts.py`
- Modify: `board/companion.py`
- Modify: `board/main.py`
- Test: `test/test_companion_state.py`

**Step 1: Write failing tests**

Cover bounded memory add/delete persistence, duplicate alert suppression, latest input-request context, duplicate proactive-event replacement, stale urgent-event expiry, and focus-mode deferral.

**Step 2: Verify the tests fail**

Run: `python3 -m unittest test.test_companion_state -v`

Expected: failures for the missing memory module and state APIs.

**Step 3: Implement the minimal state changes**

Add a twelve-entry JSON memory store. Make `alerts.add()` return whether a distinct alert was inserted and expose the latest `needs` alert. Change companion queue items to bounded dictionaries with deduplication, urgency, and universal expiry. Pass focus state into `next_line()` and avoid chiming duplicate agent events.

**Step 4: Verify the task**

Run: `python3 -m unittest test.test_companion_state -v`

Expected: all tests pass.

### Task 2: Voice context, memory commands, and remote controls

**Files:**
- Modify: `board/voice.py`
- Modify: `board/main.py`
- Modify: `board/remote.py`
- Modify: `api/voice.js`
- Test: `test/voice-context.test.js`
- Test: `test/test_remote_memory.py`

**Step 1: Write failing tests**

Cover safe decoding of bounded memory and alert headers, memory command generation, alert-display command generation, and the remote page’s memory controls.

**Step 2: Verify the tests fail**

Run: `node --test test/voice-context.test.js && python3 -m unittest test.test_remote_memory -v`

Expected: failures for missing context helpers and routes.

**Step 3: Implement the minimal integration**

Send `X-Memories` and `X-Agent-Alert` from the board. Add both to the assistant’s factual system context. Add explicit remember, forget, and show-latest-alert tools which return existing board commands. Apply those commands in `main.run()`. Expose memory list/add/delete routes and render them on the local remote page.

**Step 4: Verify the task**

Run: `node --test test/voice-context.test.js && python3 -m unittest test.test_remote_memory -v`

Expected: all tests pass.

### Task 3: Contextual Pal visuals and conversation cues

**Files:**
- Create: `board/palicon.py`
- Modify: `board/pal.py`
- Modify: `board/voice.py`
- Modify: `board/dashboard.py`
- Modify: `board/room.py`
- Modify: `board/flights.py`
- Modify: `board/tracker.py`
- Modify: `board/music.py`
- Modify: `board/timer.py`
- Modify: `board/alerts.py`
- Test: `test/test_pal_visuals.py`

**Step 1: Write failing tests**

Use a recording canvas to verify every compact Pal pose remains within its bounds and produces distinct visual operations. Test three-line large caption pagination, visible follow-up hint text, and rotating ambient status content.

**Step 2: Verify the tests fail**

Run: `python3 -m unittest test.test_pal_visuals -v`

Expected: failures for the missing compact renderer and new caption contract.

**Step 3: Implement the visual layer**

Draw the compact Pal with rectangles and lines only. Reserve safe screen-specific positions, keeping dense data readable. Render captions in three large lines, show `say your reply` with a countdown, and rotate ambient secondary status every six seconds.

**Step 4: Verify the complete project**

Run: `python3 -m unittest discover -s test -p 'test_*.py' -v`

Run: `node --test test/*.test.js`

Run: `node --check api/voice.js && python3 -m compileall -q board`

Expected: every test and syntax check passes with no warnings or errors.
