"""Synthetic personal-layer tests: current evidence is never guessed or rewritten."""
from contextlib import ExitStack
import json
import os
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.claims import build_claim_evidence_map
from app.models import TaskRecord, TranscriptResult
from app.personal_anchors import annotation_targets, resolve_anchor, _grid_hash
from app.personal_notes import export_personal_data, list_annotations, restore_personal_data
from app.routers.personal import personal_router


class PersonalAnchorTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.tasks, self.maps = {}, {}
        for target, value in (("app.personal_notes.DATA_DIR", self.root),):
            self.stack.enter_context(patch(target, value))
        for module in ("personal_notes", "personal_anchors"):
            self.stack.enter_context(patch(f"app.{module}.get_task", side_effect=self.tasks.__getitem__))
        self.stack.enter_context(patch("app.personal_anchors.task_dir", side_effect=lambda task: self.root / task))
        self.stack.enter_context(patch("app.task_artifacts.task_dir", side_effect=lambda task: self.root / task))
        app = FastAPI()
        app.include_router(personal_router)
        self.client = TestClient(app)
        self.addCleanup(self.stack.close)
        self.make_task("first")

    def make_task(self, task_id, parent="", note="An exact generated claim.\n"):
        root = self.root / task_id
        root.mkdir(exist_ok=True)
        (root / "note.md").write_text(note, encoding="utf-8")
        transcript = {"segments": [{"start": 1, "end": 5, "text": "First overlapping caption."},
                                   {"start": 3, "end": 7, "text": "Second overlapping caption."}]}
        (root / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
        (root / "grids").mkdir(exist_ok=True)
        (root / "grids/grid.jpg").write_bytes(b"synthetic-image-bytes")
        windows = [{"id": "window-1", "start": 1, "end": 7, "summary": "A synthetic visual.",
                    "grid_path": str(root / "grids/grid.jpg")}]
        (root / "visual_index.json").write_text(json.dumps({"windows": windows}), encoding="utf-8")
        task = TaskRecord(id=task_id, title="Synthetic", source_type="local", source_task_id=parent,
                          note_path=str(root / "note.md"), transcript_path=str(root / "transcript.json"),
                          visual_index_path=str(root / "visual_index.json"), created_at="2026-10-09", updated_at="2026-10-09")
        self.tasks[task_id] = task
        self.maps[task_id] = build_claim_evidence_map(task_id, task.title, note, TranscriptResult.model_validate(transcript), windows)
        (root / "claim_evidence_map.json").write_text(json.dumps(self.maps[task_id]), encoding="utf-8")
        return task

    def targets(self, task="first", kind=None):
        result = self.client.get(f"/api/personal/task/{task}/targets")
        self.assertEqual(result.status_code, 200, result.text)
        return [item["anchor"] for item in result.json()["targets"] if kind is None or item["anchor"]["kind"] == kind]

    def create(self, anchor=None, text="  我的补充 cafe\u0301 🧭\n\n", request_id=""):
        response = self.client.post("/api/personal/task/first", json={"text": text, "quote": "  字幕原文\n", "anchor": anchor or {}, "request_id": request_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["annotation"]

    def test_explicit_kinds_roundtrip_exact_text_backup_and_read_only_migration(self):
        anchors = self.targets()
        self.assertEqual({a["kind"] for a in anchors}, {"claim", "transcript", "visual"})
        saved = [self.create(anchor) for anchor in anchors]
        path = self.root / "personal-notes/task-first.json"
        before = path.read_bytes()
        self.make_task("regenerated", "first", "# Regenerated\n\nAn exact generated claim.\n")
        migrated = list_annotations("task", "regenerated")
        self.assertTrue(all(item["anchor_status"]["resolution"] == "migrated" for item in migrated))
        self.assertEqual([a["id"] for a in migrated], [a["id"] for a in saved])
        self.assertEqual(path.read_bytes(), before)
        backup = export_personal_data()
        with patch("app.personal_notes.DATA_DIR", self.root / "restored"):
            self.assertEqual(restore_personal_data(backup)["restored_annotations"], 4)
            self.assertEqual(restore_personal_data(backup)["restored_annotations"], 0)
            restored = list_annotations("task", "first")
        self.assertEqual([(a["id"], a["text"], a["quote"], a["anchor"]) for a in restored],
                         [(a["id"], a["text"], a["quote"], a["anchor"]) for a in saved])

    def test_overlap_does_not_move_to_another_caption_and_deleted_evidence_is_orphaned(self):
        first, second = self.targets(kind="transcript")
        saved = self.create(first)
        path = Path(self.tasks["first"].transcript_path)
        content = json.loads(path.read_text())
        content["segments"].pop(0)
        path.write_text(json.dumps(content))
        status = list_annotations("task", "first")[0]["anchor_status"]
        self.assertEqual(status["resolution"], "orphaned")
        self.assertNotIn("resolved_anchor", status)
        self.assertEqual(list_annotations("task", "first")[0]["text"], saved["text"])
        path.unlink()
        self.assertEqual(self.targets(kind="transcript"), [])
        self.assertTrue(list_annotations("task", "first")[0]["anchor_status"]["stale"])

    def test_changed_visual_bytes_and_missing_grid_require_repair(self):
        self.create(self.targets(kind="visual")[0])
        grid = self.root / "first/grids/grid.jpg"
        grid.write_bytes(b"different-frames-same-name-and-window")
        self.assertTrue(list_annotations("task", "first")[0]["anchor_status"]["stale"])
        grid.unlink()
        self.assertEqual(self.targets(kind="visual"), [])

    def test_corrupt_generated_source_leaves_personal_text_visible_for_repair(self):
        saved = self.create(self.targets(kind="claim")[0])
        Path(self.tasks["first"].note_path).write_bytes(b"\xff\xfe\x00corrupt-synthetic-source")
        response = self.client.get("/api/personal/task/first")
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["annotations"][0]
        self.assertEqual(item["text"], saved["text"])
        self.assertEqual(item["id"], saved["id"])
        self.assertTrue(item["anchor_status"]["stale"])

    def test_duplicate_caption_identity_after_resegmentation_is_ambiguous(self):
        self.create(self.targets(kind="transcript")[0])
        path = Path(self.tasks["first"].transcript_path)
        content = json.loads(path.read_text())
        content["segments"].append(dict(content["segments"][0]))
        path.write_text(json.dumps(content))
        status = list_annotations("task", "first")[0]["anchor_status"]
        self.assertEqual(status["resolution"], "orphaned")
        self.assertEqual(status["reason"], "ambiguous_target")

    def test_ambiguous_identical_claims_never_rebind_on_changed_revision(self):
        self.create(self.targets(kind="claim")[0])
        self.make_task("first", note="An exact generated claim.\nAn exact generated claim.\n")
        current = list_annotations("task", "first")[0]
        self.assertEqual(current["anchor_status"]["reason"], "ambiguous_target")
        self.assertTrue(current["anchor_status"]["repairable"])
        repaired = self.client.post("/api/personal/task/first", json={"id": current["id"], "text": current["text"],
            "revision": current["revision"], "anchor": self.targets(kind="claim")[1]})
        self.assertEqual(repaired.status_code, 200, repaired.text)
        self.assertEqual(list_annotations("task", "first")[0]["anchor_status"]["resolution"], "exact")
        self.assertEqual(repaired.json()["annotation"]["quote"], current["quote"])

    def test_stale_target_and_stale_edit_rejected_without_losing_draft_or_saved_text(self):
        old = self.targets(kind="claim")[0]
        self.make_task("first", note="Changed generated claim.\n")
        response = self.client.post("/api/personal/task/first", json={"text": "My draft", "anchor": old})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(list_annotations("task", "first"), [])
        saved = self.create()
        update = {"id": saved["id"], "text": "New exact text\n ", "revision": saved["revision"]}
        first = self.client.post("/api/personal/task/first", json=update)
        retry = self.client.post("/api/personal/task/first", json=update)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        conflict = self.client.post("/api/personal/task/first", json={**update, "text": "Stale tab changes"})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(list_annotations("task", "first")[0]["text"], update["text"])

    def test_retry_is_idempotent_and_different_request_payload_is_a_conflict(self):
        anchor = self.targets(kind="transcript")[0]
        first = self.create(anchor, request_id="synthetic-retry")
        again = self.create(anchor, request_id="synthetic-retry")
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(len(list_annotations("task", "first")), 1)
        conflict = self.client.post("/api/personal/task/first", json={"text": "Different", "request_id": "synthetic-retry"})
        self.assertEqual(conflict.status_code, 409)

    def test_visual_without_summary_retries_the_same_canonical_anchor(self):
        path = Path(self.tasks["first"].visual_index_path)
        value = json.loads(path.read_text())
        value["windows"][0]["summary"] = ""
        path.write_text(json.dumps(value))
        anchor = self.targets(kind="visual")[0]
        first = self.create(anchor, request_id="visual-retry")
        retried = self.create(anchor, request_id="visual-retry")
        self.assertEqual(first["id"], retried["id"])

    def test_legacy_read_is_non_mutating_and_backup_restore_preserves_unknown_old_ids(self):
        path = self.root / "personal-notes/task-first.json"
        path.parent.mkdir()
        old = {"id": "legacy_Annotation-7", "text": " \n原文未规范化 cafe\u0301 \n", "quote": "  literal \n", "anchor": {"selected_text": " literal ", "source_revision": "old"}}
        raw = json.dumps({"schema_version": 1, "annotations": [old]}, ensure_ascii=False)
        path.write_text(raw, encoding="utf-8")
        current = list_annotations("task", "first")[0]
        self.assertEqual(path.read_text(encoding="utf-8"), raw)
        self.assertTrue(current["anchor_status"]["stale"])
        response = self.client.post("/api/personal/task/first", json={"id": old["id"], "text": old["text"], "revision": current["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()["annotation"]
        for key in ("id", "text", "quote", "anchor"):
            self.assertEqual(saved[key], old[key])

    def test_stale_claim_map_is_not_presented_as_current_and_invalid_ranges_are_rejected(self):
        Path(self.tasks["first"].note_path).write_text("Unindexed current note.")
        self.assertEqual(self.targets(kind="claim"), [])
        anchor = self.targets(kind="transcript")[0]
        for change in ({"start": -1}, {"end": 0}, {"start": True}, {"target_hash": ""}):
            response = self.client.post("/api/personal/task/first", json={"text": "Draft", "anchor": {**anchor, **change}})
            self.assertEqual(response.status_code, 422, response.text)

    def test_literal_lf_crlf_unicode_and_code_survive_save_edit_backup_restore(self):
        for ending in ("\n", "\r\n"):
            text = ending * 2 + '  const cafe\u0301 = "🧭";' + ending + '\treturn x;' + ending * 2
            quote = ending + "  ```ts" + ending + "  source <>&" + ending + "```  " + ending
            saved = self.client.post("/api/personal/task/first", json={"text": text, "quote": quote}).json()["annotation"]
            self.assertEqual(saved["text"], text)
            self.assertEqual(saved["quote"], quote)
            backup = export_personal_data()
            with patch("app.personal_notes.DATA_DIR", self.root / f"restore-{len(ending)}"):
                restore_personal_data(backup)
                restored = next(a for a in list_annotations("task", "first") if a["id"] == saved["id"])
                self.assertEqual(restored["text"], text)
                self.assertEqual(restored["quote"], quote)
            updated = self.client.post("/api/personal/task/first", json={"id": saved["id"], "text": text, "revision": saved["revision"]}).json()["annotation"]
            self.assertEqual(updated["text"], text)
            self.assertEqual(updated["quote"], quote)

    def test_bundle_opt_in_keeps_personal_mapping_separate_and_lossless(self):
        from app.main import api_export_bundle
        text = '\r\n\r\n  const cafe\u0301 = "🧭";\r\n\treturn x;\r\n\r\n'
        annotation = self.create(self.targets(kind="visual")[0], text=text)
        task = self.tasks["first"]
        note = Path(task.note_path).read_text(encoding="utf-8")
        with ExitStack() as stack:
            for name, result in {"get_task": task, "read_note": note, "read_transcript": {},
                                 "read_visual_index": {"windows": []}, "read_task_qa_history": [],
                                 "read_json": {}, "read_resource_inventory": {}, "read_page_preflight_report": {}}.items():
                stack.enter_context(patch(f"app.main.{name}", return_value=result))
            plain = api_export_bundle(task.id)
            personal = api_export_bundle(task.id, include_annotations=True)
        with ZipFile(BytesIO(plain.body)) as archive:
            self.assertNotIn("personal_annotations.json", archive.namelist())
            self.assertEqual(archive.read("note.md").decode("utf-8"), note)

        with ZipFile(BytesIO(personal.body)) as archive:
            payload = json.loads(archive.read("personal_annotations.json"))
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["task_id"], task.id)
            self.assertEqual(payload["annotations"][0]["id"], annotation["id"])
            self.assertEqual(payload["annotations"][0]["text"], text)
            self.assertEqual(payload["annotations"][0]["anchor"], annotation["anchor"])
            self.assertEqual(archive.read("note.md").decode("utf-8"), note)

    def test_unrelated_identical_task_is_not_a_migration_source(self):
        original = self.create(self.targets(kind="transcript")[0])
        self.make_task("unrelated")
        foreign = self.targets("unrelated", "transcript")[0]
        self.assertEqual(foreign["target_hash"], original["anchor"]["target_hash"])
        self.assertEqual(resolve_anchor(foreign, annotation_targets("task", "first")["targets"])["resolution"], "orphaned")
        rejected = self.client.post("/api/personal/task/first", json={"text": "Wrong task", "anchor": foreign})
        self.assertEqual(rejected.status_code, 409)
        path = self.root / "personal-notes/task-first.json"
        saved_bytes = path.read_bytes()
        self.assertEqual(list_annotations("task", "first")[0]["anchor"], original["anchor"])
        self.assertEqual(path.read_bytes(), saved_bytes)

    def test_migration_lineage_cycles_and_excess_depth_fail_closed(self):
        anchor = self.targets(kind="claim")[0]
        self.make_task("child", "first")
        self.tasks["first"].source_task_id = "child"
        self.assertEqual(resolve_anchor(anchor, annotation_targets("task", "child")["targets"])["resolution"], "orphaned")
        self.tasks["first"].source_task_id = ""
        self.tasks["child"].source_task_id = "deep-0"
        for i in range(101):
            self.tasks[f"deep-{i}"] = self.tasks["first"].model_copy(update={"id": f"deep-{i}", "source_task_id": f"deep-{i+1}" if i < 100 else "first"})
        self.assertEqual(resolve_anchor(anchor, annotation_targets("task", "child")["targets"])["resolution"], "orphaned")

    def test_outside_task_artifact_paths_and_oversized_grid_are_not_read(self):
        task = self.tasks["first"]
        saved = self.create()
        outside = self.root / "private-synthetic.jpg"
        for field, kind, payload in (("note_path", "claim", "Synthetic private note"),
                                     ("transcript_path", "transcript", '{"segments":[{"start":0,"end":1,"text":"Private body"}]}'),
                                     ("visual_index_path", "visual", '{"windows":[]}')):
            with self.subTest(field=field):
                outside.write_text(payload, encoding="utf-8")
                original = getattr(task, field)
                setattr(task, field, str(outside))
                original_open = os.open
                def guarded_open(path, *args, **kwargs):
                    self.assertNotEqual(Path(path).resolve(), outside.resolve())
                    return original_open(path, *args, **kwargs)
                with patch("app.personal_anchors.os.open", side_effect=guarded_open):
                    self.assertEqual(self.targets(kind=kind), [])
                    self.assertEqual(list_annotations("task", "first")[0]["text"], saved["text"])
                setattr(task, field, original)
        visual = Path(task.visual_index_path)
        data = json.loads(visual.read_text())
        data["windows"][0]["grid_path"] = str(outside)
        visual.write_text(json.dumps(data))
        self.assertEqual(self.targets(kind="visual"), [])
        with patch("app.personal_anchors.MAX_ARTIFACT_BYTES", 4), patch.object(Path, "open", side_effect=AssertionError("Oversized grid must not open")):
            self.assertEqual(_grid_hash("first", str(self.root / "first/grids/grid.jpg")), "")

    def test_symlinked_grid_and_source_are_not_read(self):
        outside = self.root / "outside-synthetic.jpg"
        outside.write_bytes(b"synthetic-private-file")
        grid = self.root / "first/grids/link.jpg"
        try:
            grid.symlink_to(outside)
        except OSError:
            self.skipTest("This Windows runner does not permit creating test symlinks")
        self.assertEqual(_grid_hash("first", str(grid)), "")
        note = self.root / "first/linked-note.md"
        note.symlink_to(outside)
        self.tasks["first"].note_path = str(note)
        self.assertEqual(self.targets(kind="claim"), [])

    def test_replacement_between_validation_and_open_is_rejected(self):
        grid = self.root / "first/grids/grid.jpg"
        replacement = self.root / "private-replacement.jpg"
        replacement.write_bytes(b"different-synthetic-private-body")
        original_open = os.open
        def replacing_open(path, *args, **kwargs):
            if Path(path) == grid and replacement.exists():
                replacement.replace(grid)
            return original_open(path, *args, **kwargs)
        with patch("app.personal_anchors.os.open", side_effect=replacing_open):
            self.assertEqual(_grid_hash("first", str(grid)), "")

    def test_personal_api_errors_never_return_private_path_or_exception_body(self):
        private = "C:/private/Synthetic Person/token-secret Private body"
        for error in (ValueError(private), FileNotFoundError(private), OSError(private)):
            with patch("app.routers.personal.save_annotation", side_effect=error):
                response = self.client.post("/api/personal/task/first", json={"text": "Safe draft"})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], "annotation_save_failed")
                self.assertNotIn(private, response.text)
        for method, route, symbol in (("get", "/api/personal/task/first", "list_annotations"),
                                       ("get", "/api/personal/task/first/targets", "annotation_targets"),
                                       ("delete", "/api/personal/task/first/one", "delete_annotation")):
            with patch(f"app.routers.personal.{symbol}", side_effect=FileNotFoundError(private)):
                response = getattr(self.client, method)(route)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(private, response.text)


if __name__ == "__main__":
    unittest.main()
