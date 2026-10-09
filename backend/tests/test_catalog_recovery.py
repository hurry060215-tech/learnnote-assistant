"""Real app, synthetic local data, and failure-safe document catalog recovery."""
from contextlib import ExitStack, closing
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from app import config, library
from app.catalog_guard import catalog_guard
from app.catalog_health import catalog_status
from app.catalog_recovery import apply_recovery, preview_recovery
from app.knowledge import add_evidence
from app.main import app
from app.models import SourceEvidence, TaskRecord


class CatalogRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "data"
        self.root.mkdir()
        self.stack.enter_context(patch.multiple(config, DATA_DIR=self.root, UPLOAD_DIR=self.root / "uploads",
            TASK_DIR=self.root / "tasks", STATIC_DIR=self.root / "static", MODEL_CACHE_DIR=self.root / "models", TEMP_DIR=self.root / "temp"))
        for module in ("library", "knowledge", "main", "storage", "study", "personal_notes", "courses", "concept_identity", "routers.library"):
            self.stack.enter_context(patch(f"app.{module}.DATA_DIR", self.root))
        for module in ("library", "storage", "main"):
            self.stack.enter_context(patch(f"app.{module}.TASK_DIR", self.root / "tasks"))
        for module in ("library", "routers.library"):
            self.stack.enter_context(patch(f"app.{module}.TEMP_DIR", self.root / "temp"))
        config.ensure_dirs()
        self.db = self.root / "library.sqlite3"
        self.raw = "课程编码：学习率决定步长。\n\n原始出处应保留。".encode("gb18030")
        self.material = library.import_document_material("课程.txt", self.raw, "text/plain", encoding="gb18030")
        self.anchors = library.material_anchors(self.material["material_id"])
        self.source = library.material_source_path(self.material["material_id"])
        self.backup = library.backup_library()

    def sql(self, query, args=(), path=None):
        with closing(sqlite3.connect(path or self.db)) as db, db:
            return db.execute(query, args).fetchall()

    def erase(self):
        self.sql("DELETE FROM source_evidence")
        self.sql("DELETE FROM source_evidence_fts")
        self.sql("DELETE FROM library_materials")

    def preview(self, client, backup=None):
        return client.post("/api/library/catalog/recovery/preview", files={"file": ("selected.sqlite3", (backup or self.backup).read_bytes(), "application/vnd.sqlite3")})

    def apply(self, client, token, backup=None):
        return client.post("/api/library/catalog/recovery/apply", data={"preview_token": token}, files={"file": ("selected.sqlite3", (backup or self.backup).read_bytes(), "application/vnd.sqlite3")})

    def test_actual_lifespan_reports_intact_missing_and_corrupt_without_false_rebuild_success(self):
        for state in ("healthy", "missing", "corrupt"):
            with self.subTest(state=state):
                if state == "missing":
                    self.db.unlink()
                elif state == "corrupt":
                    self.db.write_bytes(b"synthetic damaged catalog, retain exactly")
                before = self.db.read_bytes() if self.db.exists() else None
                with TestClient(app, raise_server_exceptions=False) as client:
                    self.assertEqual(client.get("/health").status_code, 200)
                    status = client.get("/api/library/catalog/status").json()
                    self.assertEqual(status["state"], state)
                    self.assertEqual(status["recovery_required"], state != "healthy")
                    self.assertEqual(client.get("/api/library/status").status_code, 200)
                    self.assertEqual(client.get("/api/library/materials").status_code, 200)
                    if state != "healthy":
                        rebuilt = client.post("/api/library/rebuild").json()
                        self.assertEqual(rebuilt["status"], "blocked")
                        self.assertEqual(rebuilt["catalog"]["orphaned_material_ids"], [self.material["material_id"]])
                        self.assertEqual(client.post("/api/library/backup").status_code, 409)
                        restored = client.post("/api/library/restore", files={"file": ("tasks.sqlite3", self.backup.read_bytes())})
                        self.assertEqual(restored.status_code, 409)
                self.assertEqual(self.db.read_bytes() if self.db.exists() else None, before)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_selected_snapshot_recovers_missing_or_corrupt_catalog_with_original_identity(self):
        for damaged in (None, b"synthetic corrupt prior bytes"):
            with self.subTest(corrupt=damaged is not None):
                if damaged is None:
                    self.db.unlink()
                else:
                    self.db.write_bytes(damaged)
                with TestClient(app) as client:
                    preview = self.preview(client)
                    self.assertEqual(preview.status_code, 200, preview.text)
                    body = preview.json()
                    self.assertTrue(body["can_apply"], body)
                    self.assertEqual(self.db.read_bytes() if self.db.exists() else None, damaged)
                    result = self.apply(client, body["preview_token"])
                    self.assertEqual(result.status_code, 200, result.text)
                    self.assertEqual(result.json()["restored_material_count"], 1)
                    restored = library.get_material(self.material["material_id"])
                    self.assertEqual(restored["metadata"], self.material["metadata"])
                    self.assertEqual(restored["evidence_ids"], self.material["evidence_ids"])
                    self.assertEqual(library.material_anchors(restored["material_id"]), self.anchors)
                    folder = self.root / "exports" / result.json()["rollback_directory"]
                    if damaged is not None:
                        self.assertEqual((folder / "library.sqlite3").read_bytes(), damaged)
                    self.assertEqual((folder / "materials" / restored["material_id"] / restored["filename"]).read_bytes(), self.raw)
                    self.assertEqual(catalog_status(self.root)["state"], "healthy")
                self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.material["sha256"])

    def test_healthy_merge_preserves_unrelated_rows_group_history_and_default_task_restore(self):
        self.erase()
        other = library.import_document_material("other.md", b"# Another source", "text/markdown")
        add_evidence(SourceEvidence(evidence_id="independent", source_type="task", title="Unrelated", text="Keep this"))
        task = TaskRecord(id="unrelated-task", source_type="local", mode="local", title="Keep task", created_at="2026-10-09T00:00:00+00:00", updated_at="2026-10-09T00:00:00+00:00")
        library.index_task(task)
        self.sql("CREATE TABLE healthy_history(id INTEGER PRIMARY KEY, value BLOB)")
        self.sql("INSERT INTO healthy_history VALUES(1, ?)", (b"untouched grouping history",))
        history = self.root / "concept-identities" / "synthetic.json"
        history.parent.mkdir()
        history.write_bytes(b'{"history":"synthetic identity references"}')
        preserved = {name: self.sql(f"SELECT * FROM {name}") for name in ("library_tasks", "healthy_history")}
        before = self.db.read_bytes()
        preview = preview_recovery(self.backup)
        self.assertTrue(preview["can_apply"], preview)
        self.assertEqual(self.db.read_bytes(), before)
        result = apply_recovery(self.backup, preview["preview_token"])
        self.assertEqual(result["restored_material_count"], 1)
        self.assertEqual(library.get_material(other["material_id"]), other)
        self.assertEqual(self.sql("SELECT text FROM source_evidence WHERE evidence_id='independent'"), [("Keep this",)])
        for name, rows in preserved.items():
            self.assertEqual(self.sql(f"SELECT * FROM {name}"), rows)
        self.assertEqual(history.read_bytes(), b'{"history":"synthetic identity references"}')
        with TestClient(app) as client:
            restored = client.post("/api/library/restore", files={"file": ("tasks.sqlite3", self.backup.read_bytes())})
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json()["backup_scope"], "task_index_only")
            self.assertEqual(len(library.list_materials()), 2)

    def test_unchanged_has_no_false_success_or_need_to_apply(self):
        before = self.db.read_bytes()
        preview = preview_recovery(self.backup)
        self.assertFalse(preview["can_apply"])
        self.assertEqual(preview["materials"][0]["status"], "unchanged")
        self.assertEqual(self.db.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "catalog_recovery_unresolved"):
            apply_recovery(self.backup, preview["preview_token"])

    def test_invalid_snapshot_and_missing_provenance_are_actionable_and_read_only(self):
        self.db.unlink()
        with TestClient(app) as client:
            bad = client.post("/api/library/catalog/recovery/preview", files={"file": ("bad.sqlite3", b"not sqlite")})
            self.assertEqual(bad.status_code, 422)
            self.assertEqual(bad.json()["detail"]["code"], "catalog_snapshot_invalid")
        self.sql("DELETE FROM library_materials", path=self.backup)
        preview = preview_recovery(self.backup)
        self.assertFalse(preview["can_apply"])
        self.assertEqual(preview["unresolved"][0]["code"], "catalog_metadata_missing")
        self.assertFalse(self.db.exists())
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_changed_source_stale_metadata_foreign_owner_and_schema_are_rejected(self):
        mutations = [
            ("UPDATE library_materials SET metadata_json='{}'", (), "catalog_metadata_invalid"),
            ("UPDATE library_materials SET filename='../outside.txt'", (), "catalog_identity_invalid"),
            ("UPDATE library_materials SET material_id='../foreign'", (), "catalog_identity_invalid"),
            ("UPDATE source_evidence SET task_id='foreign'", (), "catalog_evidence_conflict"),
            ("UPDATE library_materials SET source_uri='file:///outside'", (), "catalog_identity_invalid"),
        ]
        original_snapshot = self.backup.read_bytes()
        self.db.unlink()
        for sql, args, code in mutations:
            with self.subTest(sql=sql):
                self.backup.write_bytes(original_snapshot)
                self.sql(sql, args, path=self.backup)
                preview = preview_recovery(self.backup)
                self.assertFalse(preview["can_apply"])
                self.assertEqual(preview["unresolved"][0]["code"], code)
                self.assertFalse(self.db.exists())
        self.backup.write_bytes(original_snapshot)
        self.source.write_bytes(b"changed original")
        self.assertEqual(preview_recovery(self.backup)["unresolved"][0]["code"], "catalog_original_changed")
        self.source.write_bytes(self.raw)
        self.sql("CREATE VIEW unexpected AS SELECT * FROM library_materials", path=self.backup)
        with self.assertRaisesRegex(ValueError, "catalog_snapshot_schema_invalid"):
            preview_recovery(self.backup)

    def test_stale_snapshot_conflicts_with_surviving_current_metadata(self):
        metadata = dict(self.material["metadata"], decoding_hint="utf-8")
        self.sql("UPDATE library_materials SET metadata_json=?", (json.dumps(metadata),))
        before = self.db.read_bytes()
        preview = preview_recovery(self.backup)
        self.assertEqual(preview["unresolved"][0]["code"], "catalog_current_conflict")
        self.assertEqual(self.db.read_bytes(), before)

    def test_blob_fields_return_actionable_errors_without_serializing_invalid_bytes(self):
        before = self.db.read_bytes()
        original = self.backup.read_bytes()
        with TestClient(app, raise_server_exceptions=False) as client:
            for column in ("material_id", "title"):
                self.backup.write_bytes(original)
                self.sql(f"UPDATE library_materials SET {column}=?", (b"\xff",), path=self.backup)
                response = self.preview(client)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["detail"]["code"], "catalog_snapshot_metadata_invalid")
        self.assertEqual(self.db.read_bytes(), before)

    def test_stale_preview_rejects_database_source_and_snapshot_changes(self):
        self.erase()
        preview = preview_recovery(self.backup)
        library.import_document_material("new.txt", b"New concurrent document", "text/plain")
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, "catalog_changed_preview_again"):
            apply_recovery(self.backup, preview["preview_token"])
        self.assertEqual(self.db.read_bytes(), before)
        preview = preview_recovery(self.backup)
        self.source.write_bytes(b"external file change")
        with self.assertRaisesRegex(ValueError, "catalog_changed_preview_again"):
            apply_recovery(self.backup, preview["preview_token"])
        self.source.write_bytes(self.raw)
        preview = preview_recovery(self.backup)
        self.sql("UPDATE library_materials SET title='Different selected version'", path=self.backup)
        with self.assertRaisesRegex(ValueError, "catalog_changed_preview_again"):
            apply_recovery(self.backup, preview["preview_token"])

    def test_snapshot_change_during_validation_never_binds_unreviewed_metadata(self):
        from app import catalog_recovery
        self.erase()
        validate = catalog_recovery.validate_material
        before = self.db.read_bytes()
        def changed_after_validation(*args):
            result = validate(*args)
            self.sql("UPDATE library_materials SET title='Unreviewed version'", path=self.backup)
            self.sql("UPDATE source_evidence SET title='Unreviewed version'", path=self.backup)
            return result
        with patch.object(catalog_recovery, "validate_material", side_effect=changed_after_validation), self.assertRaisesRegex(ValueError, "catalog_changed_preview_again"):
            preview_recovery(self.backup)
        self.assertEqual(self.db.read_bytes(), before)

    def test_failed_validation_and_interrupted_merge_leave_exact_database_bytes(self):
        from app import catalog_recovery
        self.erase()
        preview = preview_recovery(self.backup)
        before = self.db.read_bytes()
        real_merge = catalog_recovery._merge
        def interrupted(db, selected):
            real_merge(db, selected)
            raise KeyboardInterrupt("synthetic interrupted write")
        with patch.object(catalog_recovery, "_merge", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            apply_recovery(self.backup, preview["preview_token"])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertFalse(list(self.root.glob(".catalog-recovery-*.sqlite3")))

    def test_failed_publication_and_failed_durability_step_restore_corrupt_original(self):
        from app import catalog_recovery
        damaged = b"retain all of this damaged database"
        self.db.write_bytes(damaged)
        preview = preview_recovery(self.backup)
        with patch.object(catalog_recovery.os, "replace", side_effect=OSError("synthetic replace failure")), self.assertRaises(OSError):
            apply_recovery(self.backup, preview["preview_token"])
        self.assertEqual(self.db.read_bytes(), damaged)
        original_sync = catalog_recovery._sync_directory
        root_syncs = []
        def failed_root_sync(path):
            if path == self.root:
                root_syncs.append(path)
                if len(root_syncs) == 2:
                    raise OSError("synthetic durability failure")
            return original_sync(path)
        with patch.object(catalog_recovery, "_sync_directory", side_effect=failed_root_sync), self.assertRaises(OSError):
            apply_recovery(self.backup, preview["preview_token"])
        self.assertEqual(self.db.read_bytes(), damaged)
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_untrusted_live_schema_cannot_delete_unrelated_rows_through_triggers_or_constraints(self):
        self.erase()
        self.sql("CREATE TABLE healthy_history(value TEXT)")
        self.sql("INSERT INTO healthy_history VALUES ('must survive')")
        self.sql("CREATE TRIGGER metadata_trigger BEFORE INSERT ON library_meta BEGIN DELETE FROM healthy_history; END")
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, "catalog_current_schema_invalid"):
            preview_recovery(self.backup)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.sql("SELECT * FROM healthy_history"), [("must survive",)])
        self.sql("DROP TRIGGER metadata_trigger")
        other = library.import_document_material("other.txt", b"Keep unrelated material", "text/plain")
        self.sql("ALTER TABLE library_materials RENAME TO original_materials")
        columns = self.sql("PRAGMA table_info(original_materials)")
        definitions = ",".join(f"{r[1]} {r[2]} NOT NULL" + (" PRIMARY KEY" if r[5] else "") for r in columns)
        self.sql("CREATE TABLE library_materials (" + definitions + ", UNIQUE(status) ON CONFLICT REPLACE)")
        self.sql("INSERT INTO library_materials SELECT * FROM original_materials")
        self.sql("DROP TABLE original_materials")
        before = self.db.read_bytes()
        with self.assertRaisesRegex(ValueError, "catalog_current_schema_invalid"):
            preview_recovery(self.backup)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.sql("SELECT material_id FROM library_materials"), [(other["material_id"],)])

    def test_wal_first_preview_is_stable_and_preserves_existing_history(self):
        self.erase()
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE healthy_history(value TEXT)")
            connection.execute("INSERT INTO healthy_history VALUES('keep')")
            connection.commit()
            preview = preview_recovery(self.backup)
            self.assertTrue(preview["can_apply"], preview)
            digest = library._file_sha256
            def reject_locked_shm(path):
                if path == self.root / "library.sqlite3-shm":
                    raise PermissionError("Synthetic Windows SHM byte-range lock")
                return digest(path)
            with patch.object(library, "_file_sha256", side_effect=reject_locked_shm):
                result = apply_recovery(self.backup, preview["preview_token"])
            self.assertEqual(result["status"], "pass")
            self.assertEqual(connection.execute("SELECT * FROM healthy_history").fetchall(), [("keep",)])
            manifest = json.loads((self.root / "exports" / result["rollback_directory"] / "preserved.json").read_text(encoding="utf-8"))
            for name, digest in manifest["files"].items():
                if digest != "directory":
                    self.assertEqual(hashlib.sha256((self.root / "exports" / result["rollback_directory"] / name).read_bytes()).hexdigest(), digest)

    def test_explicit_mixed_task_rebuild_is_partial_and_retains_unresolved_documents(self):
        from app.storage import create_task, update_task
        task = create_task("local", "Synthetic task")
        transcript = self.root / "tasks" / task.id / "transcript.json"
        transcript.write_text('{"segments":[{"start":1,"end":2,"text":"Original task evidence"}]}')
        update_task(task.id, transcript_path=str(transcript), status="success")
        self.db.unlink()
        with TestClient(app) as client:
            # Startup must not silently recreate the lost material catalog.
            self.assertFalse(self.db.exists())
            response = client.post("/api/library/rebuild")
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()
            self.assertEqual((value["status"], value["indexed"]), ("partial", 1))
            self.assertTrue(value["catalog"]["recovery_required"])
            self.assertEqual(value["catalog"]["orphaned_material_ids"], [self.material["material_id"]])
            self.assertEqual(library.list_materials(), [])
            from app.knowledge import evidence_for_task
            self.assertEqual(evidence_for_task(task.id)[0]["text"], "Original task evidence")
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_process_guard_rejects_a_second_app_writer(self):
        code = """import os, sys
from pathlib import Path
sys.path.insert(0, 'backend')
from app.catalog_guard import CatalogUnavailable, connect_catalog
try:
    connection = connect_catalog(Path(os.environ['LEARNNOTE_DATA_DIR']) / 'library.sqlite3')
except CatalogUnavailable as exc:
    print(str(exc))
else:
    connection.close()
    raise SystemExit('unexpected writer access')
"""
        with catalog_guard(self.root):
            result = subprocess.run([sys.executable, "-c", code], env={**os.environ, "LEARNNOTE_DATA_DIR": str(self.root)}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "catalog_busy")

    def test_process_interruption_before_commit_keeps_original_database_and_unlocks(self):
        self.erase()
        preview = preview_recovery(self.backup)
        before = self.db.read_bytes()
        code = """import os, runpy, sys
from pathlib import Path
guard = runpy.run_path('scripts/test-backend-offline.py')
with guard['offline_network']():
    from app import catalog_recovery
    merge = catalog_recovery._merge
    def interrupted(db, selected):
        merge(db, selected)
        os._exit(73)
    catalog_recovery._merge = interrupted
    catalog_recovery.apply_recovery(Path(sys.argv[1]), sys.argv[2])
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.backup), preview["preview_token"]],
            env={**os.environ, "LEARNNOTE_DATA_DIR": str(self.root)}, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), self.raw)
        # The OS releases the process lock and SQLite rolls back any hot journal.
        with catalog_guard(self.root):
            self.assertEqual(self.sql("SELECT COUNT(*) FROM library_materials"), [(0,)])
        next_preview = preview_recovery(self.backup)
        self.assertTrue(next_preview["can_apply"], next_preview)

    def test_cached_ocr_preserves_ids_and_requires_the_selected_cache_revision(self):
        output = BytesIO()
        canvas = Canvas(output)
        canvas.drawString(50, 750, "synthetic scan source")
        canvas.save()
        material = library.import_document_material("scan.pdf", output.getvalue(), "application/pdf")
        material = library.apply_material_ocr(material["material_id"], {"engine": "synthetic-test", "page_count": 2,
            "pages": [{"page": 1, "text": "Recovered cached OCR", "confidence": 0.81}]})
        anchors = library.material_anchors(material["material_id"])
        snapshot = library.backup_library()
        self.db.unlink()
        with patch("app.pdf_ocr.ocr_pdf", side_effect=AssertionError("No OCR or model calls during recovery")):
            preview = preview_recovery(snapshot)
            self.assertTrue(preview["can_apply"], preview)
            apply_recovery(snapshot, preview["preview_token"])
        restored = library.get_material(material["material_id"])
        self.assertEqual(restored["metadata"], material["metadata"])
        self.assertEqual(library.material_anchors(material["material_id"]), anchors)
        self.assertFalse(restored["metadata"]["ocr_verified"])
        self.db.unlink()
        Path(material["metadata"]["ocr_path"]).write_text('{"pages":[]}', encoding="utf-8")
        invalid = preview_recovery(snapshot)
        self.assertFalse(invalid["can_apply"])
        self.assertEqual(invalid["unresolved"][0]["code"], "catalog_cache_invalid")
        self.assertFalse(self.db.exists())

    def test_scan_without_recognition_can_recover_a_valid_snapshot_without_evidence_table(self):
        self.erase()
        self.source.unlink()
        self.source.parent.rmdir()
        output = BytesIO()
        canvas = Canvas(output)
        canvas.showPage()
        canvas.save()
        material = library.import_document_material("unread-scan.pdf", output.getvalue(), "application/pdf")
        self.assertEqual(material["status"], "ocr_required")
        self.sql("DROP TABLE source_evidence_fts")
        self.sql("DROP TABLE source_evidence")
        snapshot = library.backup_library()
        self.db.unlink()
        preview = preview_recovery(snapshot)
        self.assertTrue(preview["can_apply"], preview)
        result = apply_recovery(snapshot, preview["preview_token"])
        self.assertEqual((result["restored_material_count"], result["restored_evidence_count"]), (1, 0))
        self.assertEqual(library.get_material(material["material_id"])["metadata"], material["metadata"])
        self.assertEqual(library.material_content(material["material_id"]), "")

    def test_missing_evidence_can_merge_without_changing_surviving_material_metadata(self):
        self.sql("DELETE FROM source_evidence")
        self.sql("DELETE FROM source_evidence_fts")
        before = self.sql("SELECT * FROM library_materials")
        preview = preview_recovery(self.backup)
        self.assertTrue(preview["can_apply"], preview)
        result = apply_recovery(self.backup, preview["preview_token"])
        self.assertEqual(result["restored_material_count"], 0)
        self.assertEqual(result["restored_evidence_count"], len(self.anchors))
        self.assertEqual(self.sql("SELECT * FROM library_materials"), before)
        self.assertEqual(library.material_anchors(self.material["material_id"]), self.anchors)

    @unittest.skipIf(os.name == "nt", "Synthetic symlink creation requires optional Windows privileges")
    def test_symlink_original_and_database_are_not_followed(self):
        self.db.unlink()
        other = self.root.parent / "outside.txt"
        other.write_bytes(self.raw)
        self.source.unlink()
        self.source.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "catalog_source_path_unsafe"):
            preview_recovery(self.backup)
        self.assertEqual(other.read_bytes(), self.raw)
        self.source.unlink()
        self.source.write_bytes(self.raw)
        self.db.symlink_to(self.backup)
        before = self.backup.read_bytes()
        with self.assertRaisesRegex(ValueError, "catalog_source_path_unsafe"):
            preview_recovery(self.backup)
        self.assertEqual(catalog_status(self.root)["state"], "corrupt")
        self.assertEqual(self.backup.read_bytes(), before)

    def test_sidecar_state_and_partial_corruption_do_not_replace_potentially_healthy_rows(self):
        self.db.write_bytes(b"corrupt bytes")
        (self.root / "library.sqlite3-wal").write_bytes(b"unresolved write ahead log")
        with self.assertRaisesRegex(ValueError, "catalog_sidecars_unresolved"):
            preview_recovery(self.backup)
        (self.root / "library.sqlite3-wal").unlink()
        self.db.write_bytes(self.backup.read_bytes())
        with patch("app.catalog_recovery.catalog_status", return_value={**catalog_status(self.root), "state": "corrupt"}), self.assertRaisesRegex(ValueError, "catalog_partial_corruption_unresolved"):
            preview_recovery(self.backup)


if __name__ == "__main__":
    unittest.main()
