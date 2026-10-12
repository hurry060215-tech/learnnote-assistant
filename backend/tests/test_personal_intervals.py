"""Adjacent subtitle intervals use exact synthetic cues, never timing guesses."""
from contextlib import ExitStack
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app.personal_anchors import annotation_targets, MAX_TRANSCRIPT_CUES, resolve_anchor
from app.personal_notes import export_personal_data, list_annotations, restore_personal_data
import test_personal_anchors as anchor_fixtures


class TranscriptIntervalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = anchor_fixtures.PersonalAnchorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client, self.root, self.tasks = self.fixture.client, self.fixture.root, self.fixture.tasks

    def replace_cues(self, cues, task="first"):
        Path(self.tasks[task].transcript_path).write_text(json.dumps({"segments": cues}), encoding="utf-8")

    def source_cues(self, task="first"):
        return json.loads(Path(self.tasks[task].transcript_path).read_text(encoding="utf-8"))["segments"]

    def interval_response(self, first=0, last=1, task="first", anchors=None):
        cues = anchors or self.fixture.targets(task, "transcript")
        return self.client.post(f"/api/personal/task/{task}/transcript-interval", json={
            "first_evidence_id": cues[first]["evidence_id"], "last_evidence_id": cues[last]["evidence_id"],
            "source_revision": cues[first]["source_revision"]})

    def interval(self, **kwargs):
        response = self.interval_response(**kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["anchor"]

    def saved_path(self):
        return self.root / "personal-notes/task-first.json"

    def test_altered_single_cue_interval_is_rejected_instead_of_silently_narrowed(self):
        first, second = self.fixture.targets(kind="transcript")
        response = self.client.post("/api/personal/task/first", json={
            "text": "Keep this draft", "anchor": {**first, "end": second["end"]}})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"], "annotation_anchor_stale")
        self.assertFalse(self.saved_path().exists())

    def test_exact_overlap_interval_preserves_all_cues_and_single_cue_contract(self):
        cues = self.fixture.targets(kind="transcript")
        self.assertEqual(self.interval(last=0), cues[0])
        anchor = self.interval()
        self.assertEqual((anchor["start"], anchor["end"]), (1, 7))
        self.assertEqual(anchor["source_task_id"], "first")
        self.assertEqual(anchor["source_revision"], cues[0]["source_revision"])
        self.assertEqual(anchor["cues"], [{key: cue[key] for key in ("evidence_id", "start", "end", "target_hash")} for cue in cues])
        generated = Path(self.tasks["first"].transcript_path).read_bytes()
        text = '\r\n  const cafe\u0301 = "🧭";\r\n\treturn x;\r\n\r\n'
        saved = self.fixture.create(anchor, text, "interval-retry")
        self.assertEqual(self.fixture.create(anchor, text, "interval-retry")["id"], saved["id"])
        original = self.saved_path().read_bytes()
        current = list_annotations("task", "first")[0]
        self.assertEqual(current["anchor_status"]["resolution"], "exact")
        self.assertEqual(current["anchor"], anchor)
        self.assertEqual(self.saved_path().read_bytes(), original)
        self.assertEqual(Path(self.tasks["first"].transcript_path).read_bytes(), generated)
        self.fixture.make_task("child", "first")
        child_cues = [{"start": 0, "end": 0.5, "text": "Inserted before."}] + self.source_cues("child")
        self.replace_cues(child_cues, "child")
        migrated = list_annotations("task", "child")[0]
        self.assertEqual(migrated["anchor_status"]["resolution"], "migrated")
        self.assertEqual(migrated["anchor_status"]["resolved_anchor"]["source_task_id"], "child")
        self.assertEqual(migrated["anchor"], anchor)
        self.assertEqual((migrated["id"], migrated["text"], migrated["quote"]), (saved["id"], text, saved["quote"]))
        self.assertEqual(self.saved_path().read_bytes(), original)
        backup = export_personal_data()
        with patch("app.personal_notes.DATA_DIR", self.root / "restore"):
            self.assertEqual(restore_personal_data(backup)["restored_annotations"], 1)
            restored = list_annotations("task", "child")[0]
            for key in ("id", "text", "quote", "anchor"):
                self.assertEqual(restored[key], saved[key])
            response = self.client.post("/api/personal/task/child", json={"id": saved["id"], "text": text + " ", "revision": restored["revision"]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["annotation"]["anchor"], anchor)
            self.assertEqual(restore_personal_data(backup)["restored_annotations"], 0)
            self.assertEqual(list_annotations("task", "child")[0]["text"], text + " ")

    def test_interior_change_missing_reordered_or_inserted_cues_never_relocate(self):
        cues = self.source_cues() + [{"start": 8, "end": 10, "text": "Last cue."}]
        self.replace_cues(cues)
        anchor = self.interval(last=2)
        saved = self.fixture.create(anchor)
        original = self.saved_path().read_bytes()
        variants = []
        changed = deepcopy(cues); changed[1]["text"] = "Changed interior text."; variants.append(changed)
        changed = deepcopy(cues); changed[1]["end"] = 7.5; variants.append(changed)
        variants += [[cues[0], cues[2]], [cues[1], cues[0], cues[2]], [cues[0], {"start": 2, "end": 3, "text": "Inserted interior cue."}, *cues[1:]]]
        for variant in variants:
            with self.subTest(cues=variant):
                self.replace_cues(variant)
                current = list_annotations("task", "first")[0]
                self.assertEqual(current["anchor_status"]["resolution"], "orphaned")
                self.assertEqual(current["anchor_status"]["reason"], "target_missing_or_changed")
                self.assertNotIn("resolved_anchor", current["anchor_status"])
                self.assertEqual(current["anchor"], anchor)
                self.assertEqual(current["text"], saved["text"])
                self.assertEqual(self.saved_path().read_bytes(), original)
        self.replace_cues(cues)
        self.assertEqual(list_annotations("task", "first")[0]["anchor_status"]["resolution"], "exact")

    def test_duplicate_runs_are_exact_before_regeneration_and_ambiguous_after(self):
        cues = self.source_cues()
        self.replace_cues(cues + cues)
        saved = self.fixture.create(self.interval(first=2, last=3))
        self.assertEqual(list_annotations("task", "first")[0]["anchor_status"]["resolution"], "exact")
        original = self.saved_path().read_bytes()
        self.replace_cues(cues + cues + [{"start": 12, "end": 13, "text": "Other revision."}])
        current = list_annotations("task", "first")[0]
        self.assertEqual(current["anchor_status"]["reason"], "ambiguous_target")
        self.assertEqual(self.saved_path().read_bytes(), original)
        response = self.client.post("/api/personal/task/first", json={"id": saved["id"], "text": saved["text"],
            "revision": current["revision"], "anchor": self.interval(first=2, last=3)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["annotation"]["id"], saved["id"])
        self.assertEqual(list_annotations("task", "first")[0]["anchor_status"]["resolution"], "exact")

    def test_stale_picker_and_stale_save_preserve_existing_record(self):
        cues = self.fixture.targets(kind="transcript")
        anchor = self.interval()
        saved = self.fixture.create(anchor)
        original = self.saved_path().read_bytes()
        self.replace_cues(self.source_cues() + [{"start": 8, "end": 9, "text": "A new revision."}])
        response = self.interval_response(anchors=cues)
        self.assertEqual(response.status_code, 409)
        response = self.client.post("/api/personal/task/first", json={"text": "Unsaved draft", "anchor": anchor})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.saved_path().read_bytes(), original)
        current = list_annotations("task", "first")[0]
        self.assertEqual(current["id"], saved["id"])
        self.assertEqual(current["anchor_status"]["resolution"], "migrated")

    def test_unrelated_identical_interval_is_not_accepted(self):
        self.fixture.make_task("unrelated")
        foreign = self.interval(task="unrelated")
        self.assertEqual(resolve_anchor(foreign, annotation_targets("task", "first")["targets"])["resolution"], "orphaned")
        response = self.client.post("/api/personal/task/first", json={"text": "Wrong task", "anchor": foreign})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.saved_path().exists())

    def test_invalid_endpoints_and_missing_interior_identity_fail_closed(self):
        self.assertEqual(self.interval_response(first=1, last=0).status_code, 422)
        cues = self.source_cues()
        self.replace_cues([cues[0], {"start": 5, "end": 6, "text": ""}, cues[1]])
        self.assertEqual(self.interval_response().status_code, 422)
        self.replace_cues(cues)
        anchor = self.interval()
        variants = []
        changed = deepcopy(anchor); changed["cues"][0].pop("evidence_id"); variants.append(changed)
        changed = deepcopy(anchor); changed["cues"][0]["evidence_id"] = "task-unrelated-transcript-00000"; variants.append(changed)
        changed = deepcopy(anchor); changed["cues"][1]["evidence_id"] = changed["cues"][0]["evidence_id"]; variants.append(changed)
        changed = deepcopy(anchor); changed["cues"][0]["start"] = True; variants.append(changed)
        changed = deepcopy(anchor); changed["cues"][1]["start"] = 4; variants.append(changed)
        changed = deepcopy(anchor); changed["cues"].reverse(); variants.append(changed)
        variants += [{**anchor, "end": 99}, {**anchor, "cues": []}, {**anchor, "target_hash": "invented"}, {**anchor, "evidence_id": "invented"}]
        for invalid in variants:
            response = self.client.post("/api/personal/task/first", json={"text": "Keep draft", "anchor": invalid})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertFalse(self.saved_path().exists())

    def test_bounded_selection_does_not_expand_target_enumeration(self):
        cues = [{"start": index, "end": index + 1, "text": f"Cue {index}"} for index in range(MAX_TRANSCRIPT_CUES + 1)]
        self.replace_cues(cues)
        self.assertEqual(len(self.fixture.targets(kind="transcript")), len(cues))
        self.assertEqual(len(self.interval(last=MAX_TRANSCRIPT_CUES - 1)["cues"]), MAX_TRANSCRIPT_CUES)
        self.assertEqual(self.interval_response(last=MAX_TRANSCRIPT_CUES).status_code, 422)

    def test_full_cue_hash_detects_text_changes_beyond_the_preview(self):
        cues = self.source_cues(); cues[0]["text"] = "x" * 1100 + "original"
        self.replace_cues(cues)
        saved = self.fixture.create(self.interval())
        self.assertEqual(len(saved["anchor"]["selected_text"]), 1000)
        cues[0]["text"] = "x" * 1100 + "changed"
        self.replace_cues(cues)
        self.assertEqual(list_annotations("task", "first")[0]["anchor_status"]["resolution"], "orphaned")

    def test_opt_in_bundle_preserves_interval_mapping_and_generated_bytes(self):
        from app.main import api_export_bundle
        saved = self.fixture.create(self.interval(), text="\r\n  Literal cafe\u0301 🧭\r\n ")
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
            for key in ("id", "text", "quote", "anchor"):
                self.assertEqual(payload["annotations"][0][key], saved[key])
            self.assertEqual(archive.read("note.md").decode("utf-8"), note)

    def test_interval_api_does_not_expose_private_exception_details(self):
        with patch("app.routers.personal.transcript_interval", side_effect=OSError("/private/synthetic-path")):
            response = self.interval_response()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "annotation_anchor_unavailable")
