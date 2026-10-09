"""Synthetic course question contracts; no model or external service is used."""
from contextlib import ExitStack, closing
from pathlib import Path
from types import SimpleNamespace
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.courses import ask_course, delete_course, save_course
from app.embeddings import DEFAULT_EMBEDDING_MODEL, semantic_rank
from app.knowledge import add_evidence, remove_evidence, replace_task_evidence, search_evidence
from app.library import delete_material, import_document_material, material_anchors, register_task_material
from app.models import SourceEvidence
from app.routers.courses import course_router
from app.storage import create_task, task_file


class CourseQuestionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.multiple(config, DATA_DIR=self.root, UPLOAD_DIR=self.root / "uploads",
                                              TASK_DIR=self.root / "tasks", STATIC_DIR=self.root / "static",
                                              MODEL_CACHE_DIR=self.root / "models", TEMP_DIR=self.root / "temp"))
        for module in ("courses", "course_episodes", "knowledge", "library", "storage", "study"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        for module in ("storage", "library"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        app = FastAPI()
        app.include_router(course_router)
        self.client = TestClient(app)

    def material(self, name="inside.md", text="gradient learning rate sets the step."):
        return import_document_material(name, text.encode(), "text/markdown")

    def course(self, *materials):
        return save_course("Synthetic selected course", [{"kind": "material", "id": item["material_id"]} for item in materials])

    def post(self, course, question="gradient", **extra):
        return self.client.post(f"/api/courses/{course['id']}/ask", json={"question": question, "revision": course["revision"], **extra})

    def task_evidence(self, count=1, *, prefix="inside", text="gradient source", kind="transcript"):
        task = create_task("current_page", f"Synthetic {prefix}")
        evidence = [SourceEvidence(evidence_id=f"{prefix}-{index}", task_id=task.id, source_type="video",
                                  title=task.title, locator="31-45s", source_uri=f"local://{task.id}", text=text,
                                  metadata={"kind": kind, "start": 31.0, "end": 45.0}) for index in range(count)]
        replace_task_evidence(task.id, evidence)
        return task, evidence

    def test_scope_precedes_fts_ranking_and_limit_and_like_fallback(self):
        inside = self.material(text="gradient inside " + "filler " * 100)
        course = self.course(inside)
        self.task_evidence(80, prefix="outside", text="gradient gradient gradient")
        # Newer/better global matches must not starve an older scoped match.
        self.assertNotEqual(search_evidence("gradient", 1)[0]["evidence_id"], inside["evidence_ids"][0])
        for fts in (True, False):
            with self.subTest(fts=fts), patch("app.knowledge._fts_available", return_value=fts):
                answer = self.post(course, limit=1).json()
            self.assertTrue(answer["grounded"])
            self.assertEqual([x["evidence_id"] for x in answer["results"]], inside["evidence_ids"])
            self.assertEqual(answer["scope"], {"kind": "course", "id": course["id"], "title": course["title"], "revision": 1})

    def test_substring_and_single_character_fallback_remain_scoped(self):
        inside = self.material(text="学习率决定步长。熵衡量不确定性。")
        self.material("outside.md", "学习率和熵是课程外资料。")
        course = self.course(inside)
        for query in ("学习率", "熵"):
            answer = self.post(course, query).json()
            self.assertEqual([x["evidence_id"] for x in answer["results"]], inside["evidence_ids"])

    def test_generated_notes_and_community_cannot_supply_course_answer(self):
        task, source = self.task_evidence(text="gradient original transcript")
        for kind in ("note", "community", "generated-note", "review-draft", "transcript-draft"):
            add_evidence(source[0].model_copy(update={"evidence_id": kind, "text": "outsideonly gradient", "metadata": {"kind": kind}}))
        add_evidence(source[0].model_copy(update={"evidence_id": "old-note", "text": "outsideonly gradient", "locator": "note", "metadata": {}}))
        course = save_course("Video course", [{"kind": "task", "id": task.id}])
        self.assertEqual([x["evidence_id"] for x in self.post(course).json()["results"]], [source[0].evidence_id])
        self.assertFalse(self.post(course, "outsideonly").json()["grounded"])

    def test_document_and_video_citations_keep_canonical_source_and_time(self):
        document = self.material()
        task, evidence = self.task_evidence()
        course = save_course("Mixed course", [{"kind": "task", "id": task.id}, {"kind": "material", "id": document["material_id"]}])
        result = self.post(course).json()
        citations = {item["evidence_id"]: item for item in result["citations"]}
        video = citations[evidence[0].evidence_id]
        self.assertEqual((video["source_kind"], video["source_id"], video["locator"], video["start"], video["end"]),
                         ("task", task.id, "31-45s", 31.0, 45.0))
        paper = citations[document["evidence_ids"][0]]
        self.assertEqual((paper["source_kind"], paper["source_id"], paper["locator"]),
                         ("material", document["material_id"], material_anchors(document["material_id"])[0]["locator"]))
        self.assertIn("未进行模型综合", result["answer"])

    def test_review_flagged_rows_are_excluded_before_the_limit(self):
        task, evidence = self.task_evidence()
        for index, metadata in enumerate(({"review_required": True}, {"evidence_quality": "review_required"})):
            add_evidence(evidence[0].model_copy(update={"evidence_id": f"flagged-{index}", "text": "gradient gradient", "metadata": metadata}))
        course = save_course("Reviewed course", [{"kind": "task", "id": task.id}])
        for fts in (True, False):
            with patch("app.knowledge._fts_available", return_value=fts):
                result = self.post(course, limit=1).json()
            self.assertEqual([item["evidence_id"] for item in result["results"]], [evidence[0].evidence_id])

    def test_legacy_rows_obey_current_owner_review_state_in_task_and_material_courses(self):
        task, evidence = self.task_evidence()
        registered = register_task_material(task)
        direct = save_course("Task course", [{"kind": "task", "id": task.id}])
        material = self.course(registered)
        self.assertTrue(self.post(direct).json()["grounded"])
        self.assertTrue(self.post(material).json()["grounded"])
        for changes in ({"summary_source": "transcript-draft"}, {"summary_diagnostics": {"review_required": True}}):
            # Keep a deliberately old projection without new metadata flags.
            task_file(task.id).write_text(task.model_copy(update=changes).model_dump_json(), encoding="utf-8")
            for course in (direct, material):
                with self.subTest(changes=changes, course=course["id"]):
                    result = self.post(course).json()
                    self.assertFalse(result["grounded"])
                    self.assertEqual(result["results"], [])
        self.assertNotIn("review_required", evidence[0].metadata)

    def test_no_matching_evidence_and_empty_courses_are_honest(self):
        document = self.material(text="nothing relevant here")
        self.material("outside.md", "gradient only appears outside the selected course")
        for course in (self.course(document), self.course()):
            for mode in ("lexical", "semantic"):
                with self.subTest(sources=course["sources"], mode=mode), patch("app.knowledge.semantic_rank") as rank:
                    result = self.post(course, mode=mode).json()
                rank.assert_not_called()
                self.assertFalse(result["grounded"])
                self.assertEqual(result["citations"], [])
                self.assertEqual(result["results"], [])
                self.assertIn("本课程", result["answer"])
        for literal in ("???", "%", "_"):
            self.assertFalse(self.post(self.course(document), literal).json()["grounded"])

    def test_membership_change_requires_reload_then_uses_new_members(self):
        first = self.material()
        second = self.material("second.md", "gradient new member")
        course = self.course(first)
        changed = save_course(course["title"], [{"kind": "material", "id": second["material_id"]}], False, course["id"], course["revision"])
        with patch("app.courses.answer_from_evidence") as answer:
            response = self.post(course)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "course_changed_reload_required")
        answer.assert_not_called()
        self.assertEqual([item["evidence_id"] for item in self.post(changed).json()["results"]], second["evidence_ids"])

    def test_deleted_material_and_stale_task_projection_do_not_reappear(self):
        document = self.material()
        course = self.course(document)
        delete_material(document["material_id"])
        self.assertFalse(self.post(course).json()["grounded"])
        task, _ = self.task_evidence()
        course = save_course("Task course", [{"kind": "task", "id": task.id}])
        alias = self.course(register_task_material(task))
        task_file(task.id).unlink()  # Simulate stale projection after source loss.
        self.assertFalse(self.post(course).json()["grounded"])
        self.assertFalse(self.post(alias).json()["grounded"])

    def test_mismatched_owners_and_document_metadata_cannot_expand_membership(self):
        task, _ = self.task_evidence(prefix="outside", text="outsidesecret")
        document = self.material(text="original document")
        course = self.course(document)
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as db, db:
            db.execute("UPDATE library_materials SET metadata_json=? WHERE material_id=?",
                       ('{"linked_task_id":"' + task.id + '"}', document["material_id"]))
        self.assertFalse(self.post(course, "outsidesecret").json()["grounded"])
        self.assertTrue(self.post(course, "original").json()["grounded"])
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as db, db:
            db.execute("UPDATE library_materials SET linked_task_id=? WHERE material_id=?", (task.id, document["material_id"]))
        self.assertFalse(self.post(course, "outsidesecret").json()["grounded"])
        registered = register_task_material(task)
        alias = self.course(registered)
        foreign, _ = self.task_evidence(prefix="foreign", text="foreignsecret")
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as db, db:
            db.execute("UPDATE library_materials SET linked_task_id=? WHERE material_id=?", (foreign.id, registered["material_id"]))
        self.assertFalse(self.post(alias, "foreignsecret").json()["grounded"])
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as db, db:
            db.execute("UPDATE library_materials SET linked_task_id=? WHERE material_id=?", (task.id, registered["material_id"]))
        task_file(task.id).write_text(task.model_copy(update={"id": "different-owner"}).model_dump_json(), encoding="utf-8")
        self.assertFalse(self.post(alias, "outsidesecret").json()["grounded"])

    def test_deleted_evidence_unknown_and_deleted_courses_fail_closed(self):
        document = self.material()
        course = self.course(document)
        remove_evidence(document["evidence_ids"][0])
        self.assertFalse(self.post(course).json()["grounded"])
        delete_course(course["id"])
        for key in (course["id"], "0" * 32, "invalid"):
            response = self.post({**course, "id": key})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["code"], "course_unavailable")

    def test_api_rejects_missing_revision_blank_question_and_unbounded_options(self):
        course = self.course()
        for change in ({"question": "  "}, {"question": "x" * 2001}, {"limit": 0}, {"limit": 51},
                       {"revision": 0}, {"mode": "remote"}, {"evidence_ids": ["outside"]}):
            self.assertEqual(self.post(course, **change).status_code, 422)
        self.assertEqual(self.client.post(f"/api/courses/{course['id']}/ask", json={"question": "gradient"}).status_code, 422)

    def test_large_membership_is_not_truncated_before_candidate_search(self):
        task, items = self.task_evidence(1200)
        registered = register_task_material(task)
        self.assertEqual(len(registered["evidence_ids"]), 500)
        items[-1] = items[-1].model_copy(update={"text": "rareterm at the final anchor"})
        replace_task_evidence(task.id, items)
        course = save_course("Long course", [{"kind": "task", "id": task.id}])
        alias = self.course(registered)
        for selected in (course, alias):
            result = self.post(selected, "rareterm", limit=1).json()
            self.assertEqual(result["citations"][0]["evidence_id"], items[-1].evidence_id)
        replacement = items[-1].model_copy(update={"evidence_id": "rebuilt-late-anchor", "text": "reindexed original"})
        replace_task_evidence(task.id, [replacement])
        for selected in (course, alias):
            result = self.post(selected, "reindexed").json()
            self.assertEqual(result["citations"][0]["evidence_id"], replacement.evidence_id)

    def test_semantic_reranking_only_receives_bounded_in_course_candidates(self):
        task, _ = self.task_evidence(520)
        self.task_evidence(650, prefix="outside")
        course = save_course("Semantic course", [{"kind": "task", "id": task.id}])
        def rank(query, candidates, limit, *, local_only=False):
            self.assertTrue(local_only)
            self.assertEqual(len(candidates), 500)
            self.assertEqual({item["task_id"] for item in candidates}, {task.id})
            return candidates[:limit]
        with patch("app.knowledge.semantic_rank", side_effect=rank):
            result = self.post(course, mode="semantic", limit=3).json()
        self.assertEqual(len(result["citations"]), 3)
        with patch("app.embeddings.find_spec", return_value=None):
            response = self.post(course, mode="semantic")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "local_embedding_unavailable")

    def test_course_semantic_load_is_cache_only_and_missing_cache_is_fixed_conflict(self):
        model = Mock()
        model.encode.return_value = [[1.0], [1.0]]
        constructor = Mock(return_value=model)
        fake_module = SimpleNamespace(SentenceTransformer=constructor)
        with patch("app.embeddings.find_spec", return_value=True), patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            semantic_rank("gradient", [{"title": "source", "text": "gradient"}], local_only=True)
            constructor.assert_called_once_with(DEFAULT_EMBEDDING_MODEL, local_files_only=True)
            course = self.course(self.material())
            for failure in (OSError, ValueError, RuntimeError):
                constructor.side_effect = failure("private cache path must not escape")
                response = self.post(course, mode="semantic")
                self.assertEqual(response.status_code, 409)
                self.assertNotIn("private cache", response.text)
                self.assertEqual(response.json()["detail"]["code"], "local_embedding_unavailable")
                with self.assertRaisesRegex(failure, "private cache"):
                    semantic_rank("gradient", [{"text": "gradient"}])


if __name__ == "__main__":
    unittest.main()
