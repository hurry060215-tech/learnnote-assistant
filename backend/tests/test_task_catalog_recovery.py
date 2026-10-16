"""Task-only rescue preserves original bytes and never fabricates documents."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, library, task_catalog_recovery as recovery
from app.catalog_health import catalog_status
from app.concept_identity import evidence_fingerprint
from app.concept_relation_sources import capture_relations
from app.courses import compare_course, edit_course_identity, save_course
from app.knowledge import evidence_for_task
from app.routers.catalog_recovery import catalog_recovery_router
from app.storage import create_task, update_task


class TaskCatalogRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "data"
        self.stack.enter_context(patch.multiple(config, DATA_DIR=self.root, TASK_DIR=self.root / "tasks", TEMP_DIR=self.root / "temp",
            UPLOAD_DIR=self.root / "uploads", STATIC_DIR=self.root / "static", MODEL_CACHE_DIR=self.root / "models"))
        for module in ("courses", "course_episodes", "concept_identity", "knowledge", "library", "storage", "study"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        for module in ("storage", "library"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        self.task = create_task("local", "Synthetic task")
        self.directory = self.root / "tasks" / self.task.id
        self.transcript = self.directory / "transcript.json"
        self.transcript.write_text(json.dumps({"segments": [{"start": 12, "end": 18, "text": "Gradient descent requires gradients."}]}), encoding="utf-8")
        self.task = update_task(self.task.id, status="success", phase="completed", transcript_path=str(self.transcript))
        self.db = self.root / "library.sqlite3"
        self.original = b"synthetic wholly unreadable catalog\x00\xff"
        app = FastAPI()
        app.include_router(catalog_recovery_router, prefix="/api/library")
        self.client = TestClient(app)

    def corrupt(self):
        self.db.write_bytes(self.original)

    def manifest(self, **changes):
        path = self.directory / "task.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update(changes)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def apply(self):
        preview = recovery.preview_task_recovery()
        self.assertTrue(preview["can_apply"], preview)
        return recovery.apply_task_recovery(preview["preview_token"])

    def test_corrupt_catalog_rebuilds_exact_evidence_and_cited_graph_with_group_history(self):
        before = evidence_for_task(self.task.id)
        other = create_task("local", "Second synthetic source")
        other_transcript = self.root / "tasks" / other.id / "transcript.json"
        other_transcript.write_bytes(self.transcript.read_bytes())
        update_task(other.id, status="success", phase="completed", transcript_path=str(other_transcript))
        course = save_course("Synthetic course", [{"kind": "task", "id": key} for key in (self.task.id, other.id)])
        comparison = compare_course(course["id"], query="gradient")
        edit_course_identity(course["id"], uuid4().hex, {"action": "split", "term": "gradient", "label": "User group",
            "evidence_ids": [before[0]["evidence_id"], evidence_for_task(other.id)[0]["evidence_id"]], "group_ids": [], "revision": comparison["identity_revision"],
            "course_revision": course["revision"], "scope_revision": comparison["concepts"][0]["scope_revision"]})
        graph = capture_relations(course_id=course["id"], revision=course["revision"])
        originals = {path: path.read_bytes() for folder in ("tasks", "courses", "concept-identities") for path in (self.root / folder).rglob("*") if path.is_file()}
        self.corrupt()
        result = self.apply()
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["document_count"])
        self.assertTrue(result["unknown_documents_unrestored"])
        restored = evidence_for_task(self.task.id)
        self.assertEqual([evidence_fingerprint(row) for row in restored], [evidence_fingerprint(row) for row in before])
        after = capture_relations(course_id=course["id"], revision=course["revision"])
        self.assertTrue(after["graph"]["edges"])
        self.assertEqual(after["graph"], graph["graph"])
        self.assertEqual(after["history"], graph["history"])
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        folder = self.root / "exports" / result["rollback_directory"]
        self.assertEqual((folder / "library.sqlite3").read_bytes(), self.original)
        self.assertIn("完全退出", (folder / "RESTORE.txt").read_text(encoding="utf-8"))
        for _ in range(2):
            state = catalog_status(self.root)
            self.assertEqual(state["state"], "incomplete")
            self.assertTrue(state["recovery_required"])
            self.assertEqual(state["orphaned_material_ids"], [])
            self.assertTrue(state["task_only_recovery"]["unknown_documents_unrestored"])
            self.assertEqual(library.rebuild_index()["status"], "partial")

    def test_every_inert_sidecar_is_preserved_exactly_and_removed_from_new_family(self):
        self.corrupt()
        values = {"-wal": b"", "-journal": b"", "-shm": b"unchanged opaque SHM bytes"}
        for suffix, value in values.items():
            self.db.with_name(self.db.name + suffix).write_bytes(value)
        initial = {path.name: path.read_bytes() for path in self.root.glob("library.sqlite3*")}
        preview = recovery.preview_task_recovery()
        self.assertEqual({path.name: path.read_bytes() for path in self.root.glob("library.sqlite3*")}, initial)
        result = recovery.apply_task_recovery(preview["preview_token"])
        folder = self.root / "exports" / result["rollback_directory"]
        manifest = json.loads((folder / "preserved.json").read_text())
        for name, raw in initial.items():
            self.assertEqual((folder / name).read_bytes(), raw)
            self.assertEqual(manifest["files"][name], hashlib.sha256(raw).hexdigest())
        self.assertEqual(sorted(path.name for path in self.root.glob("library.sqlite3*")), ["library.sqlite3"])

    def test_nonempty_logs_unknown_sidecars_and_readable_catalog_disable_apply(self):
        for suffix in ("-wal", "-journal", "-mjunknown"):
            with self.subTest(suffix=suffix):
                self.corrupt()
                sidecar = self.db.with_name(self.db.name + suffix)
                sidecar.write_bytes(b"unresolved transaction")
                preview = recovery.preview_task_recovery()
                self.assertFalse(preview["can_apply"])
                self.assertEqual(preview["code"], "catalog_sidecars_unresolved")
                with self.assertRaisesRegex(ValueError, "catalog_sidecars_unresolved"):
                    recovery.apply_task_recovery(preview["preview_token"])
                self.assertEqual(sidecar.read_bytes(), b"unresolved transaction")
                sidecar.unlink()
        self.db.unlink()
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE unknown_document (identity TEXT)")
            db.execute("INSERT INTO unknown_document VALUES ('keep-me')")
            page = db.execute("SELECT rootpage FROM sqlite_master WHERE name='unknown_document'").fetchone()[0]
            size = db.execute("PRAGMA page_size").fetchone()[0]
        raw = bytearray(self.db.read_bytes())
        raw[(page - 1) * size] = 0  # Corrupt only table data; schema remains readable.
        self.db.write_bytes(raw)
        preview = recovery.preview_task_recovery()
        self.assertFalse(preview["can_apply"])
        self.assertEqual(preview["code"], "catalog_partial_corruption_unresolved")

    def test_missing_catalog_still_warns_unknown_documents_and_has_rollback_manifest(self):
        self.db.unlink()
        result = self.apply()
        folder = self.root / "exports" / result["rollback_directory"]
        self.assertTrue(json.loads((folder / "preserved.json").read_text())["catalog_was_missing"])
        self.assertEqual(catalog_status(self.root)["state"], "incomplete")

    def test_changed_preview_manifest_source_database_and_sidecars_are_rejected(self):
        for which in ("manifest", "source", "database", "sidecar", "new_task"):
            with self.subTest(which=which):
                self.corrupt()
                preview = recovery.preview_task_recovery()
                path = {"manifest": self.directory / "task.json", "source": self.transcript, "database": self.db,
                        "sidecar": self.root / "library.sqlite3-shm", "new_task": self.root / "tasks" / "another" / "task.json"}[which]
                before = path.read_bytes() if path.exists() else None
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((before or b"") + b" ")
                with self.assertRaisesRegex(ValueError, "catalog_changed_preview_again"):
                    recovery.apply_task_recovery(preview["preview_token"])
                if before is None:
                    path.unlink()
                else:
                    path.write_bytes(before)

    def test_malicious_or_invalid_manifests_fail_closed_without_following_paths(self):
        self.corrupt()
        original = (self.directory / "task.json").read_bytes()
        outside = self.root.parent / "private.txt"
        outside.write_text("PRIVATE_NOT_TO_BE_READ", encoding="utf-8")
        for changes in ({"id": "../elsewhere"}, {"id": "different"}, {"schema_version": 9999},
                        {"transcript_path": str(outside)}, {"transcript_path": str(self.directory / "missing")}, {"status": "running"}):
            with self.subTest(changes=changes):
                self.manifest(**changes)
                preview = recovery.preview_task_recovery()
                self.assertFalse(preview["can_apply"])
                self.assertNotIn("PRIVATE_NOT_TO_BE_READ", json.dumps(preview))
                self.assertEqual(self.db.read_bytes(), self.original)
                (self.directory / "task.json").write_bytes(original)
        (self.directory / "task.json").write_text('{"id": "x", "id": "y"}')
        self.assertEqual(recovery.preview_task_recovery()["code"], "task_recovery_manifest_invalid")
        (self.directory / "task.json").write_bytes(original)
        self.transcript.unlink()
        try:
            self.transcript.symlink_to(outside)
        except OSError:
            self.skipTest("Symlinks unavailable")
        self.assertFalse(recovery.preview_task_recovery()["can_apply"])
        self.assertEqual(outside.read_text(), "PRIVATE_NOT_TO_BE_READ")

    def test_stage_failure_or_source_race_does_not_touch_original_family(self):
        self.corrupt()
        for mode in ("stage_failure", "source_race", "sidecar_race"):
            preview = recovery.preview_task_recovery()
            stage = recovery._stage
            def changed(*args):
                if mode == "stage_failure":
                    raise OSError("synthetic disk full")
                stage(*args)
                if mode == "source_race":
                    self.transcript.write_text(self.transcript.read_text() + " ")
                else:
                    (self.root / "library.sqlite3-shm").write_bytes(b"new sidecar")
            with patch.object(recovery, "_stage", side_effect=changed), self.assertRaises((ValueError, OSError)):
                recovery.apply_task_recovery(preview["preview_token"])
            self.assertEqual(self.db.read_bytes(), self.original)
            (self.root / "library.sqlite3-shm").unlink(missing_ok=True)

    def test_interrupted_swap_rolls_back_original_database_and_sidecars(self):
        for phase in ("before_swap", "after_swap", "after_replace"):
            self.corrupt()
            sidecar = self.root / "library.sqlite3-shm"
            sidecar.write_bytes(b"original bookkeeping")
            preview = recovery.preview_task_recovery()
            replace = os.replace
            sync = recovery._sync_directory
            triggered = False
            def fail_replace(source, destination):
                nonlocal triggered
                if Path(source).name.startswith(".task-catalog-") and Path(destination) == self.db:
                    if phase == "after_replace" and not triggered:
                        triggered = True
                        replace(source, destination)
                        raise KeyboardInterrupt("publication flag not yet assigned")
                    if phase == "before_swap":
                        raise KeyboardInterrupt("before atomic publication")
                return replace(source, destination)
            def fail_sync(path):
                nonlocal triggered
                if path == self.root and self.db.read_bytes() != self.original and not triggered:
                    triggered = True
                    raise KeyboardInterrupt("after atomic publication")
                return sync(path)
            with patch.object(recovery, "_sync_directory", side_effect=fail_sync) if phase == "after_swap" else patch.object(recovery.os, "replace", side_effect=fail_replace):
                with self.assertRaises(KeyboardInterrupt):
                    recovery.apply_task_recovery(preview["preview_token"])
            self.assertEqual(self.db.read_bytes(), self.original)
            self.assertEqual(sidecar.read_bytes(), b"original bookkeeping")

    def test_api_requires_explicit_scope_and_token_and_returns_disabled_diagnostics(self):
        schema = self.client.app.openapi()
        for name in ("preview", "apply"):
            path = schema["paths"][f"/api/library/catalog/tasks/{name}"]
            self.assertEqual(set(path), {"post"})
        request = schema["components"]["schemas"]["TaskRecoveryApply"]
        self.assertEqual(set(request["required"]), {"preview_token", "confirm_scope"})
        self.assertFalse(request["additionalProperties"])
        self.assertEqual(request["properties"]["confirm_scope"]["pattern"], "^task_catalog_only$")
        self.corrupt()
        response = self.client.post("/api/library/catalog/tasks/preview")
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertTrue(preview["can_apply"])
        self.assertEqual(self.db.read_bytes(), self.original)
        self.assertEqual(self.client.post("/api/library/catalog/tasks/apply", json={"preview_token": preview["preview_token"]}).status_code, 422)
        self.assertEqual(self.client.post("/api/library/catalog/tasks/apply", json={"preview_token": "a" * 64, "confirm_scope": recovery.SCOPE}).status_code, 409)
        result = self.client.post("/api/library/catalog/tasks/apply", json={"preview_token": preview["preview_token"], "confirm_scope": recovery.SCOPE})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "partial")
        blocked = self.client.post("/api/library/catalog/tasks/preview").json()
        self.assertFalse(blocked["can_apply"])
        self.assertTrue(blocked["diagnostic"])

    def test_sidecar_writer_at_move_is_preserved_and_blocks_publication(self):
        self.corrupt()
        wal = self.root / "library.sqlite3-wal"
        wal.write_bytes(b"")
        preview = recovery.preview_task_recovery()
        replace = os.replace
        def changed(source, destination):
            if Path(source) == wal:
                wal.write_bytes(b"new unaccounted transaction")
            return replace(source, destination)
        with patch.object(recovery.os, "replace", side_effect=changed), self.assertRaisesRegex(ValueError, "catalog_changed_preview_again"):
            recovery.apply_task_recovery(preview["preview_token"])
        self.assertEqual(wal.read_bytes(), b"new unaccounted transaction")
        self.assertEqual(self.db.read_bytes(), self.original)

    def test_interruption_after_each_sidecar_move_restores_complete_original_family(self):
        values = {"-wal": b"", "-journal": b"", "-shm": b"original shared memory"}
        for interrupted in values:
            self.corrupt()
            for suffix, value in values.items():
                self.db.with_name(self.db.name + suffix).write_bytes(value)
            preview = recovery.preview_task_recovery()
            replace = os.replace
            selected = self.db.with_name(self.db.name + interrupted)
            def fail_after_move(source, destination):
                replace(source, destination)
                if Path(source) == selected:
                    raise KeyboardInterrupt("sidecar move succeeded before Python bookkeeping")
            with patch.object(recovery.os, "replace", side_effect=fail_after_move), self.assertRaises(KeyboardInterrupt):
                recovery.apply_task_recovery(preview["preview_token"])
            self.assertEqual(self.db.read_bytes(), self.original)
            for suffix, value in values.items():
                self.assertEqual(self.db.with_name(self.db.name + suffix).read_bytes(), value)

    def test_windows_reparse_point_checks_do_not_require_following_junction(self):
        from types import SimpleNamespace
        self.corrupt()
        original = Path.lstat
        for destination in (self.directory, self.root / "exports", self.root / ".task-state", self.root / "assistant-operations"):
            def reparse(path):
                if path == destination:
                    return SimpleNamespace(st_file_attributes=0x400, st_mode=0o40755)
                return original(path)
            with patch.object(Path, "lstat", reparse):
                try:
                    result = recovery.preview_task_recovery()
                    self.assertFalse(result["can_apply"])
                    self.assertEqual(result["code"], "catalog_source_path_unsafe")
                except ValueError as exc:
                    self.assertEqual(str(exc), "catalog_source_path_unsafe")
            self.assertEqual(self.db.read_bytes(), self.original)

    def test_rollback_probe_does_not_follow_changed_catalog_symlink(self):
        self.corrupt()
        outside = self.root.parent / "outside-original.sqlite3"
        outside.write_bytes(b"private outside bytes")
        preview = recovery.preview_task_recovery()
        stage, fingerprint = recovery._stage, library._file_sha256
        observed = []
        def changed(*args):
            stage(*args)
            self.db.unlink()
            try:
                self.db.symlink_to(outside)
            except OSError:
                self.skipTest("Symlinks unavailable")
        def checked(path):
            if Path(path).is_symlink():
                observed.append(str(path))
            return fingerprint(path)
        with patch.object(recovery, "_stage", side_effect=changed), patch.object(library, "_file_sha256", side_effect=checked):
            with self.assertRaisesRegex(ValueError, "catalog_source_path_unsafe"):
                recovery.apply_task_recovery(preview["preview_token"])
        self.assertEqual(observed, [])
        self.assertEqual(outside.read_bytes(), b"private outside bytes")

    def test_source_budget_is_checked_before_loading_text(self):
        self.corrupt()
        total = (self.directory / "task.json").stat().st_size + self.transcript.stat().st_size
        with patch.object(recovery, "MAX_BYTES", total - 1), patch.object(recovery, "read_canonical_text") as read:
            preview = recovery.preview_task_recovery()
        self.assertFalse(preview["can_apply"])
        self.assertEqual(preview["code"], "catalog_recovery_too_large")
        read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
