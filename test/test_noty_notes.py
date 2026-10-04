"""Desk Pal document projection, offline edits, and explicitly requested note display."""
import ast
import copy
import importlib
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
    import noty_notes as notes
except ImportError:
    notes = None
sys.path.remove(BOARD)

DESK = "eeeeeeee-0000-4000-8000-000000000001"
WORK = "eeeeeeee-0000-4000-8000-000000000002"
TASK = "ffffffff-0000-4000-8000-000000000001"


def document(note_id=DESK, **changes):
    value = {"id": note_id, "title": "Desk Pal", "body": "# to-do\n- [ ] Keep café 🦀\n# idea\n- New project\n# building\n# testing\n# shift\n",
             "archived": False, "deleted": False, "version": 1, "taskIds": [TASK]}
    value.update(changes)
    return value


def response(*docs, **changes):
    value = {"notes": copy.deepcopy(list(docs)), "deskPalId": DESK, "conflicts": []}
    value.update(changes)
    return value


class NoteTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(notes, "Board document sync is not implemented")
        sys.path.insert(0, BOARD)
        modules = {name: types.ModuleType(name) for name in ("dashboard", "font5", "room", "schedule")}
        modules["dashboard"].ascii = str
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()

    def tearDown(self):
        self.modules.stop()
        sys.modules.pop("plan", None)
        sys.path.remove(BOARD)

    def ledger(self, *docs):
        ledger = notes.Ledger()
        ledger.receive(response(*(docs or (document(),))), [])
        return ledger

    def test_sections_accept_plain_bullets_checkboxes_and_shift_alias(self):
        body = "Not a task\n# to-do\nPlain café 🦀\n- bullet\n* [X] finished\n# idea\n- idea name\n# building\nBuild name\n# testing\n+ test name\n# shift\n- shipped name\n# unrelated\nNot a task either"
        projected = notes.project(document(body=body, taskIds=[TASK, WORK, DESK]))
        self.assertEqual(["Plain café 🦀", "bullet", "finished"], [t["t"] for t in projected["tasks"]])
        self.assertEqual([False, False, True], [t["done"] for t in projected["tasks"]])
        self.assertEqual([TASK, WORK, DESK], [t["id"] for t in projected["tasks"]])
        self.assertEqual(["idea", "building", "testing", "shipped"], [p["s"] for p in projected["projects"]])

    def test_native_checkbox_migration_keeps_three_original_ids_text_and_flags(self):
        body = ("# to-do\n☑ Original completed one\n☐ Original open two\n☑ Original completed three\n\n"
                "# idea\n- Idea one\n- Idea two\n# building\n- Build one\n- Build two\n"
                "# testing\n- Test one\n- Test two\n# shift\n- Shipped one\n- Shipped two\n")
        original = document(body=body, taskIds=[TASK, WORK, DESK])
        projected = notes.project(original)
        self.assertEqual([TASK, WORK, DESK], [task["id"] for task in projected["tasks"]])
        self.assertEqual([True, False, True], [task["done"] for task in projected["tasks"]])
        self.assertEqual(["Original completed one", "Original open two", "Original completed three"],
                         [task["t"] for task in projected["tasks"]])
        self.assertEqual(8, len(projected["projects"]))
        self.assertEqual(body, original["body"])

    def test_native_and_markdown_checkboxes_have_equivalent_text_and_completion(self):
        body = "# to-do\n☐café 🦀\n☑ done café\n- ☐ bullet native\n- [x] markdown done\n"
        ids = [TASK, WORK, DESK, "ffffffff-0000-4000-8000-000000000004"]
        projected = notes.project(document(body=body, taskIds=ids))
        self.assertEqual(["café 🦀", "done café", "bullet native", "markdown done"],
                         [task["t"] for task in projected["tasks"]])
        self.assertEqual([False, True, False, True], [task["done"] for task in projected["tasks"]])

    def test_project_native_checkbox_name_moves_without_rewriting_glyph_style(self):
        original = document(body="# to-do\n☑ Completed original\n# idea\n☐ café 🦀 project\n# testing\n")
        ledger = self.ledger(original)
        self.assertEqual([{"n": "café 🦀 project", "s": "idea"}], ledger.view()["projects"])
        self.assertTrue(ledger.set_project("café 🦀 project", "testing"))
        body = ledger.get(DESK)["body"]
        self.assertIn("# testing\n☐ café 🦀 project\n", body)
        self.assertIn("# to-do\n☑ Completed original\n", body)
        self.assertEqual([True], [task["done"] for task in ledger.view()["tasks"]])

    def test_code_fence_and_unknown_heading_are_not_pipeline_content(self):
        body = "# to-do\n- real\n```\n# idea\n- code\n```\n# elsewhere\n- ignore\n# testing\nReal test"
        value = notes.project(document(body=body, taskIds=[TASK]))
        self.assertEqual(["real"], [t["t"] for t in value["tasks"]])
        self.assertEqual([{"n": "Real test", "s": "testing"}], value["projects"])

    def test_hashtag_task_is_preserved_and_nested_heading_ends_section(self):
        value = notes.project(document(body="# to-do\n#hashtag task\n## details\nnot todo\n# idea\nProject", taskIds=[TASK]))
        self.assertEqual(["#hashtag task"], [task["t"] for task in value["tasks"]])
        self.assertEqual([{"n": "Project", "s": "idea"}], value["projects"])

    def test_archived_selected_note_does_not_overlay_pending_tasks(self):
        ledger = self.ledger(document(archived=True))
        pending = [{"id": TASK, "noteId": DESK, "text": "Keep café 🦀", "completed": True, "deleted": False, "listTitle": "Desk Pal"}]
        with patch.object(notes, "_ledger", ledger), patch.object(notes.noty_sync, "pending_tasks", return_value=pending):
            self.assertEqual([], notes.view_data()["tasks"])
            self.assertFalse(notes.view_data()["editable"])

    def test_selected_identity_filters_other_note_even_after_title_rename(self):
        ledger = self.ledger(document(title="Renamed by me"), document(WORK, title="Work", body="- [ ] hidden"))
        self.assertEqual(["Keep café 🦀"], [t["t"] for t in ledger.view()["tasks"]])
        self.assertEqual("Work", ledger.get(WORK)["title"])

    def test_deleted_selected_note_falls_back_to_live_desk_pal_note(self):
        ledger = self.ledger(document(deleted=True, body="# to-do\n- [ ] old\n"),
                             document(WORK, body="# to-do\n- [ ] new\n# idea\n- Robot\n", taskIds=[]))
        self.assertEqual(["new"], [t["t"] for t in ledger.view()["tasks"]])
        self.assertEqual([{"n": "Robot", "s": "idea"}], ledger.view()["projects"])
        with patch.object(notes, "_ledger", ledger), patch.object(notes.noty_sync, "pending_tasks", return_value=[]):
            self.assertEqual(WORK, notes.view_data()["note_id"])

    def test_project_move_preserves_raw_line_unicode_and_other_sections(self):
        original = document(body="preamble\n# to-do\n- [ ] Keep café 🦀\n# idea\n  * café  🦀 project\n# building\n- Existing\n# testing\n# shift\n")
        ledger = self.ledger(original)
        self.assertTrue(ledger.set_project("café  🦀 project", "testing"))
        pending = ledger.prepare()
        self.assertEqual(original, pending[0]["base"])
        changed = pending[0]["note"]["body"]
        self.assertIn("# testing\n  * café  🦀 project\n", changed)
        self.assertIn("preamble\n# to-do\n- [ ] Keep café 🦀\n", changed)
        self.assertTrue(ledger.set_project("café  🦀 project", "idea"))
        self.assertIn("# idea\n  * café  🦀 project\n", ledger.get(DESK)["body"])
        self.assertEqual(original["taskIds"], ledger.get(DESK)["taskIds"])

    def test_pending_draft_and_frozen_request_survive_restart_and_inflight_edit(self):
        ledger = self.ledger()
        ledger.set_project("New project", "building")
        sent = ledger.prepare()
        ledger.set_project("New project", "testing")
        restored = notes.Ledger(json.loads(json.dumps(ledger.data())))
        self.assertEqual(sent, restored.prepare())
        accepted = dict(sent[0]["note"], version=2)
        restored.receive(response(accepted), sent)
        self.assertEqual("testing", restored.view()["projects"][0]["s"])
        self.assertEqual(accepted, restored.prepare()[0]["base"])

    def test_conflict_keeps_both_local_draft_and_remote_text(self):
        ledger = self.ledger()
        ledger.set_project("New project", "building")
        sent = ledger.prepare()
        server = document(body=document()["body"].replace("- New project", "- Remote project"), version=2)
        ledger.receive(response(server, conflicts=[{"id": DESK, "note": server}]), sent)
        self.assertIn("New project", ledger.get(DESK)["body"])
        self.assertEqual(server, ledger.conflicts[DESK])
        self.assertEqual([], ledger.prepare())
        self.assertFalse(ledger.set_project("Another", "testing"))

    def test_bad_or_missing_remote_doc_preserves_all_cached_content(self):
        ledger = self.ledger()
        before = ledger.data()
        for invalid in (response(document(taskIds=["invalid"])), response(), response(document(version=0))):
            with self.assertRaises(ValueError):
                ledger.receive(invalid, [])
            self.assertEqual(before, ledger.data())

    def test_project_move_retains_crlf_and_does_not_change_other_note(self):
        original = document(body="# to-do\r\n- [ ] keep\r\n# idea\r\n  * café  🦀\r\n# testing\r\n")
        work = document(WORK, title="Work", body="Leave  all\r\nlines unchanged", taskIds=[])
        ledger = self.ledger(original, work)
        self.assertTrue(ledger.set_project("café  🦀", "testing"))
        self.assertIn("# testing\r\n  * café  🦀\r\n", ledger.get(DESK)["body"])
        self.assertEqual(work, ledger.get(WORK))

    def test_large_pending_note_reports_capacity_and_keeps_draft(self):
        ledger = self.ledger(document(body="# idea\n" + "a" * 64000, taskIds=[]))
        self.assertTrue(ledger.set_project("New café", "testing"))
        before = ledger.data()
        with patch.object(notes.noty_sync, "MAX_BYTES", 1024):
            with self.assertRaises(ValueError):
                ledger.prepare()
        self.assertEqual(before, ledger.data())

    def test_pending_tasks_overlay_only_selected_note_without_modifying_cache(self):
        ledger = self.ledger()
        pending = [{"id": TASK, "noteId": DESK, "text": "Keep café 🦀", "completed": True, "deleted": False, "listTitle": "Desk Pal"},
                   {"id": WORK, "noteId": WORK, "text": "Hidden work", "completed": False, "deleted": False, "listTitle": "Work"}]
        with patch.object(notes, "_ledger", ledger), patch.object(notes.noty_sync, "pending_tasks", return_value=pending):
            visible = notes.view_data()
        self.assertEqual(1, len(visible["tasks"]))
        self.assertTrue(visible["tasks"][0]["done"])
        self.assertFalse(notes.project(ledger.get(DESK))["tasks"][0]["done"])

    def test_worker_failure_does_not_log_private_note_or_token(self):
        with patch.object(notes.noty_sync, "_request", side_effect=OSError("secret-token private note text")):
            notes._worker({"token": "secret-token"}, [])
        self.assertEqual("Note sync unavailable; retrying", notes._result["error"])
        self.assertNotIn("secret-token", json.dumps(notes._result))
        notes._result = None

    def test_network_result_applies_on_tick_and_nudges_legacy_import_for_new_task_id(self):
        with tempfile.TemporaryDirectory() as folder:
            saved = self.ledger()
            native = importlib.import_module("plan")
            native.tasks[:] = []
            result = {"response": response(document()), "sent": []}
            with patch.object(notes, "STATE_FILE", os.path.join(folder, "notes.json")), \
                    patch.object(notes, "_ledger", saved), patch.object(notes, "_settings", {"token": "private"}), \
                    patch.object(notes, "_result", result), patch.object(notes, "_blocked", False), \
                    patch.object(notes, "_busy", True), patch.object(notes, "_last_attempt", 100), \
                    patch.object(notes, "_force", False), patch.object(notes.noty_sync, "_now", return_value=101), \
                    patch.object(notes.noty_sync, "refresh_now") as refresh:
                notes.tick(lambda: False)
                self.assertIsNone(notes._result)
                self.assertFalse(notes._busy)
                self.assertEqual(document(), notes._ledger.get(DESK))
                refresh.assert_called_once()

    def test_retry_uses_frozen_body_after_network_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = self.ledger()
            ledger.set_project("New project", "building")
            sent = ledger.prepare()
            ledger.set_project("New project", "testing")
            scheduled = []
            with patch.object(notes, "STATE_FILE", os.path.join(folder, "notes.json")), \
                    patch.object(notes, "_ledger", ledger), patch.object(notes, "_settings", {"token": "private"}), \
                    patch.object(notes, "_result", {"error": "Note sync unavailable; retrying", "sent": sent}), \
                    patch.object(notes, "_blocked", False), patch.object(notes, "_busy", True), \
                    patch.object(notes, "_last_attempt", 100), patch.object(notes, "_force", False), \
                    patch.object(notes.noty_sync, "_now", return_value=20000), \
                    patch.object(notes.noty_sync, "info", return_value={"busy": False}), \
                    patch.object(notes._thread, "stack_size"), \
                    patch.object(notes._thread, "start_new_thread", side_effect=lambda func, args: scheduled.append(args)):
                notes.tick(lambda: True)
                self.assertEqual(sent, scheduled[0][1])
                self.assertEqual("testing", notes._ledger.view()["projects"][0]["s"])

    def test_saved_state_recovers_backup_without_replacing_invalid_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            primary = os.path.join(folder, "notes.json")
            saved = self.ledger().data()
            with open(primary, "w") as target:
                target.write("{partial")
            with open(primary + ".bak", "w") as target:
                json.dump(saved, target)
            with patch.object(notes, "STATE_FILE", primary):
                self.assertEqual(saved, notes._load_state())
            with open(primary) as source:
                self.assertEqual("{partial", source.read())

    def test_atomic_save_failure_retains_previous_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(notes, "STATE_FILE", os.path.join(folder, "notes.json")):
                saved = self.ledger().data()
                notes._save_state(saved)
                newer = self.ledger().data()
                newer["entries"][DESK]["note"]["title"] = "Newer"
                with patch.object(notes.os, "rename", side_effect=OSError(5, "disk error")):
                    with self.assertRaises(OSError):
                        notes._save_state(newer)
                self.assertEqual(saved, notes._load_state())

    def test_named_viewer_opens_only_exact_cached_identity_and_wraps_display_only(self):
        ledger = self.ledger(document(), document(WORK, title="Work café", body="line one\n" + "🦀 café " * 250, taskIds=[]))
        with patch.object(notes, "_ledger", ledger):
            self.assertFalse(notes.show_note("Work"))
            self.assertTrue(notes.show_note(WORK))
            self.assertEqual(WORK, notes.viewing_id)
            self.assertGreater(len(notes.viewer_pages(lambda text: text.replace("🦀", "?"))), 1)
            self.assertIn("🦀", ledger.get(WORK)["body"])
            notes.next_page()
            self.assertEqual(1, notes.page)
            self.assertFalse(notes.show_note("not-a-note"))
            self.assertEqual(WORK, notes.viewing_id)

    def test_run_requires_explicit_show_note_command(self):
        with open(os.path.join(BOARD, "main.py")) as source:
            tree = ast.parse(source.read())
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
        shown, looked_up = [], []
        viewer = types.SimpleNamespace(show_note=lambda note_id: looked_up.append(note_id) or note_id == WORK)
        env = {"noty_notes": viewer, "show": shown.append, "SCREENS": ("plan",), "PLAN_DO": {}}
        exec(compile(ast.Module(body=[run], type_ignores=[]), "main.py", "exec"), env)
        self.assertTrue(env["run"]({"do": "show_note", "note_id": WORK}))
        self.assertEqual(["note"], shown)
        self.assertFalse(env["run"]({"do": "show_note", "note_id": "Work"}))
        self.assertEqual(["note"], shown)
        self.assertIsNone(env["run"]({"do": "answer_note_question", "note_id": WORK}))
        self.assertEqual(["note"], shown)


if __name__ == "__main__":
    unittest.main()
