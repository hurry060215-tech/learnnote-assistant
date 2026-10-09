"""Synthetic end-to-end snapshots; no external providers or live user data."""
from contextlib import ExitStack, closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.concept_identity import read_history
from app.courses import save_course
from app.graph_snapshot import assemble_snapshot, digest, encoded, safe_locator, verify_snapshot
from app.knowledge import add_evidence, evidence_for_task, remove_evidence
from app.library import import_document_material, register_task_material
from app.models import SourceEvidence
from app.routers.courses import course_router
from app.storage import create_task, update_task


class GraphSnapshotTests(unittest.TestCase):
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
        app.include_router(course_router)
        self.client = TestClient(app)
        self.material = import_document_material("synthetic.md", b"# Document\n\nscale has no video time.\n\nscale second anchor.", "text/markdown")
        self.task = create_task("local", "Synthetic video")
        add_evidence(SourceEvidence(evidence_id="video-original", task_id=self.task.id, source_type="video", title=self.task.title,
                                   source_uri=f"local://tasks/{self.task.id}", text="scale in video", locator="12.345-18.765s",
                                   metadata={"kind": "transcript", "start": 12.345, "end": 18.765, "frame_timestamp": 15.25, "window_id": "window-1"}))
        self.course = save_course("Synthetic <course>", [{"kind": "task", "id": self.task.id}, {"kind": "material", "id": self.material["material_id"]}])
        self.base = f"/api/courses/{self.course['id']}"

    def export(self, **params):
        response = self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": self.course["revision"], **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def preview(self, value):
        return self.client.post("/api/courses/graph-snapshot/preview", json={"snapshot": value})

    def edit(self, **changes):
        comparison = self.client.get(self.base + "/compare", params={"q": "scale"}).json()
        payload = {"request_id": uuid4().hex, "action": "split", "term": "scale", "label": "  Meaning <script> & exact spaces  ",
                   "evidence_ids": ["video-original"], "group_ids": [], "revision": comparison["identity_revision"],
                   "course_revision": self.course["revision"], "scope_revision": comparison["concepts"][0]["scope_revision"], **changes}
        reply = self.client.post(self.base + "/concepts", json=payload)
        self.assertEqual(reply.status_code, 200, reply.text)

    def hashes(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.root.rglob("*") if path.is_file()}

    def test_mixed_roundtrip_contains_full_text_true_anchors_and_ordered_references(self):
        value = self.export(q="Scale scale")
        self.assertEqual(value["scope"], {"query": "Scale scale", "terms": ["scale"], "filters": {"source_id": "", "source_kind": "", "start": None, "end": None}})
        self.assertEqual([entry["position"] for entry in value["sources"]], [0, 1])
        self.assertEqual(value["course"]["revision"], self.course["revision"])
        video = next(row for row in value["evidence"] if row["evidence_id"] == "video-original")
        self.assertEqual(video["metadata"], {"kind": "transcript", "start": 12.345, "end": 18.765, "frame_timestamp": 15.25, "window_id": "window-1"})
        documents = [row for row in value["evidence"] if row["canonical_owner"]["kind"] == "material"]
        self.assertTrue(documents)
        self.assertTrue(all("start" not in row["metadata"] and "end" not in row["metadata"] for row in documents))
        self.assertEqual(value["graph"]["truncated"], {"nodes": False, "matches": False, "edges": False})
        self.assertEqual(len(value["graph"]["edges"]), 1)
        edge = value["graph"]["edges"][0]
        self.assertEqual(len(set(edge["evidence_ids"])), 2)
        self.assertEqual(edge["kind"], "keyword_cooccurrence")
        self.assertFalse(value["graph"]["inference"])
        self.assertEqual(self.preview(value).json(), {"snapshot": value, "graph": value["graph"], "read_only": True})
        self.assertEqual(self.export(q="Scale scale"), value)
        self.assertEqual(verify_snapshot(json.loads(encoded(value)))["snapshot"], value)

    def test_all_filters_reconstruct_exact_scope_and_report_query_term_cap(self):
        cases = [({"source_kind": "task"}, {"video-original"}),
                 ({"source_id": self.material["material_id"]}, set(self.material["evidence_ids"][1:])),
                 ({"source_kind": "material"}, set(self.material["evidence_ids"][1:])),
                 ({"start": 12.35, "end": 15}, {"video-original"}),
                 ({"start": 19}, set()), ({"end": 1}, set()),
                 ({"source_kind": "material", "start": 0}, set())]
        for params, expected in cases:
            with self.subTest(params=params):
                value = self.export(**params)
                self.assertEqual({row["evidence_id"] for row in value["graph"]["matches"]}, expected)
                self.assertEqual(self.preview(value).status_code, 200)
        value = self.export(q="scale one two three four five six seven eight nine")
        self.assertTrue(value["graph"]["query_terms_truncated"])
        self.assertEqual(len(value["scope"]["terms"]), 8)
        self.assertEqual(self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": 1, "start": 20, "end": 10}).status_code, 409)

    def test_exact_split_merge_history_missing_and_stale_entries(self):
        self.edit()
        split = self.export()
        self.assertEqual(split["history"]["events"][0]["request"]["label"], "  Meaning <script> & exact spaces  ")
        self.assertEqual(split["graph"]["edges"], [])
        groups = [group["id"] for group in split["group_state"][0]["groups"]]
        self.edit(action="merge", label="Unified only by my choice", evidence_ids=[], group_ids=groups)
        merged = self.export()
        self.assertEqual(len(merged["history"]["events"]), 2)
        missing = self.material["evidence_ids"][1]
        remove_evidence(missing)
        original = evidence_for_task(self.task.id)[0]
        add_evidence(SourceEvidence(**{key: original[key] for key in SourceEvidence.model_fields}).model_copy(update={"text": "scale changed text"}))
        value = self.export()
        self.assertEqual(value["history"], merged["history"])
        self.assertEqual({item["evidence_id"]: item["status"] for item in value["unresolved"]}, {"video-original": "stale", missing: "missing"})
        self.assertEqual(value["sources"][1]["missing_evidence_ids"], [missing])
        self.assertEqual(value["graph"]["edges"], [])
        self.assertEqual(self.preview(value).json()["graph"], value["graph"])

    def test_more_than_display_limits_is_complete_with_full_citations(self):
        materials = [import_document_material(f"source-{i}.md", f"scale source {i} first.\n\nscale source {i} second.\n\nscale source {i} third.".encode(), "text/markdown") for i in range(45)]
        self.course = save_course("45 synthetic sources", [{"kind": "material", "id": item["material_id"]} for item in materials])
        self.base = f"/api/courses/{self.course['id']}"
        display = self.client.get(self.base + "/compare", params={"q": "scale"}).json()
        self.assertEqual(display["counts"], {"nodes": 45, "matches": 135, "edges": 990})
        self.assertEqual(display["truncated"], {"nodes": True, "matches": True, "edges": True})
        self.assertEqual([len(display[key]) for key in ("nodes", "matches", "edges")], [40, 100, 100])
        value = self.export()
        self.assertEqual([len(value["graph"][key]) for key in ("nodes", "matches", "edges")], [45, 135, 990])
        self.assertEqual(len(value["evidence"]), 135)
        self.assertEqual(self.preview(value).status_code, 200)
        citations = {row["evidence_id"] for row in value["evidence"]}
        self.assertTrue(all(len(set(edge["evidence_ids"])) == 2 and set(edge["evidence_ids"]) <= citations for edge in value["graph"]["edges"]))

    def test_resource_bounds_reject_instead_of_truncating(self):
        for target, limit in (("app.course_graph_export.MAX_EVIDENCE", 1), ("app.graph_snapshot.MAX_EDGES", 0),
                              ("app.graph_snapshot.MAX_BYTES", 100), ("app.course_graph_export.MAX_BYTES", 100), ("app.graph_snapshot.MAX_GROUP_SCAN", 1)):
            with self.subTest(target=target), patch(target, limit):
                response = self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": 1})
                self.assertEqual(response.status_code, 413, response.text)
                self.assertEqual(response.json()["detail"]["code"], "graph_snapshot_too_large")
                self.assertIn("20 MB", response.json()["detail"]["message"])
        with patch("app.routers.graph_snapshot.MAX_BYTES", 100):
            response = self.client.post("/api/courses/graph-snapshot/preview", content="x" * 201)
            self.assertEqual(response.status_code, 413)

    def test_alias_deduplication_wrong_owners_generated_and_review_rows(self):
        alias = register_task_material(self.task)
        self.course = save_course("Aliases", [{"kind": "material", "id": alias["material_id"]}, {"kind": "task", "id": self.task.id}, {"kind": "material", "id": self.material["material_id"]}])
        self.base = f"/api/courses/{self.course['id']}"
        for kind in ("note", "community", "generated-note", "review-draft", "transcript-draft"):
            add_evidence(SourceEvidence(evidence_id=kind, task_id=self.task.id, title="Generated", text="scale", source_type="video", locator="1-2s", metadata={"kind": kind}))
        add_evidence(SourceEvidence(evidence_id="review", task_id=self.task.id, title="Needs review", text="scale", source_type="video", locator="1-2s", metadata={"review_required": True}))
        outsider = create_task("local", "Wrong owner")
        add_evidence(SourceEvidence(evidence_id="wrong-owner", task_id=outsider.id, source_type="video", text="scale"))
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as connection, connection:
            connection.execute("UPDATE library_materials SET evidence_ids_json=? WHERE material_id=?", (json.dumps([*self.material["evidence_ids"], "wrong-owner"]), self.material["material_id"]))
        value = self.export()
        self.assertEqual([row["evidence_id"] for row in value["evidence"]].count("video-original"), 1)
        self.assertEqual(value["sources"][0]["canonical_owner"], {"kind": "task", "id": self.task.id})
        self.assertEqual(value["sources"][0]["status"], "alias")
        self.assertEqual(len(value["sources"][0]["excluded_evidence_ids"]), 6)
        self.assertEqual(value["sources"][2]["excluded_evidence_ids"], ["wrong-owner"])
        self.assertEqual(len(value["graph"]["edges"]), 1)
        self.assertEqual(self.preview(value).status_code, 200)
        with closing(sqlite3.connect(self.root / "library.sqlite3")) as connection, connection:
            connection.execute("UPDATE library_materials SET source_uri=? WHERE material_id=?", ("local://tasks/foreign", alias["material_id"]))
        self.assertEqual(self.export()["sources"][0]["status"], "excluded")
        update_task(self.task.id, summary_source="transcript-draft")
        self.assertFalse(any(row["task_id"] for row in self.export()["evidence"]))

    def test_projection_drops_paths_credentials_queries_but_keeps_text_and_labels(self):
        self.edit()
        original = evidence_for_task(self.task.id)[0]
        item = SourceEvidence(**{key: original[key] for key in SourceEvidence.model_fields})
        add_evidence(item.model_copy(update={"source_uri": "https://user:synthetic-password@example.test/lesson?token=synthetic-signed#auth", "metadata": {
            "kind": "transcript", "start": 12.345, "end": 18.765, "frame_timestamp": 15.25, "window_id": "window-1",
            "media_path": "/private/synthetic.mp4", "api_key": "synthetic-secret", "frame_path": "C:\\private\\frame.png"}}))
        value = self.export()
        video = next(row for row in value["evidence"] if row["task_id"])
        self.assertEqual(video["source_uri"], "https://example.test/lesson")
        self.assertEqual(video["redacted_fields"], ["metadata", "source_uri"])
        exported = encoded(value).decode()
        for private in ("synthetic-password", "synthetic-signed", "synthetic-secret", "/private/", "C:\\\\private"):
            self.assertNotIn(private, exported)
        self.assertIn("scale in video", exported)
        self.assertIn("  Meaning <script> & exact spaces  ", exported)
        self.assertEqual(self.preview(value).status_code, 200)
        add_evidence(item.model_copy(update={"source_uri": "/private/local.mp4", "locator": "C:\\private\\frame.png"}))
        video = next(row for row in self.export()["evidence"] if row["task_id"])
        self.assertEqual(video["source_uri"], "")
        self.assertEqual(video["locator"], "unlocated (redacted)")

    def test_verification_never_reads_or_writes_absent_or_corrupt_catalog(self):
        self.edit()
        value = self.export()
        (self.root / "library.sqlite3").unlink()
        for content in (None, b"synthetic corrupt catalog"):
            if content is not None:
                (self.root / "library.sqlite3").write_bytes(content)
            before = self.hashes()
            with patch("app.courses.get_course", side_effect=AssertionError("live course read")), patch("app.knowledge._connect", side_effect=AssertionError("live evidence read")), patch("app.library._connect", side_effect=AssertionError("live catalog read")), patch("app.concept_identity.read_history", side_effect=AssertionError("live group read")):
                response = self.preview(value)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["snapshot"], value)
            self.assertEqual(before, self.hashes())

    def test_tampered_payloads_reject_even_with_recomputed_digest(self):
        value = self.export()
        mutations = [lambda x: x["graph"]["edges"][0].update(kind="fact"),
                     lambda x: x["graph"]["edges"][0].update(evidence_ids=["video-original", "video-original"]),
                     lambda x: x["evidence"].append(deepcopy(x["evidence"][0])),
                     lambda x: x["evidence"][0].update(canonical_owner={"kind": "task", "id": "wrong-owner"}),
                     lambda x: x["evidence"][0]["metadata"].update(api_key="untrusted"),
                     lambda x: x["evidence"][0].update(source_uri="file:///private/source"),
                     lambda x: x["sources"][0]["evidence_ids"].append("foreign"),
                     lambda x: x["sources"][0].update(resolved_source={"kind": "task", "id": "foreign", "title": "Synthetic video"}),
                     lambda x: x.update(schema_version=100), lambda x: x.update(extra="unknown"),
                     lambda x: x["scope"]["filters"].update(start=float("inf"))]
        before = self.hashes()
        for mutation in mutations:
            changed = deepcopy(value)
            mutation(changed)
            try:
                for record in changed["evidence"]:
                    record["snapshot_fingerprint"] = digest({key: item for key, item in record.items() if key != "snapshot_fingerprint"})
                changed["digest"] = digest({key: item for key, item in changed.items() if key != "digest"})
            except ValueError:
                pass
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ValueError, "graph_snapshot_invalid"):
                    verify_snapshot(changed)
        self.assertEqual(before, self.hashes())
        for raw in ('{"snapshot":{},"snapshot":{}}', '{', '{"snapshot":null}', '{"snapshot":NaN}'):
            self.assertEqual(self.client.post("/api/courses/graph-snapshot/preview", content=raw).status_code, 409)

    def test_stale_revision_and_corrupt_live_index_return_safe_errors(self):
        response = self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": 2})
        self.assertEqual(response.json()["detail"]["code"], "course_changed_reload_required")
        (self.root / "library.sqlite3").write_bytes(b"corrupt synthetic catalog")
        before = self.hashes()
        response = self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "graph_snapshot_unavailable")
        self.assertEqual(before, self.hashes())

    def test_pdf_page_missing_source_and_unresolved_url_are_explicit(self):
        doc_id = self.material["evidence_ids"][1]
        add_evidence(SourceEvidence(evidence_id=doc_id, source_type="pdf", title="Synthetic PDF page", text="scale on a page",
                                   source_uri=f"local://materials/{self.material['material_id']}", locator="page 7 part 2",
                                   metadata={"kind": "material", "material_id": self.material["material_id"], "page": 7, "page_index": 6}))
        # Preserve an existing orphaned task reference, plus an unprocessed URL.
        self.course = save_course(self.course["title"], [*self.course["sources"], {"kind": "url", "url": "https://www.youtube.com/watch?v=synthetic"}],
                                  course_id=self.course["id"], revision=self.course["revision"])
        with patch("app.course_graph_export.courses._evidence_sources", return_value=self.course["sources"]), patch("app.course_graph_export.courses.get_task", side_effect=FileNotFoundError):
            value = self.export()
        self.assertEqual([entry["status"] for entry in value["sources"]], ["missing", "ready", "unresolved_url"])
        page = next(row for row in value["evidence"] if row["evidence_id"] == doc_id)
        self.assertEqual(page["locator"], "page 7 part 2")
        self.assertEqual(page["metadata"]["page"], 7)
        self.assertEqual(page["metadata"]["page_index"], 6)
        self.assertNotIn("start", page["metadata"])
        self.assertEqual(self.preview(value).status_code, 200)

    def test_redacted_fingerprints_preserve_an_unchanged_group(self):
        original = evidence_for_task(self.task.id)[0]
        row = SourceEvidence(**{key: original[key] for key in SourceEvidence.model_fields})
        add_evidence(row.model_copy(update={"source_uri": "https://synthetic:credential@example.test/video?signature=private"}))
        self.edit()
        value = self.export()
        self.assertEqual(value["unresolved"], [])
        self.assertEqual(value["graph"]["edges"], [])
        self.assertEqual(self.preview(value).json()["graph"], value["graph"])

    def test_actual_javascript_serialization_preserves_integral_and_fractional_numbers(self):
        original = evidence_for_task(self.task.id)[0]
        row = SourceEvidence(**{key: original[key] for key in SourceEvidence.model_fields})
        add_evidence(row.model_copy(update={"metadata": {"kind": "transcript", "start": 12.0, "end": 18.0, "frame_timestamp": 0.0000001, "page": 9_007_199_254_740_993}}))
        value = self.export(start=0, end=20)
        exported = next(row for row in value["evidence"] if row["task_id"])
        self.assertNotIn("page", exported["metadata"])
        self.assertIn("metadata", exported["redacted_fields"])
        js = subprocess.run(["node", "-e", "let text='';process.stdin.on('data',x=>text+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(text))));"],
                            input=json.dumps(value), encoding="utf-8", capture_output=True, check=True)
        reply = self.client.post("/api/courses/graph-snapshot/preview", content='{"snapshot":' + js.stdout + '}')
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json()["snapshot"]["digest"], value["digest"])

    def test_export_is_read_only_and_never_creates_missing_catalog_schemas(self):
        self.course = save_course(self.course["title"], [*self.course["sources"], {"kind": "url", "url": "https://www.youtube.com/watch?v=synthetic"}],
                                  course_id=self.course["id"], revision=self.course["revision"])
        before = self.hashes()
        self.export()
        self.assertEqual(before, self.hashes())

        self.assertFalse((self.root / "course-episodes.sqlite3").exists())
        database = self.root / "library.sqlite3"
        database.unlink()
        before = self.hashes()
        reply = self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": self.course["revision"]})
        self.assertEqual(reply.json()["detail"]["code"], "graph_snapshot_unavailable")
        self.assertEqual(before, self.hashes())
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        before = self.hashes()
        reply = self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": self.course["revision"]})
        self.assertEqual(reply.json()["detail"]["code"], "graph_snapshot_unavailable")
        self.assertEqual(before, self.hashes())

    def test_task_identity_or_review_changes_during_capture_reject_without_repair(self):
        from app.course_graph_export import assemble_snapshot
        for change in ({"summary_source": "transcript-draft"}, {"page_url": "https://example.test/changed"}, {"summary_diagnostics": {"review_required": True}},
                       {"source_identity": self.task.source_identity.model_copy(update={"media_sha256": "a" * 64})}):
            def change_after_capture(*args, **kwargs):
                result = assemble_snapshot(*args, **kwargs)
                # Mutate only the separate manifest while the captured SQLite
                # read transaction remains open, as an interrupted writer can.
                with patch("app.storage.index_task"):
                    update_task(self.task.id, **change)
                return result
            with self.subTest(change=change), patch("app.course_graph_export.assemble_snapshot", side_effect=change_after_capture):
                reply = self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": self.course["revision"]})
                self.assertEqual(reply.status_code, 409, reply.text)
                self.assertEqual(reply.json()["detail"]["code"], "course_changed_reload_required")
            update_task(self.task.id, page_url="", summary_source="", summary_diagnostics={}, source_identity=self.task.source_identity)

    def test_invalid_explicit_timing_is_not_silently_replaced_by_locator_time(self):
        original = evidence_for_task(self.task.id)[0]
        row = SourceEvidence(**{key: original[key] for key in SourceEvidence.model_fields})
        for start in ("12", -1, 9_007_199_254_740_993):
            with self.subTest(start=start):
                add_evidence(row.model_copy(update={"metadata": {"kind": "transcript", "start": start, "end": 18}}))
                reply = self.client.get(self.base + "/graph-snapshot", params={"q": "scale", "revision": 1, "start": 0, "end": 20})
                self.assertEqual(reply.status_code, 409, reply.text)
                self.assertEqual(reply.json()["detail"]["code"], "graph_snapshot_invalid")

    def test_every_source_membership_owner_revision_and_reference_must_agree(self):
        alias = register_task_material(self.task)
        self.course = save_course("Aliases", [{"kind": "material", "id": alias["material_id"]}, {"kind": "task", "id": self.task.id}, {"kind": "material", "id": self.material["material_id"]}])
        self.base = f"/api/courses/{self.course['id']}"
        value = self.export()
        def duplicate_reference(changed):
            changed["course"]["sources"].append(deepcopy(changed["course"]["sources"][0]))
            entry = deepcopy(changed["sources"][0]); entry["position"] = len(changed["sources"])
            changed["sources"].append(entry)
        mutations = [lambda x: x["sources"][1]["evidence_ids"].append(self.material["evidence_ids"][1]),
                     lambda x: x["sources"][1].update(owner_revision="0" * 64), duplicate_reference]
        for mutate in mutations:
            changed = deepcopy(value); mutate(changed)
            rebuilt = assemble_snapshot(changed["course"], changed["sources"], changed["evidence"], changed["history"], changed["scope"]["query"], changed["scope"]["filters"])
            self.assertEqual(self.preview(rebuilt).status_code, 409)

    def test_duplicate_keys_inside_raw_file_and_all_path_locator_forms_reject(self):
        value = self.export()
        raw = json.dumps(value)
        duplicated = '{"format":"hostile.first.value",' + raw[1:]
        reply = self.client.post("/api/courses/graph-snapshot/preview", content='{"snapshot":' + duplicated + '}')
        self.assertEqual(reply.status_code, 409)
        for locator in ("file:/private/synthetic-secret.txt", "~/private/synthetic-secret.txt", "~user/private/file", "../private/file", "C:private.txt", "\\\\server\\private", " file:/private/synthetic.txt", " /private/synthetic.txt"):
            with self.subTest(locator=locator):
                self.assertEqual(safe_locator(locator), "unlocated (redacted)")
        self.assertEqual(safe_locator(" A: Introduction "), " A: Introduction ")

    def test_import_candidate_limit_counts_all_source_partitions_together(self):
        value = self.export()
        for index, entry in enumerate(value["sources"]):
            entry["missing_evidence_ids"] = [f"missing-{index}-{number}" for number in range(6000)]
        value = assemble_snapshot(value["course"], value["sources"], value["evidence"], value["history"], value["scope"]["query"], value["scope"]["filters"])
        reply = self.preview(value)
        self.assertEqual(reply.status_code, 413)
        self.assertEqual(reply.json()["detail"]["code"], "graph_snapshot_too_large")

    def test_wal_export_preserves_persistent_bytes_and_only_allows_sqlite_shm_bookkeeping(self):
        database = self.root / "library.sqlite3"
        subprocess.run([sys.executable, "-c", "import os, sqlite3, sys; db=sqlite3.connect(sys.argv[1]); db.execute('PRAGMA journal_mode=WAL'); db.execute('CREATE TABLE synthetic_review(value)'); db.commit(); os._exit(0)", str(database)], check=True)
        shared = self.root / "library.sqlite3-shm"
        shared.unlink(missing_ok=True)
        before = self.hashes()
        self.assertIn("library.sqlite3-wal", before)
        self.export()
        after = self.hashes()
        self.assertEqual(before, {name: value for name, value in after.items() if name != "library.sqlite3-shm"})
        self.assertEqual(set(after) - set(before), {"library.sqlite3-shm"}, "Only SQLite's transient reader coordination file is created")

    def test_private_task_options_never_influence_public_owner_revision(self):
        from app.course_graph_export import assemble_snapshot
        with patch("app.storage.index_task"):
            update_task(self.task.id, options=self.task.options.model_copy(update={"llm_api_key": "dummy-private-one", "llm_base_url": "https://private-one.invalid/v1"}))
        first = self.export()
        def change_private_options(*args, **kwargs):
            result = assemble_snapshot(*args, **kwargs)
            with patch("app.storage.index_task"):
                update_task(self.task.id, options=self.task.options.model_copy(update={"llm_api_key": "dummy-private-two", "llm_base_url": "https://private-two.invalid/v1"}))
            return result
        with patch("app.course_graph_export.assemble_snapshot", side_effect=change_private_options):
            second = self.export()
        third = self.export()
        self.assertEqual(first["sources"][0]["owner_revision"], second["sources"][0]["owner_revision"])
        self.assertEqual(first["sources"][0]["owner_revision"], third["sources"][0]["owner_revision"])
        self.assertEqual(first, third)
        self.assertNotIn("dummy-private", encoded(third).decode())


if __name__ == "__main__":
    unittest.main()
