"""Only temporary synthetic notes: personal actions are not fact verification."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from app.models import TaskRecord
from app.personal_review_records import review_key
from app.storage import save_task


class PersonalReviewTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.tasks = self.root / "tasks"
        self.tasks.mkdir()
        for module in ("storage", "library", "knowledge", "study", "personal_notes", "routers.notes", "routers.library"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        for module in ("storage", "library"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.tasks))
        self.stack.enter_context(patch("app.storage.ensure_dirs", return_value=None))
        self.stack.enter_context(patch("app.study.ensure_dirs", return_value=None))
        self.client = self.stack.enter_context(TestClient(app, raise_server_exceptions=False))
        self.addCleanup(self.stack.close)
        self.task = self.make_task("synthetic")
        self.url = "/api/tasks/editions/task/synthetic/personal-review"
        self.counter = 0

    def make_task(self, source_id, parent=""):
        root = self.tasks / source_id
        root.mkdir()
        (root / "note.md").write_text("# Synthetic\n\nA note to check.\n", encoding="utf-8")
        (root / "transcript.json").write_text(json.dumps({"segments": [{"start": 1, "end": 3, "text": "A source caption."}]}), encoding="utf-8")
        (root / "grids").mkdir()
        (root / "grids/a.jpg").write_bytes(b"synthetic image")
        (root / "visual.json").write_text(json.dumps({"windows": [{"id": "1", "start": 1, "end": 3, "grid_path": str(root / "grids/a.jpg")}]}), encoding="utf-8")
        record = TaskRecord(id=source_id, title="Synthetic", source_type="local", status="success", source_task_id=parent,
            note_path=str(root / "note.md"), transcript_path=str(root / "transcript.json"), visual_index_path=str(root / "visual.json"),
            created_at="2026-10-13T00:00:00+00:00", updated_at="2026-10-13T00:00:00+00:00")
        save_task(record)
        return record

    def get(self, url=None):
        result = self.client.get(url or self.url)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def body(self, current, action="mark", request_id=None):
        self.counter += 1
        return {"action": action, "expected_context_revision": current["context_revision"] or "",
            "expected_review_revision": current["review_revision"], "request_id": request_id or f"request-{self.counter}"}

    def change(self, current=None, action="mark", url=None):
        result = self.client.post(url or self.url, json=self.body(current or self.get(url), action))
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def review_path(self, source_id="synthetic"):
        return self.root / "personal-reviews" / f"{review_key('task', source_id)}.json"

    def test_explicit_mark_revoke_durable_without_changing_sources(self):
        before = {p: p.read_bytes() for p in (self.tasks / "synthetic").rglob("*") if p.is_file()}
        current = self.get()
        self.assertEqual(current["status"], "unmarked")
        self.assertEqual(current["source_scope"], "available_sources")
        marked = self.change(current)
        self.assertEqual(marked["status"], "current")
        self.assertIn("不证明事实正确", marked["scope_detail"])
        self.assertEqual(self.get()["review_revision"], marked["review_revision"])
        self.assertEqual(self.change(marked, "revoke")["status"], "revoked")
        self.assertTrue(self.review_path().exists())
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_replay_does_not_revive_revoked_record_or_accept_changed_payload(self):
        original = self.body(self.get(), request_id="stable-retry")
        marked = self.client.post(self.url, json=original).json()
        revoked = self.change(marked, "revoke")
        replay = self.client.post(self.url, json=original)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["replayed"])
        self.assertEqual(replay.json()["status"], "revoked")
        self.assertEqual(replay.json()["review_revision"], revoked["review_revision"])
        self.assertEqual(self.client.post(self.url, json={**original, "action": "revoke"}).status_code, 409)

    def test_two_tabs_and_concurrent_mark_have_exactly_one_winner(self):
        current = self.get()
        requests = [self.body(current), self.body(current)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda body: self.client.post(self.url, json=body).status_code, requests))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(self.client.post(self.url, json=self.body(current, "revoke")).status_code, 409)

    def test_edit_and_return_to_old_text_stays_stale(self):
        self.change()
        endpoint = self.url.removesuffix("/personal-review")
        original = self.client.get(endpoint).json()
        changed = self.client.put(endpoint, json={"text": original["text"] + "\nChanged", "revision": original["revision"]}).json()
        self.assertEqual(self.get()["status"], "stale")
        self.client.put(endpoint, json={"text": original["text"], "revision": changed["revision"]})
        self.assertEqual(self.get()["status"], "stale")
        self.assertEqual(self.change()["status"], "current")

    def test_each_source_version_change_invalidates(self):
        cases = ("caption", "image", "generation", "same_text_regeneration")
        for case in cases:
            with self.subTest(case=case):
                self.change()
                if case == "caption":
                    Path(self.task.transcript_path).write_text('{"segments":[{"text":"Changed source"}]}')
                elif case == "image":
                    (self.tasks / "synthetic/grids/a.jpg").write_bytes(b"changed image")
                elif case == "generation":
                    self.task.control_generation = "new-generation"; save_task(self.task)
                else:
                    original = Path(self.task.note_path).read_bytes()
                    replacement = Path(self.task.note_path).with_suffix(".new")
                    replacement.write_bytes(original); replacement.replace(self.task.note_path)
                self.assertEqual(self.get()["status"], "stale")

    def test_processing_cannot_be_marked_or_keep_current_badge(self):
        current = self.change()
        self.task.status = "running"; save_task(self.task)
        result = self.get()
        self.assertFalse(result["can_mark"])
        self.assertEqual(result["status"], "stale")
        self.assertEqual(self.client.post(self.url, json=self.body(result)).status_code, 409)
        self.assertEqual(self.change(current, "revoke")["status"], "revoked")

    def test_missing_sources_scope_is_reading_only_and_old_mark_stale(self):
        self.change()
        Path(self.task.transcript_path).unlink()
        current = self.get()
        self.assertEqual(current["status"], "stale")
        self.assertEqual(current["source_scope"], "reading_only")
        self.assertIn("不表示来源已证实", current["scope_detail"])
        self.assertEqual(self.change(current)["status"], "current")

    def test_corrupt_edition_blocks_mark_but_not_revoke_and_preserves_bytes(self):
        self.change()
        path = self.root / "user-editions" / (review_key("task", "synthetic") + ".json")
        path.parent.mkdir(); original = b'{"text":"unfinished'; path.write_bytes(original)
        current = self.get()
        self.assertEqual(current["status"], "stale")
        self.assertFalse(current["can_mark"])
        self.assertEqual(self.change(current, "revoke")["status"], "revoked")
        self.assertEqual(path.read_bytes(), original)

    def test_same_family_does_not_inherit_review(self):
        self.change()
        self.make_task("child", parent="synthetic")
        self.assertEqual(self.get("/api/tasks/editions/task/child/personal-review")["status"], "unmarked")

    def test_changed_between_snapshot_reads_rejects_before_write(self):
        from app.routers.notes import _personal_review_context
        context = _personal_review_context("task", "synthetic")
        with patch("app.routers.notes._personal_review_context", side_effect=[context, {**context, "context_revision": "a" * 64}]):
            result = self.client.post(self.url, json=self.body(self.get_context_absent(context)))
        self.assertEqual(result.status_code, 409)
        self.assertFalse(self.review_path().exists())

    def get_context_absent(self, context):
        from app.personal_reviews import ABSENT_REVISION
        return {**context, "review_revision": ABSENT_REVISION}

    def test_client_cannot_supply_identity_verification_or_timestamp(self):
        current = self.get()
        for field in ("actor", "verified", "checked_at", "status"):
            self.assertEqual(self.client.post(self.url, json={**self.body(current), field: "forged"}).status_code, 422)
        self.assertFalse(self.review_path().exists())

    def test_explicit_review_api_contract_requires_both_revisions_and_request_id(self):
        schema = app.openapi()
        path = schema["paths"]["/api/tasks/editions/{kind}/{source_id}/personal-review"]
        self.assertEqual(set(path), {"get", "post"})
        request = schema["components"]["schemas"]["PersonalReviewRequest"]
        self.assertEqual(set(request["required"]), {"action", "expected_context_revision", "expected_review_revision", "request_id"})
        self.assertEqual(set(request["properties"]), set(request["required"]))
        self.assertFalse(request["additionalProperties"])
        self.assertEqual(request["properties"]["action"]["enum"], ["mark", "revoke"])

    def test_backup_import_pending_local_revocation_wins_and_v1_remains_usable(self):
        marked = self.change()
        payload = self.client.get("/api/study/backup").json()
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(len(payload["personal"]["personal_reviews"]), 1)
        self.change(marked, "revoke")
        response = self.client.post("/api/study/backup/restore", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.get()["status"], "revoked")
        self.review_path().unlink()  # Synthetic empty destination only.
        response = self.client.post("/api/study/backup/restore", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["merge"]["restored_personal_reviews"], 1)
        self.assertEqual(self.get()["status"], "imported")
        self.assertEqual(json.loads(self.review_path().read_text())["receipts"], [])
        self.assertEqual(self.change()["status"], "current")
        legacy = copy.deepcopy(payload); legacy["schema_version"] = 1
        legacy["personal"].pop("personal_reviews")
        self.assertEqual(self.client.post("/api/study/backup/restore", json=legacy).status_code, 200)
        self.assertEqual(self.get()["status"], "current")

    def test_invalid_or_future_record_preserves_all_restore_destinations(self):
        self.change()
        payload = self.client.get("/api/study/backup").json()
        original = self.review_path().read_bytes()
        malformed = [b'{"unfinished":', b'{"schema_version":999}', b'{"schema_version":1,"schema_version":1}']
        for raw in malformed:
            with self.subTest(raw=raw):
                self.review_path().write_bytes(raw)
                self.assertEqual(self.client.post("/api/study/backup/restore", json=payload).status_code, 422)
                self.assertEqual(self.review_path().read_bytes(), raw)
                self.assertNotEqual(self.client.get("/api/study/backup").status_code, 200)
        self.review_path().write_bytes(original)
        for variant in ("schema", "duplicate", "timestamp", "foreign_key", "oversized", "unknown"):
            changed = copy.deepcopy(payload)
            entry = changed["personal"]["personal_reviews"][0]
            if variant == "schema": changed["schema_version"] = 999
            elif variant == "duplicate": changed["personal"]["personal_reviews"].append(copy.deepcopy(entry))
            elif variant == "timestamp": entry["value"]["checked_at"] = "not a date"
            elif variant == "foreign_key": entry["value"]["source_id"] = "different"
            elif variant == "oversized": entry["value"]["receipts"] *= 33
            else: entry["value"]["actor"] = "trusted-self"
            result = self.client.post("/api/study/backup/restore", json=changed)
            self.assertEqual(result.status_code, 422, (variant, result.text))
            self.assertEqual(self.review_path().read_bytes(), original)

    def test_restore_write_failure_rolls_back_earlier_personal_changes(self):
        self.change()
        payload = self.client.get("/api/study/backup").json()
        self.review_path().unlink()
        payload["personal"]["annotations"] = [{"key": "task-new", "items": [{"id": "one", "text": "Synthetic", "quote": "", "anchor": {}}]}]
        from app.storage import atomic_write_text
        def failing(path, content):
            atomic_write_text(path, content)
            if path.parent.name == "personal-reviews":
                raise OSError("Synthetic post-write failure")
        with patch("app.personal_notes.atomic_write_text", side_effect=failing):
            result = self.client.post("/api/study/backup/restore", json=payload)
        self.assertNotEqual(result.status_code, 200)
        self.assertFalse(self.review_path().exists())
        self.assertFalse((self.root / "personal-notes/task-new.json").exists())

    def test_corrupt_review_never_overwritten_or_exported(self):
        self.change()
        original = b'{"schema_version":999,"retain":"mine"}'
        self.review_path().write_bytes(original)
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertEqual(self.review_path().read_bytes(), original)
        self.assertNotEqual(self.client.get("/api/study/backup").status_code, 200)

    def test_material_source_content_change_stales_even_when_personal_edition_unchanged(self):
        from app.library import import_document_material, material_source_path
        material = import_document_material("synthetic.md", b"# Original\n\nSource wording.", "text/markdown")
        source_id = material["material_id"]
        endpoint = f"/api/tasks/editions/material/{source_id}"
        edition = self.client.get(endpoint).json()
        result = self.client.put(endpoint, json={"text": "# My edition\n\nKeep my words.", "revision": edition["revision"]})
        self.assertEqual(result.status_code, 200, result.text)
        url = endpoint + "/personal-review"
        self.change(url=url)
        original_export = self.client.get(endpoint + "/exports/markdown").content
        material_source_path(source_id).write_bytes(b"# Original\n\nNew source wording.")
        self.assertEqual(self.get(url)["status"], "stale")
        self.assertEqual(self.client.get(endpoint + "/exports/markdown").content, original_export)

    def test_page_text_source_is_bound_even_without_transcript_or_visual_index(self):
        from app.claims import build_claim_evidence_map
        from app.models import TranscriptResult
        self.task.source_type = "page_text"; self.task.mode = "page_text"
        self.task.transcript_path = ""; self.task.visual_index_path = ""; save_task(self.task)
        evidence = [{"evidence_id": "task-synthetic-page-text", "source_type": "webpage",
            "locator": "captured page text", "text": "Original captured page text."}]
        mapped = build_claim_evidence_map("synthetic", "Synthetic", Path(self.task.note_path).read_text(), TranscriptResult(), document_evidence=evidence)
        path = self.tasks / "synthetic/claim_evidence_map.json"
        path.write_text(json.dumps(mapped))
        current = self.get()
        self.assertEqual(current["source_scope"], "available_sources")
        self.assertIn("已保存的页面原文", current["source_labels"])
        self.change(current)
        mapped["evidence"][0]["text"] = "Changed page text"
        path.write_text(json.dumps(mapped))
        self.assertEqual(self.get()["status"], "stale")

    def test_pending_restore_blocks_review_write_and_preserves_receipt(self):
        current = self.change(); original = self.review_path().read_bytes()
        pending = self.root / "personal-state/restore-pending"; pending.mkdir()
        result = self.client.post(self.url, json=self.body(current, "revoke"))
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["detail"]["code"], "personal_restore_recovery_required")
        self.assertEqual(self.review_path().read_bytes(), original)

    def test_symlinked_review_or_source_does_not_expose_or_mutate_referent(self):
        self.change(); path = self.review_path()
        outside = self.root / "unrelated.json"; original = b'{"retain":"private synthetic"}'
        outside.write_bytes(original); path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("This platform cannot create test symlinks")
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertEqual(outside.read_bytes(), original)
        path.unlink()
        transcript = Path(self.task.transcript_path); transcript.unlink(); transcript.symlink_to(outside)
        result = self.get()
        self.assertEqual(result["source_scope"], "reading_only")
        self.assertNotIn("private synthetic", json.dumps(result))

    def test_generated_note_symlink_is_not_read_or_given_a_current_badge(self):
        self.change()
        outside = self.root / "other.md"; outside.write_text("Unrelated private synthetic text")
        path = Path(self.task.note_path); path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("This platform cannot create test symlinks")
        with patch("app.task_artifacts.decode_task_note", side_effect=AssertionError("Unsafe source must not be decoded")) as decoder:
            result = self.get()
        decoder.assert_not_called()
        self.assertFalse(result["can_mark"])
        self.assertEqual(result["status"], "stale")
        self.assertEqual(self.client.post(self.url, json=self.body(result)).status_code, 409)

    def test_oversize_generated_note_rejected_before_decode(self):
        from app.personal_anchors import MAX_ARTIFACT_BYTES
        with Path(self.task.note_path).open("wb") as stream:
            stream.truncate(MAX_ARTIFACT_BYTES + 1)
        with patch("app.task_artifacts.decode_task_note", side_effect=AssertionError("Oversize source must not be decoded")) as decoder:
            result = self.get()
        decoder.assert_not_called()
        self.assertFalse(result["can_mark"])

    def test_valid_saved_edition_can_record_reading_with_missing_original(self):
        endpoint = self.url.removesuffix("/personal-review")
        original = self.client.get(endpoint).json()
        self.client.put(endpoint, json={"text": "My preserved edition.", "revision": original["revision"]})
        Path(self.task.note_path).unlink()
        with patch("app.task_artifacts.read_task_note", side_effect=AssertionError("Saved edition supplies note")):
            current = self.get()
        self.assertTrue(current["can_mark"])
        self.assertEqual(current["source_scope"], "reading_only")
        self.assertEqual(self.change(current)["status"], "current")

    def test_visual_window_missing_image_is_reading_only(self):
        Path(self.task.visual_index_path).write_text('{"windows":[{"id":"1","start":1,"end":3}]}')
        self.assertEqual(self.get()["source_scope"], "reading_only")

    def test_malformed_or_empty_declared_transcript_is_not_available_source(self):
        self.task.visual_index_path = ""; save_task(self.task)
        for payload in ({}, {"segments": "corrupt"}, {"segments": []},
                        {"segments": [{"text": "", "start": 1, "end": 2}]},
                        {"segments": [{"text": "Wrong bounds", "start": 3, "end": 2}]},
                        {"segments": [{"text": "Wrong types", "start": True, "end": 2}]},
                        {"segments": [{"text": "Overflow", "start": 10 ** 1000, "end": 10 ** 1001}]}):
            with self.subTest(payload=payload):
                Path(self.task.transcript_path).write_text(json.dumps(payload))
                current = self.get()
                self.assertEqual(current["source_scope"], "reading_only")
                self.assertNotIn("字幕原文", current["source_labels"])

    def test_same_text_restored_edition_gets_fresh_local_generation(self):
        self.change()
        payload = self.client.get("/api/study/backup").json()
        endpoint = self.url.removesuffix("/personal-review")
        current = self.client.get(endpoint).json()
        payload["personal"]["editions"] = [{"key": review_key("task", "synthetic"),
            "value": {"text": current["text"], "revision": current["revision"], "edited": True}}]
        response = self.client.post("/api/study/backup/restore", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        first_id = self.client.get(endpoint).json()["write_id"]
        self.assertEqual(self.get()["status"], "stale")
        self.change()
        (self.root / "user-editions" / (review_key("task", "synthetic") + ".json")).unlink()
        self.client.post("/api/study/backup/restore", json=payload)
        self.assertNotEqual(self.client.get(endpoint).json()["write_id"], first_id)
        self.assertEqual(self.get()["status"], "stale")

    def test_deeply_nested_or_overflow_source_does_not_prevent_revocation(self):
        original = Path(self.task.transcript_path).read_bytes()
        for content in ('[' * 10_000 + ']' * 10_000,
                        json.dumps({"segments": [{"text": "Overflow", "start": 10 ** 1000, "end": 10 ** 1001}]})):
            Path(self.task.transcript_path).write_bytes(original)
            current = self.change()
            Path(self.task.transcript_path).write_text(content)
            self.assertEqual(self.get()["status"], "stale")
            self.assertEqual(self.change(current, "revoke")["status"], "revoked")


if __name__ == "__main__":
    unittest.main()
