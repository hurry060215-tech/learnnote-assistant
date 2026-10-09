"""Real course handlers with synthetic local sources, no model/network calls."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.concept_identity import read_history
from app.courses import save_course
from app.knowledge import add_evidence, evidence_for_task, remove_evidence, replace_task_evidence
from app.library import import_document_material, material_anchors, rebuild_document_material, rebuild_index, register_task_material
from app.models import SourceEvidence
from app.routers.courses import course_router
from app.storage import create_task, update_task


class ConceptIdentityTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch.multiple(config, DATA_DIR=self.root, UPLOAD_DIR=self.root / "uploads", TASK_DIR=self.root / "tasks",
                                           STATIC_DIR=self.root / "static", MODEL_CACHE_DIR=self.root / "models", TEMP_DIR=self.root / "temp"))
        for module in ("courses", "course_episodes", "concept_identity", "knowledge", "library", "storage", "study"):
            stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        for module in ("storage", "library"):
            stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        app = FastAPI()
        app.include_router(course_router)
        self.client = TestClient(app)
        self.materials = [import_document_material(f"synthetic-{i}.md", text.encode(), "text/markdown") for i, text in enumerate((
            "# Music\n\nA scale orders musical pitches.", "# Measurement\n\nA scale measures the weight of an object.", "# Piano\n\nA scale contains ordered musical notes."))]
        self.course = save_course("Synthetic homonyms", [{"kind": "material", "id": item["material_id"]} for item in self.materials])
        self.base = f"/api/courses/{self.course['id']}"
        self.ids = [next(anchor["evidence_id"] for anchor in material_anchors(item["material_id"]) if "scale" in anchor["text"]) for item in self.materials]

    def compare(self, **params):
        response = self.client.get(self.base + "/compare", params={"q": "scale", **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def payload(self, **changes):
        result = self.compare()
        return {"request_id": uuid4().hex, "action": "split", "term": "scale", "label": "测量 / measurement", "evidence_ids": [self.ids[1]], "group_ids": [],
                "revision": result["identity_revision"], "course_revision": self.course["revision"], "scope_revision": result["concepts"][0]["scope_revision"], **changes}

    def edit(self, **changes):
        response = self.client.post(self.base + "/concepts", json=self.payload(**changes))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def history(self):
        response = self.client.get(self.base + "/concepts/backup")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_split_merge_keeps_actual_evidence_and_original_files(self):
        original = {path: path.read_bytes() for folder in ("materials", "raw-imports", "courses") for path in (self.root / folder).rglob("*") if path.is_file()}
        self.assertEqual(len(self.compare()["edges"]), 3)
        self.edit()
        split = self.compare()
        self.assertEqual(len(split["edges"]), 1)
        self.assertEqual(set(split["edges"][0]["evidence_ids"]), {self.ids[0], self.ids[2]})
        self.assertEqual(split["edges"][0]["kind"], "keyword_cooccurrence")
        self.assertEqual({c["evidence_id"] for c in split["edges"][0]["citations"]}, {self.ids[0], self.ids[2]})
        groups = split["concepts"][0]["groups"]
        self.edit(action="merge", label="My organizational choice", evidence_ids=[], group_ids=[g["id"] for g in groups])
        self.assertEqual(len(self.compare()["edges"]), 3)
        self.assertEqual(len(self.history()["events"]), 2)
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.assertTrue(list((self.root / "concept-identities" / "history" / self.course["id"]).glob("*.json")))

    def test_foreign_missing_generated_and_nonmatching_ids_are_rejected(self):
        outsider = import_document_material("outside.md", b"A scale outside this course.", "text/markdown")
        for evidence_id in (outsider["evidence_ids"][0], "missing", "../not-an-evidence"):
            reply = self.client.post(self.base + "/concepts", json=self.payload(evidence_ids=[evidence_id]))
            self.assertEqual(reply.status_code, 409)
            self.assertEqual(reply.json()["detail"]["code"], "concept_evidence_outside_scope")
        self.assertEqual(self.history()["events"], [])

    def test_revision_conflict_and_uncertain_retry_are_lossless(self):
        payload = self.payload()
        first = self.client.post(self.base + "/concepts", json=payload)
        self.assertEqual(first.status_code, 200)
        retry = self.client.post(self.base + "/concepts", json=payload)
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.json()["replayed"])
        changed = {**payload, "label": "Different meaning"}
        self.assertEqual(self.client.post(self.base + "/concepts", json=changed).json()["detail"]["code"], "concept_request_conflict")
        stale = {**payload, "request_id": uuid4().hex}
        self.assertEqual(self.client.post(self.base + "/concepts", json=stale).json()["detail"]["code"], "concept_changed_reload_required")
        current = self.payload()
        save_course("New course title", self.course["sources"], course_id=self.course["id"], revision=self.course["revision"])
        self.assertEqual(self.client.post(self.base + "/concepts", json=current).json()["detail"]["code"], "concept_changed_reload_required")
        self.assertEqual(len(self.history()["events"]), 1)

    def test_rebuild_preserves_group_and_missing_or_changed_ids_remain_unresolved(self):
        self.edit()
        saved = self.history()
        record = next(anchor for anchor in material_anchors(self.materials[1]["material_id"]) if anchor["evidence_id"] == self.ids[1])
        remove_evidence(self.ids[1])
        missing = self.compare()["concepts"][0]
        group = next(group for group in missing["groups"] if group["id"] != "unassigned")
        self.assertEqual(group["unresolved_ids"], [self.ids[1]])
        reply = self.client.post(self.base + "/concepts", json=self.payload(action="merge", evidence_ids=[], group_ids=[g["id"] for g in missing["groups"]]))
        self.assertEqual(reply.json()["detail"]["code"], "concept_evidence_unresolved")
        rebuild_document_material(self.materials[1]["material_id"])
        self.assertEqual(self.history(), saved)
        self.assertEqual(len(self.compare()["edges"]), 1)
        self.assertFalse(any(group["unresolved_ids"] for group in self.compare()["concepts"][0]["groups"]))
        add_evidence(SourceEvidence(**{key: record[key] for key in SourceEvidence.model_fields if key in record}).model_copy(update={"text": "A scale is now a changed source."}))
        stale = self.compare()
        self.assertEqual(next(group for group in stale["concepts"][0]["groups"] if group["id"] != "unassigned")["unresolved_ids"], [self.ids[1]])
        self.assertTrue(all(self.ids[1] not in edge["evidence_ids"] for edge in stale["edges"]))
        self.assertEqual(self.history(), saved)

    def test_evidence_changes_between_read_and_write_require_reload(self):
        payload = self.payload()
        remove_evidence(self.ids[0])
        reply = self.client.post(self.base + "/concepts", json=payload)
        self.assertEqual(reply.status_code, 409)
        self.assertEqual(reply.json()["detail"]["code"], "concept_evidence_changed_reload_required")
        self.assertEqual(self.history()["events"], [])

    def test_backups_restore_without_overwriting_later_or_divergent_edits(self):
        self.edit()
        first = self.history()
        self.edit(evidence_ids=[self.ids[0]], label="  用户原文 🎵  ")
        latest = self.history()
        reply = self.client.post(self.base + "/concepts/restore", json={"revision": 1, "backup": first})
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json()["restored"], 0)
        self.assertEqual(self.history(), latest)
        self.assertEqual(latest["events"][1]["request"]["label"], "  用户原文 🎵  ")
        divergent = deepcopy(first)
        divergent["events"][0]["request"]["label"] = "A different history"
        self.assertEqual(self.client.post(self.base + "/concepts/restore", json={"revision": 2, "backup": divergent}).json()["detail"]["code"], "concept_backup_conflict")
        # Move the complete file aside as a synthetic lost-store recovery.
        stored = self.root / "concept-identities" / f"{self.course['id']}.json"
        stored.rename(stored.with_suffix(".saved"))
        reply = self.client.post(self.base + "/concepts/restore", json={"revision": 0, "backup": latest})
        self.assertEqual(reply.json()["restored"], 2)
        self.assertEqual(self.history(), latest)
        self.assertEqual(self.client.post(self.base + "/concepts/restore", json={"revision": 0, "backup": latest}).json()["restored"], 0)

    def test_malformed_history_is_preserved_and_never_reset_or_overwritten(self):
        payload = self.payload()
        path = self.root / "concept-identities" / f"{self.course['id']}.json"
        path.parent.mkdir()
        for content in (b"{broken", b"[]", b'{"schema_version":1,"course_id":"other","events":[]}'):
            path.write_bytes(content)
            self.assertEqual(self.client.get(self.base + "/compare", params={"q": "scale"}).status_code, 409)
            self.assertEqual(self.client.post(self.base + "/concepts", json=payload).status_code, 409)
            self.assertEqual(path.read_bytes(), content)

    def test_failed_atomic_write_preserves_prior_choice_and_retry_is_safe(self):
        self.edit()
        prior = self.history()
        payload = self.payload(evidence_ids=[self.ids[0]], label="Music")
        with patch("app.concept_identity.atomic_write_text", side_effect=OSError("synthetic disk full")):
            self.assertEqual(self.client.post(self.base + "/concepts", json=payload).status_code, 409)
        self.assertEqual(self.history(), prior)
        self.assertEqual(self.client.post(self.base + "/concepts", json=payload).status_code, 200)
        self.assertEqual(len(self.history()["events"]), 2)

    def test_actual_video_sources_filter_and_rebuild_without_changing_identity(self):
        tasks = []
        for index in range(2):
            task = create_task("local", f"Synthetic video {index}")
            transcript = self.root / "tasks" / task.id / "transcript.json"
            transcript.write_text(json.dumps({"segments": [{"start": 12, "end": 18, "text": "A scale in this video."}]}))
            tasks.append(update_task(task.id, transcript_path=str(transcript), status="success"))
        course = save_course("Synthetic videos", [{"kind": "task", "id": task.id} for task in tasks])
        self.course, self.base = course, f"/api/courses/{course['id']}"
        self.ids = [evidence_for_task(task.id)[0]["evidence_id"] for task in tasks]
        result = self.compare(start=10, end=20, source_kind="task")
        self.assertEqual(len(result["edges"]), 1)
        self.assertEqual({citation["locator"] for citation in result["edges"][0]["citations"]}, {"12.0-18.0s"})
        self.edit()
        history = self.history()
        (self.root / "library.sqlite3").rename(self.root / "damaged-index-preserved.sqlite3")
        rebuild_index()
        self.assertEqual(self.history(), history)
        self.assertEqual(self.compare()["edges"], [])
        self.assertFalse(any(group["unresolved_ids"] for group in self.compare()["concepts"][0]["groups"]))

    def test_review_drafts_generated_sources_and_aliases_cannot_supply_a_relation(self):
        task = create_task("local", "Synthetic original")
        for kind in ("note", "community", "generated-note", "review-draft", "transcript-draft", "transcript"):
            add_evidence(SourceEvidence(evidence_id=kind, task_id=task.id, title=task.title, source_type="video", text="A scale source.", locator="1-2s", metadata={"kind": kind}))
        for evidence_id, fields in (
            ("legacy-note", {"locator": "note"}),
            ("community-type", {"source_type": "community"}),
            ("review-flag", {"metadata": {"review_required": True}}),
            ("review-quality", {"metadata": {"evidence_quality": "review_required"}}),
        ):
            add_evidence(SourceEvidence(evidence_id=evidence_id, task_id=task.id, title=task.title,
                                        source_type="video", text="A scale source.", locator="1-2s").model_copy(update=fields))
        course = save_course("Synthetic canonical course", [{"kind": "task", "id": task.id}])
        self.course, self.base = course, f"/api/courses/{course['id']}"
        self.assertEqual([item["evidence_id"] for item in self.compare()["matches"]], ["transcript"])
        for kind in ("note", "community", "generated-note", "review-draft", "transcript-draft", "legacy-note", "community-type", "review-flag", "review-quality"):
            reply = self.client.post(self.base + "/concepts", json=self.payload(evidence_ids=[kind]))
            self.assertEqual(reply.status_code, 409)
        update_task(task.id, summary_source="transcript-draft")
        self.assertEqual(self.compare()["matches"], [])

    def test_canonical_rows_beyond_old_limits_and_video_aliases_remain_in_scope(self):
        task = create_task("local", "Synthetic late source")
        rows = [SourceEvidence(evidence_id=f"draft-{i:04d}", task_id=task.id, source_type="video", title=task.title,
                               text="A scale generated passage.", locator="1-2s", metadata={"kind": "review-draft"}) for i in range(510)]
        replace_task_evidence(task.id, rows)
        alias = register_task_material(task)
        # This citation is deliberately added after registration and after the
        # old first-500 task evidence page, so it is absent from the alias list.
        original = SourceEvidence(evidence_id="z-original", task_id=task.id, source_type="video", title=task.title,
                                  text="A scale original passage.", locator="21-24s", metadata={"kind": "transcript"})
        add_evidence(original)
        outsider = create_task("local", "Outside course")
        add_evidence(original.model_copy(update={"evidence_id": "z-outside", "task_id": outsider.id}))
        for sources in ([{"kind": "task", "id": task.id}], [{"kind": "material", "id": alias["material_id"]}],
                        [{"kind": "material", "id": alias["material_id"]}, {"kind": "task", "id": task.id}]):
            course = save_course("Synthetic alias course", sources)
            self.course, self.base = course, f"/api/courses/{course['id']}"
            result = self.compare()
            self.assertEqual([item["evidence_id"] for item in result["matches"]], ["z-original"])
            self.assertEqual([item["evidence_id"] for item in self.compare(source_kind="task")["matches"]], ["z-original"])
            self.assertEqual(self.compare(source_kind="material")["matches"], [])
            self.assertEqual(result["edges"], [])
            self.edit(evidence_ids=["z-original"], label="Existing source only")
            self.assertEqual(self.client.post(self.base + "/concepts", json=self.payload(evidence_ids=["z-outside"])).status_code, 409)
        update_task(task.id, summary_diagnostics={"review_required": True})
        # Reinsert a legacy row with no review metadata. Current owner wins.
        add_evidence(original.model_copy(update={"metadata": {}}))
        self.assertEqual(self.compare()["matches"], [])
        self.assertEqual(self.compare()["concepts"][0]["groups"][0]["unresolved_ids"], ["z-original"])

    def test_invalid_restore_shapes_and_wrong_course_do_not_change_history(self):
        self.edit()
        previous = self.history()
        for mutate in (lambda value: value.update(course_id="f" * 32),
                       lambda value: value["events"][0].update(references={}),
                       lambda value: value["events"][0]["request"].update(revision=10),
                       lambda value: value["events"].append(deepcopy(value["events"][0]))):
            invalid = deepcopy(previous)
            mutate(invalid)
            reply = self.client.post(self.base + "/concepts/restore", json={"revision": 1, "backup": invalid})
            self.assertEqual(reply.status_code, 409)
            self.assertEqual(self.history(), previous)

    def test_unknown_exception_details_are_not_exposed_by_identity_handlers(self):
        payload = self.payload()
        backup = self.history()
        sentinel = "PRIVATE_DETAIL_DO_NOT_EXPOSE"
        for endpoint, target, method, body in (
            ("/concepts", "edit_course_identity", "post", payload),
            ("/concepts/backup", "read_history", "get", None),
            ("/concepts/restore", "restore_history", "post", {"revision": 0, "backup": backup}),
        ):
            for error in (ValueError(sentinel), OSError(sentinel)):
                with patch(f"app.routers.courses.{target}", side_effect=error):
                    reply = getattr(self.client, method)(self.base + endpoint, **({"json": body} if body else {}))
                self.assertEqual(reply.status_code, 409)
                self.assertNotIn(sentinel, reply.text)
                self.assertIn(reply.json()["detail"]["code"], {"concept_operation_failed", "concept_storage_unavailable"})

    def test_history_read_uses_one_descriptor_even_when_path_is_replaced(self):
        self.edit()
        previous = self.history()
        current = self.root / "concept-identities" / f"{self.course['id']}.json"
        replacement = current.with_suffix(".replacement")
        changed = deepcopy(previous)
        changed["events"][0]["request"]["label"] = "Replacement path contents"
        replacement.write_text(json.dumps(changed), encoding="utf-8")
        fstat = os.fstat
        def replace_after_stat(descriptor):
            info = fstat(descriptor)
            replacement.replace(current)
            return info
        with patch("app.concept_identity.os.fstat", side_effect=replace_after_stat):
            self.assertEqual(read_history(self.course["id"]), previous)
        self.assertEqual(read_history(self.course["id"]), changed)

    def test_history_read_bounds_growth_after_size_check_and_rejects_nonfiles(self):
        current = self.root / "concept-identities" / f"{self.course['id']}.json"
        current.parent.mkdir()
        current.write_bytes(b"x" * 33)
        original = current.stat()
        for mode in (original.st_mode, 0):
            info = type("FileInfo", (), {"st_size": 0, "st_mode": mode})()
            with patch("app.concept_identity.MAX_HISTORY_BYTES", 32), patch("app.concept_identity.os.fstat", return_value=info):
                with self.assertRaisesRegex(ValueError, "concept_history_invalid"):
                    read_history(self.course["id"])
        self.assertEqual(current.read_bytes(), b"x" * 33)

    def test_history_byte_cap_is_platform_independent_and_labels_remain_exact(self):
        label = "\r\n  原文 label cafe\u0301 🎵\r\n"
        self.edit(label=label)
        path = self.root / "concept-identities" / f"{self.course['id']}.json"
        raw = path.read_bytes()
        self.assertNotIn(b"\n", raw)
        self.assertNotIn(b"\r", raw)
        self.assertEqual(json.loads(raw)["events"][0]["request"]["label"], label)
        self.edit(evidence_ids=[self.ids[0]])
        snapshots = list((path.parent / "history" / self.course["id"]).glob("*.json"))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
