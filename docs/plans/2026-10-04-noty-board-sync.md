# Preserve existing data while sharing Noty tasks with Desk Pal

User scope: wire the ESP32 into the already deployed Noty HTTPS service. Existing
board tasks and projects and existing Mac notes must keep their content and state.

## Preservation gates

Before edits, back up all board files and take a transaction-consistent SQLite
backup of Noty's database plus its encryption key and sync files. Backups are under
`../backups/noty-sync-2026-10-04-01a1043f/`. The live baseline contains three board
tasks, eight projects, and four Mac notes. Do not print or commit credentials.

The initial connection is additive: existing board tasks become a separate
Desk Pal list with stable IDs; Noty tasks are appended to the board. No migration
may truncate task text, change completion flags, remove a local task, or evict an
older task. Existing Mac note rows must compare equal to their backup after
the board's list is added. Take another board snapshot immediately before upload
so new user edits made during development are also preserved.

## Implementation

1. Add a MicroPython sync ledger and background network client in `board/noty_sync.py`.
   Keep task IDs/bases durable, queue offline changes, use the existing Noty API,
   merge fields against bases, preserve conflicting text as a separate task,
   retain tombstones, and handle first-upload deletions and lost acknowledgements.
   Only the main thread applies results to the plan. The client must fail closed
   on corrupted state, invalid responses, network errors and storage failures.
2. Make plan writes atomic and preserve projects. Add `apply_tasks` for the client,
   exact-ID task actions for duplicated text, and a save notification callback.
   Replace silent 30-task eviction with refusal of an extra local task at capacity;
   importing a synced list must not use this cap to discard existing tasks.
3. Hook bounded polling into `main.py` and expose safe sync status on the board's
   existing remote page. Store the private HTTPS endpoint/key in a separate,
   ignored `noty-sync.json`; never overwrite `secrets.py` or other agent fixes.
4. Run meaningful preservation/concurrency tests, review changes, upload only the
   changed application files and new sync configuration, then verify the actual
   board's HTTP state, persisted task/project baseline, and original Mac note rows.
   Keep test task IDs isolated and remove only created verification fixtures.

No new dependencies, board firmware flash, partition changes, bulk overwrite of
`plan.json`, or Noty app code changes are required. Preserve pre-existing board
modules and unrelated local work. Success requires live board↔service checks as
well as host tests; screen rendering and physical voice interaction are separate
evidence boundaries.
