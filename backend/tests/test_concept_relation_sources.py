"""Public local-only relation API, disposable-catalog capture and offline export."""
from contextlib import ExitStack, closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.courses import save_course, compare_course, edit_course_identity
from app.concept_relation_snapshot import verify_relation_snapshot
from app.graph_snapshot import digest
from app.knowledge import add_evidence
from app.library import import_document_material, register_task_material
from app.models import SourceEvidence
from app.routers.concept_relations import concept_relation_router
from app.storage import create_task, update_task

TEXT = "Gradient descent requires gradients."


class ConceptRelationSourceTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory())) / "data"
        stack.enter_context(patch.multiple(config, DATA_DIR=self.root, UPLOAD_DIR=self.root / "uploads", TASK_DIR=self.root / "tasks",
                                           STATIC_DIR=self.root / "static", MODEL_CACHE_DIR=self.root / "models", TEMP_DIR=self.root / "temp"))
        for module in ("courses", "course_episodes", "concept_identity", "knowledge", "library", "storage", "study"):
            stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        for module in ("storage", "library"):
            stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        app = FastAPI()
        app.include_router(concept_relation_router)
        self.client = TestClient(app)
        self.material = import_document_material("synthetic.md", TEXT.encode(), "text/markdown")
        self.task = create_task("local", "Synthetic video")
        self.add("video", self.task, TEXT)
        self.course = save_course("Synthetic course", [{"kind": "task", "id": self.task.id}, {"kind": "material", "id": self.material["material_id"]}])

    def add(self, key, task, text, **changes):
        add_evidence(SourceEvidence(evidence_id=key, task_id=task.id, source_type="video", title=task.title,
                                   source_uri=f"local://tasks/{task.id}", text=text, locator="12-18s",
                                   metadata={"kind": "transcript", "start": 12, "end": 18}, **changes))

    def capture(self, **params):
        response = self.client.get("/api/concept-relations", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def hashes(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.root.rglob("*") if path.is_file()}

    def test_new_endpoint_openapi_contract_is_explicit_and_independently_frozen(self):
        schema = self.client.app.openapi()
        self.assertEqual(set(schema["paths"]), {"/api/concept-relations", "/api/concept-relations/preview"})
        get = schema["paths"]["/api/concept-relations"]
        preview = schema["paths"]["/api/concept-relations/preview"]
        self.assertEqual(set(get), {"get"})
        self.assertEqual(set(preview), {"post"})
        self.assertEqual(get["get"]["operationId"], "local_concept_relations_api_concept_relations_get")
        self.assertEqual(preview["post"]["operationId"], "preview_concept_relations_api_concept_relations_preview_post")
        parameters = {item["name"]: item for item in get["get"]["parameters"]}
        self.assertEqual(set(parameters), {"course_id", "revision", "q", "source_id", "source_kind", "start", "end"})
        self.assertTrue(all(item["in"] == "query" and not item["required"] for item in parameters.values()))
        self.assertEqual(parameters["q"]["schema"]["maxLength"], 200)
        self.assertEqual(parameters["source_id"]["schema"]["maxLength"], 128)
        self.assertEqual(parameters["source_kind"]["schema"]["enum"], ["", "task", "material"])
        self.assertEqual(parameters["course_id"]["schema"]["pattern"], r"^(?:[a-f0-9]{32})?$")
        for name in ("revision", "start", "end"):
            number = next(item for item in parameters[name]["schema"]["anyOf"] if item["type"] != "null")
            self.assertEqual(number["minimum"], 1 if name == "revision" else 0)

    def test_full_library_and_course_capture_are_read_only_and_offline_reconstructible(self):
        before = self.hashes()
        whole = self.capture()
        scoped = self.capture(course_id=self.course["id"], revision=1)
        self.assertEqual(whole["scope"], {"kind": "library"})
        self.assertEqual(whole["schema_version"], 2)
        self.assertEqual(len(whole["graph"]["edges"]), 1)
        self.assertEqual(whole["graph"], scoped["graph"])
        self.assertEqual(self.hashes(), before)
        with patch("app.courses.get_course", side_effect=AssertionError("No live course")), patch("sqlite3.connect", side_effect=AssertionError("No catalog")):
            result = verify_relation_snapshot(whole)
            self.assertTrue(result["read_only"])
            self.assertEqual(result["graph"], whole["graph"])
        response = self.client.post("/api/concept-relations/preview", json={"snapshot": whole})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.hashes(), before)

    def test_course_group_history_roundtrips_without_remerging_split_meanings(self):
        comparison = compare_course(self.course["id"], "gradient")
        request = {"action": "split", "term": "gradient", "label": "One meaning", "evidence_ids": ["video"],
                   "group_ids": [], "revision": 0, "course_revision": 1,
                   "scope_revision": comparison["concepts"][0]["scope_revision"]}
        edit_course_identity(self.course["id"], "1" * 32, request)
        split = self.capture(course_id=self.course["id"], revision=1)
        self.assertEqual(split["graph"]["edges"], [])
        self.assertEqual(verify_relation_snapshot(split)["graph"], split["graph"])
        comparison = compare_course(self.course["id"], "gradient")
        request.update(action="merge", label="My explicit grouping", evidence_ids=[], group_ids=["unassigned", "1" * 32],
                       revision=1, scope_revision=comparison["concepts"][0]["scope_revision"])
        edit_course_identity(self.course["id"], "2" * 32, request)
        merged = self.capture(course_id=self.course["id"], revision=1)
        self.assertEqual(len(merged["history"]["events"]), 2)
        self.assertEqual(len(merged["graph"]["edges"]), 1)
        reply = self.client.post("/api/concept-relations/preview", json={"snapshot": merged})
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json()["graph"], merged["graph"])

    def test_entire_library_is_not_limited_to_members_of_a_course(self):
        outsider = create_task("local", "Outside every course")
        self.add("outside", outsider, "Gradient descent does not require gradients.")
        all_edges = self.capture()["graph"]["edges"]
        self.assertTrue(any(edge["kind"] == "inferred" for edge in all_edges))
        self.assertFalse(any(edge["kind"] == "inferred" for edge in self.capture(course_id=self.course["id"], revision=1)["graph"]["edges"]))

    def test_aliases_and_duplicate_content_cannot_manufacture_support(self):
        alias = register_task_material(self.task)
        course = save_course("Only one source", [{"kind": "task", "id": self.task.id}, {"kind": "material", "id": alias["material_id"]}])
        self.assertEqual(self.capture(course_id=course["id"], revision=1)["graph"]["edges"], [])
        duplicate = create_task("local", "Same media")
        self.add("duplicate", duplicate, TEXT)
        for task in (self.task, duplicate):
            update_task(task.id, source_identity=task.source_identity.model_copy(update={"media_sha256": "a" * 64}))
        course = save_course("Copies", [{"kind": "task", "id": self.task.id}, {"kind": "task", "id": duplicate.id}])
        self.assertEqual(self.capture(course_id=course["id"], revision=1)["graph"]["edges"], [])

    def test_known_page_aliases_deduplicate_even_when_only_one_has_media_hash(self):
        duplicate = create_task("local", "Same page")
        self.add("duplicate", duplicate, TEXT)
        update_task(self.task.id, page_url="https://example.test/watch?v=same", source_identity=self.task.source_identity.model_copy(update={"media_sha256": "a" * 64}))
        update_task(duplicate.id, page_url="https://example.test/watch?v=same")
        course = save_course("Copies", [{"kind": "task", "id": self.task.id}, {"kind": "task", "id": duplicate.id}])
        self.assertEqual(self.capture(course_id=course["id"], revision=1)["graph"]["edges"], [])

    def test_filters_preserve_original_video_time_and_type(self):
        for options in ({"start": 19}, {"source_kind": "task"}, {"q": "unknown"}):
            self.assertEqual(self.capture(**options)["graph"]["edges"], [])
        value = self.capture(q="GRADIENT")
        citation = next(row for row in value["graph"]["edges"][0]["citations"] if row["source"]["kind"] == "task")
        self.assertEqual(citation["locator"], "12-18s")
        self.assertEqual(citation["anchors"]["start"], 12)
        self.assertEqual(self.client.get("/api/concept-relations", params={"start": 20, "end": 5}).status_code, 409)
        self.assertEqual(self.client.get("/api/concept-relations", params={"course_id": self.course["id"], "revision": 2}).status_code, 409)

    def test_selected_source_retains_counterpart_and_roundtrips_without_source_writes(self):
        before = self.hashes()
        for owner in (self.task.id, self.material["material_id"]):
            value = self.capture(source_id=owner, course_id=self.course["id"], revision=1)
            self.assertEqual(value["schema_version"], 2)
            edge, = value["graph"]["edges"]
            self.assertEqual({row["source"]["id"] for row in edge["citations"]}, {self.task.id, self.material["material_id"]})
            response = self.client.post("/api/concept-relations/preview", json={"snapshot": value})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["snapshot"], value)
        self.assertEqual(self.hashes(), before)

    def test_original_v1_snapshots_keep_exact_graph_and_export_semantics(self):
        path = Path(__file__).parent / "fixtures/cited_relations_v1_source_filter.json"
        original = path.read_bytes()
        before = self.hashes()
        fixtures = json.loads(original)
        for name, value in fixtures.items():
            with self.subTest(name=name):
                response = self.client.post("/api/concept-relations/preview", json={"snapshot": value})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["snapshot"], value)
                self.assertEqual(response.json()["graph"], value["graph"])
        self.assertEqual(len(fixtures["unfiltered"]["graph"]["edges"]), 1)
        self.assertEqual(fixtures["selected_source"]["graph"]["edges"], [])
        for version in (2, 3, True):
            changed = deepcopy(fixtures["selected_source"])
            changed["schema_version"] = version
            changed["digest"] = digest({key: value for key, value in changed.items() if key != "digest"})
            self.assertEqual(self.client.post("/api/concept-relations/preview", json={"snapshot": changed}).status_code, 409)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.hashes(), before)

    def test_review_generated_missing_and_wrong_ownership_evidence_are_excluded(self):
        add_evidence(SourceEvidence(evidence_id="review", task_id=self.task.id, source_type="video", title="Draft", text=TEXT, locator="1-2s", metadata={"review_required": True}))
        add_evidence(SourceEvidence(evidence_id="note", task_id=self.task.id, source_type="video", title="Generated", text=TEXT, locator="generated-note"))
        add_evidence(SourceEvidence(evidence_id="no-time", task_id=self.task.id, source_type="video", title="Unlocated", text=TEXT, locator=""))
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as db, db:
            db.execute("UPDATE library_materials SET evidence_ids_json=? WHERE material_id=?", (json.dumps([*self.material["evidence_ids"], "review", "missing"]), self.material["material_id"]))
        value = self.capture()
        self.assertTrue({"review", "note", "no-time", "missing"}.isdisjoint(row["evidence_id"] for row in value["evidence"]))
        self.assertGreaterEqual(sum(member["excluded"] for member in value["members"]), 3)
        self.assertEqual(sum(member["missing"] for member in value["members"]), 1)

    def test_snapshot_detects_mutated_relation_and_quote_even_with_new_outer_digest(self):
        value = self.capture()
        mutations = [lambda x: x["graph"]["edges"][0].update(truth_verified=True),
                     lambda x: x["graph"]["edges"][0].update(kind="fact"),
                     lambda x: x["graph"]["edges"][0]["citations"][0].update(quote="invented"),
                     lambda x: x["evidence"][0].update(text="tampered"),
                     lambda x: x.update(schema_version=True)]
        for mutate in mutations:
            changed = deepcopy(value)
            mutate(changed)
            changed["digest"] = digest({key: val for key, val in changed.items() if key != "digest"})
            response = self.client.post("/api/concept-relations/preview", json={"snapshot": changed})
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.post("/api/concept-relations/preview", content='{"snapshot":{},"snapshot":{}}').status_code, 409)

    def test_damage_and_limits_never_reset_catalog_or_leak_exception_details(self):
        before = self.hashes()
        for target in ("app.concept_relation_sources.MAX_ROWS", "app.concept_relation_sources.MAX_SOURCES", "app.concept_relation_sources.MAX_TEXT", "app.concept_relation_sources.MAX_CHARACTERS", "app.concept_relation_sources.MAX_BYTES"):
            with patch(target, 0):
                self.assertEqual(self.client.get("/api/concept-relations").status_code, 413, target)
        self.assertEqual(self.hashes(), before)
        with patch("app.concept_relation_sources._inspect", side_effect=OSError("secret local path /private/token")):
            response = self.client.get("/api/concept-relations")
            self.assertEqual(response.status_code, 409)
            self.assertNotIn("secret", response.text)
        (self.root / "library.sqlite3").write_bytes(b"damaged catalog")
        before = self.hashes()
        self.assertEqual(self.client.get("/api/concept-relations").status_code, 409)
        self.assertEqual(self.hashes(), before)

    def test_limit_error_closes_active_cursor_before_traceback_release(self):
        from app.concept_relation_sources import capture_relations
        opened = []
        class TrackedCursor(sqlite3.Cursor):
            closed = False
            def close(self):
                self.closed = True
                return super().close()
        class TrackedConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.startswith("SELECT evidence_id,schema_version"):
                    cursor = self.cursor(factory=TrackedCursor)
                    opened.append(cursor)
                    return cursor.execute(sql, parameters)
                return super().execute(sql, parameters)
        original_connect = sqlite3.connect
        def connect(*args, **kwargs):
            return original_connect(*args, factory=TrackedConnection, **kwargs)
        with patch("app.concept_relation_sources.sqlite3.connect", side_effect=connect), patch("app.concept_relation_sources.MAX_TEXT", 0):
            try:
                capture_relations()
            except ValueError as error:
                self.assertEqual(str(error), "concept_relations_too_large")
                self.assertTrue(opened)
                self.assertTrue(all(cursor.closed for cursor in opened))
            else:
                self.fail("Expected bounded-source rejection")

    def test_live_change_requires_explicit_refresh(self):
        with patch("app.concept_relation_sources._task_revision", return_value="changed"):
            response = self.client.get("/api/concept-relations")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["code"], "concept_relations_changed_reload_required")


if __name__ == "__main__":
    unittest.main()
