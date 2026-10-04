"""Plan preservation at capacity, during sync replacement and failed writes."""
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

BOARD = os.path.join(os.path.dirname(os.path.dirname(__file__)), "board")


class PlanStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.temp.name)
        self.saved = {"tasks": [{"t": "Original task", "done": False}],
                      "projects": [{"n": "Existing project", "s": "building"}]}
        with open("plan.json", "w") as target:
            json.dump(self.saved, target)
        modules = {name: types.ModuleType(name) for name in ("dashboard", "font5", "room", "schedule")}
        modules["dashboard"].ascii = str
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        sys.path.insert(0, BOARD)
        sys.modules.pop("plan", None)
        self.plan = importlib.import_module("plan")

    def tearDown(self):
        sys.modules.pop("plan", None)
        sys.path.remove(BOARD)
        self.modules.stop()
        os.chdir(self.cwd)
        self.temp.cleanup()

    def read(self):
        with open("plan.json") as source:
            return json.load(source)

    def test_full_local_list_refuses_add_instead_of_evicting_existing_tasks(self):
        original = [{"t": "Task %d" % i, "done": i % 2 == 0} for i in range(self.plan.MAX_TASKS)]
        self.plan.tasks[:] = original
        self.plan._save()
        self.assertFalse(self.plan.add_task("One more"))
        self.assertEqual(self.plan.tasks, original)
        self.assertEqual(self.read()["tasks"], original)

    def test_sync_import_preserves_original_tasks_and_projects_above_local_capacity(self):
        incoming = self.plan.tasks + [{"t": "Synced %d" % i, "done": False, "id": str(i)} for i in range(40)]
        self.plan.apply_tasks(incoming)
        self.assertEqual(self.read()["tasks"], incoming)
        self.assertEqual(self.read()["projects"], self.saved["projects"])
        self.assertEqual(self.plan.tasks[0], self.saved["tasks"][0])

    def test_duplicate_task_text_actions_target_exact_id(self):
        self.plan.apply_tasks([{"t": "Same", "done": False, "id": "first"},
                               {"t": "Same", "done": False, "id": "second"}])
        self.assertTrue(self.plan.finish_task("Same", True, task_id="second"))
        self.assertEqual([task["done"] for task in self.plan.tasks], [False, True])
        self.assertTrue(self.plan.remove_task("Same", task_id="first"))
        self.assertEqual([task["id"] for task in self.plan.tasks], ["second"])
        self.assertFalse(self.plan.remove_task("Same", task_id="missing"))

    def test_failed_sync_write_preserves_both_saved_file_and_memory(self):
        before = self.read()
        with patch.object(self.plan.json, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.plan.apply_tasks([{"t": "Replacement", "done": True}])
        self.assertEqual(self.read(), before)
        self.assertEqual(self.plan.tasks, before["tasks"])

    def test_atomic_write_failure_does_not_overwrite_saved_plan(self):
        before = self.read()
        with patch.object(self.plan.os, "rename", side_effect=OSError(5, "I/O failure")):
            with self.assertRaises(OSError):
                self.plan.apply_tasks([{"t": "Replacement", "done": True}])
        self.assertEqual(self.read(), before)
        self.assertEqual(self.plan.tasks, before["tasks"])

    def test_save_notifies_sync_after_the_data_is_persisted(self):
        observed = []
        self.plan.on_change = lambda: observed.append(self.read()["tasks"])
        self.assertTrue(self.plan.add_task("New task"))
        self.assertEqual(observed, [self.plan.tasks])

    def test_incomplete_primary_recovers_the_last_valid_backup(self):
        with open("plan.json.bak", "w") as target:
            json.dump(self.saved, target)
        with open("plan.json", "w") as target:
            target.write("{partial")
        self.plan = importlib.reload(self.plan)
        self.assertEqual(self.plan.tasks, self.saved["tasks"])
        self.assertEqual(self.plan.projects, self.saved["projects"])
        self.assertEqual(self.plan.storage_error, "")

    def test_unrecoverable_storage_blocks_sync_overwriting_tasks(self):
        with open("plan.json", "w") as target:
            target.write("{partial")
        self.plan = importlib.reload(self.plan)
        self.assertTrue(self.plan.storage_error)
        with self.assertRaises(OSError):
            self.plan.apply_tasks([{"t": "Should not replace", "done": False}])
        with open("plan.json") as source:
            self.assertEqual(source.read(), "{partial")

    def test_sync_notification_error_cannot_undo_a_successful_file_write(self):
        def fail():
            raise OSError("sync notifier unavailable")
        self.plan.on_change = fail
        self.plan.apply_tasks([{"t": "Saved task", "done": False}])
        self.assertEqual(self.read()["tasks"], self.plan.tasks)

    def scoped(self):
        visible = {"t": "Desk task", "done": True, "id": "desk", "noteId": "eeeeeeee-0000-4000-8000-000000000001"}
        hidden = {"t": "Work task", "done": True, "id": "work", "noteId": "work-note"}
        self.plan.apply_tasks([visible, hidden])
        document_task = dict(visible)
        self.plan.view_data = lambda: {"tasks": [dict(document_task)], "projects": [{"n": "Shown project", "s": "idea"}],
                                       "note_id": "eeeeeeee-0000-4000-8000-000000000001"}
        return visible, hidden

    def test_scoped_state_and_headers_do_not_publish_other_note_tasks_or_stored_projects(self):
        visible, hidden = self.scoped()
        self.assertEqual([visible], self.plan.state()["tasks"])
        self.assertEqual("Shown project", self.plan.state()["projects"][0]["n"])
        import base64
        data = json.loads(base64.b64decode(self.plan.headers()["X-Plan"]))
        self.assertEqual(["Desk task"], data["done"])
        self.assertEqual([["Shown project", "idea"]], data["projects"])
        self.assertEqual([visible, hidden], self.read()["tasks"])
        self.assertEqual(self.saved["projects"], self.read()["projects"])

    def test_clear_done_removes_only_visible_done_ids(self):
        visible, hidden = self.scoped()
        self.assertTrue(self.plan.clear_done())
        self.assertEqual([hidden], self.read()["tasks"])

    def test_clear_done_uses_document_completion_even_when_legacy_cache_is_behind(self):
        visible, hidden = self.scoped()
        self.plan.tasks[0]["done"] = False
        self.assertTrue(self.plan.clear_done())
        self.assertEqual([hidden], self.read()["tasks"])

    def test_task_actions_cannot_target_hidden_note_id_or_matching_text(self):
        visible, hidden = self.scoped()
        self.assertFalse(self.plan.finish_task("", False, task_id="work"))
        self.assertFalse(self.plan.remove_task("Work task"))
        self.assertEqual([visible, hidden], self.read()["tasks"])

    def test_project_changes_use_document_callback_without_mutating_backing_projects(self):
        self.scoped()
        changed = []
        self.plan.edit_project = lambda name, stage: changed.append((name, stage)) or True
        self.assertTrue(self.plan.set_project("Shown project", "testing"))
        self.assertTrue(self.plan.remove_project("Shown project"))
        self.assertEqual([("Shown project", "testing"), ("Shown project", None)], changed)
        self.assertEqual(self.saved["projects"], self.read()["projects"])

    def test_scoped_add_uses_selected_note_identity_and_unicode(self):
        self.scoped()
        self.assertTrue(self.plan.add_task("café 🦀"))
        added = self.plan.tasks[-1]
        self.assertEqual("eeeeeeee-0000-4000-8000-000000000001", added.get("noteId"))
        self.assertEqual("café 🦀", added["t"])
        self.assertIn(added, self.plan.visible_tasks())

    def test_failed_task_mutation_rolls_back_memory_and_disk(self):
        visible, hidden = self.scoped()
        before = self.read()
        with patch.object(self.plan.os, "rename", side_effect=OSError(5, "disk error")):
            for action in (lambda: self.plan.add_task("New"),
                           lambda: self.plan.finish_task("", False, "desk"),
                           lambda: self.plan.remove_task("", "desk"), self.plan.clear_done):
                with self.assertRaises(OSError):
                    action()
                self.assertEqual(before["tasks"], self.plan.tasks)
                self.assertEqual(before, self.read())

    def test_local_completion_keeps_latest_document_text_until_note_bridge_ack(self):
        self.scoped()
        self.plan.view_data = lambda: {"tasks": [{"t": "Edited on phone", "done": False, "id": "desk", "noteId": "eeeeeeee-0000-4000-8000-000000000001"}],
                                       "projects": [], "note_id": "eeeeeeee-0000-4000-8000-000000000001"}
        self.assertTrue(self.plan.finish_task("", True, "desk"))
        self.assertEqual("Edited on phone", self.plan.visible_tasks()[0]["t"])
        self.assertTrue(self.plan.visible_tasks()[0]["done"])

    def test_archived_document_blocks_add(self):
        self.scoped()
        self.plan.view_data = lambda: {"tasks": [], "projects": [], "note_id": "eeeeeeee-0000-4000-8000-000000000001", "editable": False}
        before = self.read()
        self.assertFalse(self.plan.add_task("Do not alter archive"))
        self.assertEqual(before, self.read())


if __name__ == "__main__":
    unittest.main()
