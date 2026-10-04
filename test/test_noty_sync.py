"""Preservation and retry checks for the board's private Noty sync client."""
import copy
import importlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

BOARD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "board")
sys.path.insert(0, BOARD)
try:
    import noty_sync as sync
except ImportError:
    sync = None
sys.path.remove(BOARD)


def task(number=1, **updates):
    record = {"id": "%08x-0000-4000-8000-000000000001" % number,
              "noteId": "eeeeeeee-0000-4000-8000-000000000001",
              "listTitle": "Mac notes", "text": "Keep café 🦀 %d" % number,
              "completed": False, "position": number, "deleted": False, "version": 1}
    record.update(updates)
    return record


def response(records, conflicts=None):
    return {"tasks": copy.deepcopy(records), "conflicts": conflicts or []}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(sync, "Noty board client has not been implemented")
        self.ledger = sync.Ledger()

    def acknowledged(self):
        candidate = self.ledger.reconcile([{"t": "Existing board task", "done": False}])
        sent = self.ledger.prepare()
        remote = dict(sent[0]["task"], version=1)
        self.ledger.receive(response([remote]), sent)
        return self.ledger.visible(), remote

    def test_original_board_list_stays_first_independent_of_dictionary_order(self):
        original, acknowledged = self.acknowledged()
        imported = task(11, noteId="00000000-0000-4000-8000-000000000011")
        self.ledger.receive(response([acknowledged, imported]), [])
        saved = self.ledger.data()
        # MicroPython map iteration does not promise Python's insertion order.
        saved["entries"] = dict(reversed(list(saved["entries"].items())))
        restored = sync.Ledger(saved)
        self.assertEqual(restored.visible()[0]["id"], original[0]["id"])

    def test_adoption_keeps_existing_tasks_exact_and_creates_a_separate_list(self):
        before = [{"t": "Keep  board  spacing", "done": False},
                  {"t": "Already complete", "done": True}, {"t": "Third café 🦀", "done": False}]
        original = copy.deepcopy(before)
        candidate = self.ledger.reconcile(before)
        self.assertEqual(original, [{"t": t["t"], "done": t["done"]} for t in candidate])
        self.assertEqual(original, before)
        self.assertEqual(3, len({t["id"] for t in candidate}))
        self.assertTrue(all(t["noteId"] == self.ledger.device_note_id for t in candidate))
        self.assertTrue(all(t["listTitle"] == "Desk Pal" for t in candidate))
        self.assertTrue(all(c["base"] is None for c in self.ledger.prepare()))

    def test_empty_fetch_never_erases_local_tasks(self):
        self.ledger.reconcile([{"t": "Keep me", "done": False}])
        self.ledger.receive(response([]), [])
        self.assertEqual("Keep me", self.ledger.visible()[0]["t"])
        current, remote = self.acknowledged()
        before = self.ledger.data()
        with self.assertRaises(ValueError):
            self.ledger.receive(response([]), [])
        self.assertEqual(before, self.ledger.data())

    def test_restart_preserves_identifiers_base_null_and_frozen_first_post(self):
        first = self.ledger.reconcile([{"t": "First", "done": False}])
        sent = self.ledger.prepare()
        first[0]["t"] = "Edited while request was in flight"
        self.ledger.reconcile(first)
        restored = sync.Ledger(json.loads(json.dumps(self.ledger.data())))
        self.assertEqual(self.ledger.device_note_id, restored.device_note_id)
        self.assertEqual(sent, restored.prepare())
        accepted = dict(sent[0]["task"], version=1)
        restored.receive(response([accepted]), restored.prepare())
        following = restored.prepare()
        self.assertEqual(accepted, following[0]["base"])
        self.assertEqual("Edited while request was in flight", following[0]["task"]["text"])
        self.assertEqual(accepted["id"], following[0]["task"]["id"])

    def test_remote_add_completion_and_tombstone_apply_by_identity(self):
        local = self.ledger.reconcile([{"t": "Board original", "done": False}])
        remote = task()
        candidate = self.ledger.receive(response([remote]), [])
        self.assertEqual(2, len(candidate))
        self.assertIn("Board original", [t["t"] for t in candidate])
        remote = dict(remote, completed=True, version=2)
        candidate = self.ledger.receive(response([remote]), [])
        self.assertTrue(next(t for t in candidate if t["id"] == remote["id"])["done"])
        remote = dict(remote, deleted=True, version=3)
        candidate = self.ledger.receive(response([remote]), [])
        self.assertEqual([local[0]["id"]], [t["id"] for t in candidate])
        self.assertTrue(self.ledger.entries[remote["id"].lower()]["base"]["deleted"])

    def test_local_remove_and_clear_done_export_tombstones(self):
        self.ledger.receive(response([task(1), task(2, completed=True)]), [])
        self.ledger.reconcile([t for t in self.ledger.visible() if not t["done"]])
        changes = self.ledger.prepare()
        self.assertEqual(1, len(changes))
        self.assertTrue(changes[0]["task"]["deleted"])
        self.assertEqual(task(2, completed=True), changes[0]["base"])

    def test_delete_during_first_post_survives_lost_acknowledgement(self):
        self.ledger.reconcile([{"t": "Remove while sending", "done": False}])
        sent = self.ledger.prepare()
        self.ledger.reconcile([])
        restored = sync.Ledger(self.ledger.data())
        self.assertEqual(sent, restored.prepare())
        accepted = dict(sent[0]["task"], version=1)
        self.assertEqual([], restored.receive(response([accepted]), sent))
        delete = restored.prepare()[0]
        self.assertTrue(delete["task"]["deleted"])
        self.assertEqual(accepted, delete["base"])

    def test_in_flight_local_edit_keeps_remote_disjoint_completion(self):
        local, remote = self.acknowledged()
        self.ledger.prepare()  # GET snapshot
        local[0]["t"] = "Local edited text"
        self.ledger.reconcile(local)
        remote = dict(remote, completed=True, version=2)
        candidate = self.ledger.receive(response([remote]), [])
        self.assertEqual("Local edited text", candidate[0]["t"])
        self.assertTrue(candidate[0]["done"])
        self.assertEqual(remote, self.ledger.prepare()[0]["base"])

    def test_conflicting_local_text_is_kept_under_new_identity(self):
        local, remote = self.acknowledged()
        local[0]["t"] = "Local text worth keeping"
        self.ledger.reconcile(local)
        sent = self.ledger.prepare()
        remote = dict(remote, text="Mac text worth keeping", version=2)
        candidate = self.ledger.receive(response([remote], [{"id": remote["id"], "task": remote}]), sent)
        self.assertEqual({"Local text worth keeping", "Mac text worth keeping"}, {t["t"] for t in candidate})
        recovered = self.ledger.prepare()[0]
        self.assertIsNone(recovered["base"])
        self.assertNotEqual(remote["id"], recovered["task"]["id"])
        self.assertEqual(1, self.ledger.conflicts)

    def test_remote_delete_does_not_revive_identity_but_preserves_unsent_edit(self):
        local, remote = self.acknowledged()
        local[0]["t"] = "Keep my unfinished edit"
        self.ledger.reconcile(local)
        remote = dict(remote, deleted=True, version=2)
        candidate = self.ledger.receive(response([remote]), [])
        self.assertEqual("Keep my unfinished edit", candidate[0]["t"])
        self.assertNotEqual(remote["id"], candidate[0]["id"])
        self.assertTrue(self.ledger.entries[remote["id"].lower()]["task"]["deleted"])

    def test_identical_titles_and_case_insensitive_ids_keep_distinct_lists(self):
        records = [task(1, text="Same", listTitle="Same title"),
                   task(2, text="Same", listTitle="Same title", noteId="dddddddd-0000-4000-8000-000000000001")]
        candidate = self.ledger.receive(response(records), [])
        self.assertEqual(2, len(candidate))
        candidate[0]["id"] = candidate[0]["id"].upper()
        self.ledger.reconcile(candidate)
        self.assertEqual([], self.ledger.prepare())
        self.assertEqual(2, len(self.ledger.entries))

    def test_invalid_response_and_corrupt_state_leave_ledger_untouched(self):
        self.ledger.reconcile([{"t": "Do not reset", "done": False}])
        before = self.ledger.data()
        invalid = task(text="invalid\nmultiline")
        with self.assertRaises(ValueError):
            self.ledger.receive(response([invalid]), [])
        self.assertEqual(before, self.ledger.data())
        damaged = copy.deepcopy(before)
        damaged["entries"][next(iter(damaged["entries"]))]["base"] = {"broken": True}
        with self.assertRaises(ValueError):
            sync.Ledger(damaged)

    def test_capacity_rejects_without_evicting_any_task(self):
        self.ledger.reconcile([{"t": "Board must stay", "done": False}])
        before = self.ledger.data()
        with self.assertRaises(ValueError):
            self.ledger.receive(response([task(i) for i in range(1, 31)]), [], capacity=30)
        self.assertEqual(before, self.ledger.data())

    def test_outbound_batch_fits_transport_limit_without_discarding_pending(self):
        local = [{"t": "🦀" * 1000, "done": False} for _ in range(40)]
        self.ledger.reconcile(local)
        sent = self.ledger.prepare()
        self.assertGreater(len(sent), 0)
        self.assertLess(len(sent), 40)
        self.assertLessEqual(len(json.dumps({"changes": sent}).encode()), sync.MAX_BYTES)
        self.assertEqual(40, len(self.ledger.visible()))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(sync, "Noty board client has not been implemented")
        self.directory = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.directory.name)
        self.plan = types.ModuleType("plan")
        self.plan.tasks = [{"t": "Existing board task", "done": False}]
        self.plan.MAX_TASKS = 30
        self.plan.version = 0
        self.plan.apply_tasks = self.apply
        self.modules = patch.dict(sys.modules, {"plan": self.plan})
        self.modules.start()
        sys.path.insert(0, BOARD)
        self.sync = importlib.reload(sync)
        self.now = 5000
        self.clock = patch.object(self.sync, "_now", lambda: self.now)
        self.clock.start()
        self.stack = patch.object(self.sync._thread, "stack_size", lambda size: None)
        self.stack.start()
        with open("noty-sync.json", "w") as out:
            json.dump({"enabled": True, "url": "https://noty-task-sync.vercel.app/api/sync", "token": "x" * 40}, out)

    def tearDown(self):
        self.clock.stop()
        self.stack.stop()
        self.modules.stop()
        sys.path.remove(BOARD)
        os.chdir(self.cwd)
        self.directory.cleanup()

    def apply(self, candidate):
        self.plan.tasks = copy.deepcopy(candidate)
        self.plan.version += 1
        return True

    def test_corrupt_ledger_blocks_start_without_touching_plan(self):
        with open("noty-sync-state.json", "w") as out:
            out.write("broken json")
        before = copy.deepcopy(self.plan.tasks)
        self.assertFalse(self.sync.start())
        self.assertEqual(before, self.plan.tasks)
        self.assertIn("state", self.sync.status().lower())

    def test_atomic_state_write_failure_keeps_previous_file_and_plan(self):
        self.assertTrue(self.sync.start())
        with open("noty-sync-state.json") as source:
            before = source.read()
        prior = copy.deepcopy(self.plan.tasks)
        def broken(value, out):
            out.write("{")
            raise OSError("full disk")
        with patch.object(self.sync.json, "dump", side_effect=broken):
            with self.assertRaises(OSError):
                self.sync._save_state(self.sync._ledger.data())
        with open("noty-sync-state.json") as source:
            self.assertEqual(before, source.read())
        self.assertEqual(prior, self.plan.tasks)

    def test_valid_backup_recovers_corrupt_state_without_resetting_ids(self):
        self.assertTrue(self.sync.start())
        identifiers = [t["id"] for t in self.plan.tasks]
        with open("noty-sync-state.json") as source:
            saved = source.read()
        with open("noty-sync-state.json.bak", "w") as out:
            out.write(saved)
        with open("noty-sync-state.json", "w") as out:
            out.write("broken")
        self.sync = importlib.reload(self.sync)
        self.assertTrue(self.sync.start())
        self.assertEqual(identifiers, [t["id"] for t in self.plan.tasks])

    def test_cannot_launch_thread_never_runs_network_on_main_thread(self):
        self.assertTrue(self.sync.start())
        with patch.object(self.sync._thread, "start_new_thread", side_effect=OSError("no thread")), \
             patch.object(self.sync, "_request") as request:
            self.sync.tick(lambda: True)
            request.assert_not_called()
        self.assertIn("retry", self.sync.status().lower())

    def test_worker_only_publishes_response_then_main_tick_applies(self):
        self.assertTrue(self.sync.start())
        callbacks = []
        with patch.object(self.sync._thread, "start_new_thread", side_effect=lambda function, args: callbacks.append((function, args))):
            self.sync.tick(lambda: True)
        before = copy.deepcopy(self.plan.tasks)
        outgoing = callbacks[0][1][1]
        records = [dict(c["task"], version=1) for c in outgoing] + [task()]
        with patch.object(self.sync, "_request", return_value=response(records)):
            function, args = callbacks.pop()
            function(*args)
        self.assertEqual(before, self.plan.tasks)
        self.sync.tick(lambda: False)
        self.assertEqual(2, len(self.plan.tasks))
        self.assertNotIn("token", self.sync.info())

    def test_idle_poll_waits_thirty_seconds_and_local_changes_debounce(self):
        self.assertTrue(self.sync.start())
        calls = []
        def launch(fn, args):
            calls.append(args)
            with patch.object(self.sync, "_request", return_value=response([dict(c["task"], version=1) for c in args[1]])):
                fn(*args)
        with patch.object(self.sync._thread, "start_new_thread", side_effect=launch):
            self.sync.tick(lambda: True)
            self.now += 2000
            self.sync.tick(lambda: True)
            self.assertEqual(1, len(calls))
            self.plan.tasks[0]["done"] = True
            self.sync.changed()
            self.sync.tick(lambda: True)
            self.now += 1999
            self.sync.tick(lambda: True)
            self.assertEqual(1, len(calls))
            self.now += 1
            self.sync.tick(lambda: True)
            self.assertEqual(2, len(calls))

    def test_recovery_journal_does_not_overwrite_newer_board_tasks(self):
        self.assertTrue(self.sync.start())
        saved = self.sync._ledger.data()
        saved["pending_before"] = copy.deepcopy(self.plan.tasks)
        saved["pending_plan"] = copy.deepcopy(self.plan.tasks) + [{"t": "Remote addition", "done": False}]
        self.sync._save_state(saved)
        self.plan.tasks.append({"t": "Newer board addition", "done": False})
        before = copy.deepcopy(self.plan.tasks)
        self.sync = importlib.reload(self.sync)
        self.assertFalse(self.sync.start())
        self.assertEqual(before, self.plan.tasks)

    def test_cloud_task_thirty_one_does_not_evict_existing_board_task(self):
        self.assertTrue(self.sync.start())
        callbacks = []
        with patch.object(self.sync._thread, "start_new_thread", side_effect=lambda fn, args: callbacks.append((fn, args))):
            self.sync.tick(lambda: True)
        fn, args = callbacks[0]
        records = [dict(c["task"], version=1) for c in args[1]] + [task(i) for i in range(1, 32)]
        with patch.object(self.sync, "_request", return_value=response(records)):
            fn(*args)
        self.sync.tick(lambda: False)
        self.assertEqual(32, len(self.plan.tasks))
        self.assertIn("Existing board task", [t["t"] for t in self.plan.tasks])

    def test_missing_ledger_with_paired_tasks_blocks_reset(self):
        self.plan.tasks = [{"t": "Keep paired task", "done": False, "id": task()["id"],
                            "noteId": task()["noteId"], "listTitle": "Mac notes"}]
        original = copy.deepcopy(self.plan.tasks)
        self.assertFalse(self.sync.start())
        self.assertEqual(original, self.plan.tasks)
        self.assertFalse(os.path.exists("noty-sync-state.json"))

    def test_network_failure_preserves_tasks_and_same_outbound_snapshot(self):
        self.assertTrue(self.sync.start())
        callbacks = []
        with patch.object(self.sync._thread, "start_new_thread", side_effect=lambda fn, args: callbacks.append((fn, args))):
            self.sync.tick(lambda: True)
            fn, args = callbacks.pop()
            snapshot = copy.deepcopy(args[1])
            original = copy.deepcopy(self.plan.tasks)
            with patch.object(self.sync, "_request", side_effect=OSError("network down")):
                fn(*args)
            self.sync.tick(lambda: False)
            self.assertEqual(original, self.plan.tasks)
            self.now += 30000
            self.sync.tick(lambda: True)
            self.assertEqual(snapshot, callbacks.pop()[1][1])

    def test_interrupted_plan_journal_recovers_the_committed_candidate(self):
        self.assertTrue(self.sync.start())
        saved = self.sync._ledger.data()
        saved["pending_before"] = copy.deepcopy(self.plan.tasks)
        candidate = copy.deepcopy(self.plan.tasks)
        candidate[0]["done"] = True
        saved["entries"][candidate[0]["id"].lower()]["task"]["completed"] = True
        saved["pending_plan"] = candidate
        self.sync._save_state(saved)
        self.sync = importlib.reload(self.sync)
        self.assertTrue(self.sync.start())
        self.assertEqual(candidate, self.plan.tasks)
        with open("noty-sync-state.json") as source:
            self.assertNotIn("pending_plan", json.load(source))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(sync, "Noty board client has not been implemented")

    def test_http_content_length_is_bounded_and_incomplete_bodies_rejected(self):
        with self.assertRaises(ValueError):
            sync._read_body(io.BytesIO(b"abc"), {"content-length": "131073"})
        with self.assertRaises(ValueError):
            sync._read_body(io.BytesIO(b"abc"), {"content-length": "10"})
        self.assertEqual(b"abc", sync._read_body(io.BytesIO(b"abc"), {"content-length": "3"}))

    def test_chunked_body_is_bounded_and_validated(self):
        self.assertEqual(b"abc", sync._read_body(io.BytesIO(b"3\r\nabc\r\n0\r\n\r\n"), {"transfer-encoding": "chunked"}))
        with self.assertRaises(ValueError):
            sync._read_body(io.BytesIO(b"20001\r\n"), {"transfer-encoding": "chunked"})
        with self.assertRaises(ValueError):
            sync._read_body(io.BytesIO(b"3\r\na"), {"transfer-encoding": "chunked"})

    def test_read_budget_expires_across_multiple_reads(self):
        clock = [100]
        fake_socket = types.SimpleNamespace(settimeout=lambda timeout: None)
        with patch.object(sync, "_now", side_effect=lambda: clock[0]):
            stream = sync._Budget(io.BytesIO(b"abc"), fake_socket, 0)
            self.assertEqual(b"a", stream.read(1))
            clock[0] = 15001
            with self.assertRaises(OSError):
                stream.read(1)


if __name__ == "__main__":
    unittest.main()
