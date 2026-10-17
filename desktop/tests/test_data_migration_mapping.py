"""Synthetic, offline tests of the explicitly approved migration mapper."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from desktop.data_migration_paths import (JsonDocument, MappingContext, ReferenceMappingError,
    _lexically_under_source, apply_reference_changes, plan_reference_changes, rewrite_staged_references)

ROOT = Path(__file__).resolve().parents[2]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def inventory(root):
    return {path.relative_to(root).as_posix(): {"sha256": digest(path.read_bytes()), "size": path.stat().st_size,
             "mtime_ns": path.stat().st_mtime_ns, "device": path.stat().st_dev, "inode": path.stat().st_ino}
            for path in root.rglob("*") if path.is_file()}


def hashes(root):
    return {name: item["sha256"] for name, item in inventory(root).items()}


def production_schema(db, *, evidence=False, fts=False):
    """Extract trusted literal DDL from the producer, without importing backend."""
    choices = [(ROOT / "backend/app/library.py", "_ensure_schema")]
    if evidence:
        choices.append((ROOT / "backend/app/knowledge.py", "ensure_evidence_schema"))
    for path, name in choices:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            sql = node.args[0].value
            if node.func.attr == "executescript":
                db.executescript(sql)
            elif fts and node.func.attr == "execute" and isinstance(sql, str) and sql.startswith("CREATE VIRTUAL"):
                db.execute(sql)


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="learnnote-map-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "original"
        self.snapshot = self.base / "preview"
        self.stage = self.base / "stage"
        self.destination = self.base / "selected-destination"
        self.source.mkdir()
        self.payloads = {}

    def put(self, relative, raw=b"synthetic artifact"):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return str(path)

    def task(self, identifier="task-a", **extra):
        payload = {"schema_version": 1, "id": identifier, "source_type": "local", "mode": "video",
                   "title": "Synthetic title", "status": "success", "page_url": "https://example.invalid/video?p=2",
                   "created_at": "2026-10-17T00:00:00Z", "updated_at": "unchanged", "control_generation": "keep-generation",
                   "learning_range": {}, "source_task_id": "", "selected_resource": None, "active_video": None,
                   "source_media_path": "", "media_path": "", "note_path": "", "transcript_path": "",
                   "frame_grids": [], "summary_diagnostics": {}, **extra}
        self.payloads[identifier] = payload
        self.save_task(identifier)
        return payload

    def save_task(self, identifier):
        self.put(f"tasks/{identifier}/task.json", json.dumps(self.payloads[identifier], ensure_ascii=False, indent=2).encode())

    def prepare(self):
        self.expected = inventory(self.source)
        shutil.copytree(self.source, self.snapshot)
        shutil.copytree(self.source, self.stage)
        self.original_hashes = hashes(self.source)
        self.preview_hashes = hashes(self.snapshot)

    def plan(self):
        return plan_reference_changes(self.source, self.snapshot, self.destination, self.expected)

    def assert_blocked(self, code=None):
        before = hashes(self.snapshot)
        with self.assertRaises(ReferenceMappingError) as caught:
            self.plan()
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(hashes(self.snapshot), before)
        self.assertEqual(hashes(self.source), self.original_hashes)
        self.assertFalse(self.destination.exists())

    def catalog(self, *, evidence=False, fts=False, wal=False):
        connection = sqlite3.connect(self.source / "library.sqlite3")
        production_schema(connection, evidence=evidence, fts=fts)
        if wal:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
        self.addCleanup(connection.close)
        return connection

    def insert_catalog_task(self, connection, identifier="task-a"):
        task = self.payloads[identifier]
        values = (identifier, "Catalog title", "https://example.invalid/path", "local", "video", "success", "checkpoint", "created", "updated",
                  task.get("note_path", ""), task.get("media_path") or task.get("source_media_path", ""), "fingerprint-stays", "Exact content with old root " + str(self.source))
        connection.execute("INSERT INTO library_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
        connection.commit()
        return values

    def test_same_platform_move_preserves_all_other_json_bytes(self):
        note = self.put("tasks/task-a/note.md")
        self.task(note_path=note, arbitrary={"kept": [1, True, "text that mentions " + note]})
        path = self.source / "tasks/task-a/task.json"
        raw = path.read_bytes().replace(b'"schema_version": 1', b'"schema_version" : 1').replace(b'"kept": [\n      1,', b'"kept": [\n      1.000,')
        path.write_bytes(raw)
        self.prepare()
        plan = self.plan()
        self.assertEqual(hashes(self.snapshot), self.preview_hashes)
        self.assertEqual(len(plan["changes"]), 1)
        self.assertEqual(plan["changes"][0]["json_pointer"], "/note_path")
        apply_reference_changes(self.stage, plan)
        result = (self.stage / "tasks/task-a/task.json").read_bytes()
        expected = raw.replace(json.dumps(note).encode(), json.dumps(str(self.destination / "tasks/task-a/note.md")).encode(), 1)
        self.assertEqual(result, expected)
        self.assertEqual(hashes(self.source), self.original_hashes)
        self.assertFalse(self.destination.exists())

    def test_exact_nested_pointers_and_companion_files(self):
        media = self.put("tasks/task-a/downloads/source.mp4")
        frame = self.put("tasks/task-a/frames/frame-001.png")
        grid = self.put("tasks/task-a/grids/grid-001.jpg")
        quality = self.put("tasks/task-a/note_quality.json", b'{"score": 1}')
        visual = {"task_id": "task-a", "frames": [{"path": frame, "timestamp": 2, "sha256": "unchanged"}],
                  "important_frames": [{"path": frame}], "windows": [{"grid_path": grid}]}
        visual_path = self.put("tasks/task-a/visual_index.json", json.dumps(visual).encode())
        diagnostic_path = self.put("tasks/task-a/summary_diagnostics.json", json.dumps({"note_quality_path": quality, "quality": "same"}).encode())
        self.task(source_media_path=media, media_path=media, visual_index_path=visual_path,
                  summary_diagnostics_path=diagnostic_path, summary_diagnostics={"note_quality_path": quality},
                  download_attempts=[{"output_path": media, "status": "success"}],
                  frame_grids=[{"path": grid, "frame_paths": [frame], "important_frame_paths": [frame]}],
                  visual_windows=[{"grid_path": grid}])
        self.prepare()
        plan = self.plan()
        self.assertEqual(len(plan["changes"]), 14)
        self.assertTrue(any(item.get("json_pointer") == "/frame_grids/0/important_frame_paths/0" for item in plan["changes"]))
        apply_reference_changes(self.stage, plan)
        for change in plan["changes"]:
            self.assertIn(str(self.destination), change["after"])
        self.assertEqual((self.stage / "tasks/task-a/frames/frame-001.png").read_bytes(), b"synthetic artifact")

    def test_external_original_is_disclosed_without_any_stat_or_read(self):
        external = str(self.base / "outside" / "original.mp4")
        self.task(source_media_path=external)
        self.prepare()
        original_lstat, original_open = Path.lstat, os.open
        def no_external_stat(path, *args, **kwargs):
            if str(path) == external or path == self.source:
                raise AssertionError("original path was probed")
            return original_lstat(path, *args, **kwargs)
        def no_external_open(path, *args, **kwargs):
            if str(path).startswith(str(self.source)) or str(path) == external:
                raise AssertionError("original path was opened")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "lstat", no_external_stat), patch("os.open", no_external_open):
            plan = self.plan()
            apply_reference_changes(self.stage, plan)
        self.assertEqual(plan["changes"], [])
        self.assertEqual(plan["external_references"][0]["value"], external)
        self.assertEqual(plan["external_references"][0]["disposition"], "unchanged_external_original_not_copied")

    def test_source_and_destination_cannot_be_used_as_writable_stage(self):
        self.task()
        self.prepare()
        plan = self.plan()
        for stage in (self.source, self.source / "nested", self.destination, self.destination / "nested"):
            with self.subTest(stage=stage), self.assertRaises(ReferenceMappingError):
                apply_reference_changes(stage, plan)
        with self.assertRaises(ReferenceMappingError):
            plan_reference_changes(self.source, self.source, self.destination, self.expected)

    def test_malformed_identity_and_traversal_are_rejected(self):
        for identifier, pointer in (("../evil", ""), ("task-a", str(self.source / "tasks/task-a/../task-b/note.md"))):
            with self.subTest(identifier=identifier):
                payload = self.task(note_path=pointer)
                payload["id"] = identifier
                self.save_task("task-a")
                if self.snapshot.exists():
                    shutil.rmtree(self.snapshot)
                    shutil.rmtree(self.stage)
                self.prepare()
                self.assert_blocked()

    def test_foreign_and_prefix_similar_roots_are_not_mapped(self):
        for value in (r"C:\old\tasks\task-a\note.md", str(self.base / "original-other/tasks/task-a/note.md"),
                      str(self.base / "old/tasks/task-a/input.mp4")):
            with self.subTest(value=value):
                if self.snapshot.exists():
                    shutil.rmtree(self.snapshot)
                    shutil.rmtree(self.stage)
                self.task(source_media_path=value)
                self.prepare()
                self.assert_blocked("foreign_reference_root")

    def test_missing_destination_and_case_collisions_fail_closed(self):
        self.task(note_path=str(self.source / "tasks/task-a/note.md"))
        self.prepare()
        self.assert_blocked("missing_inventory_file")
        self.expected["Tasks/task-a/task.json"] = dict(self.expected["tasks/task-a/task.json"])
        self.assert_blocked("colliding_snapshot_paths")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_linked_snapshot_or_ancestor_is_rejected(self):
        note = self.put("tasks/task-a/note.md")
        self.task(note_path=note)
        self.prepare()
        linked = self.snapshot / "tasks/task-a/note.md"
        linked.unlink()
        linked.symlink_to(self.source / "tasks/task-a/note.md")
        self.assert_blocked("linked_snapshot")

    @unittest.skipUnless(hasattr(os, "link"), "hardlinks unavailable")
    def test_source_hardlinks_copy_to_independent_stage_files(self):
        note = self.put("tasks/task-a/note.md")
        os.link(note, self.source / "hardlink-kept.txt")
        self.task(note_path=note)
        self.prepare()
        plan = self.plan()
        apply_reference_changes(self.stage, plan)
        self.assertEqual(hashes(self.source), self.original_hashes)

    def test_changed_or_partial_stage_is_rejected_before_any_write(self):
        self.task(note_path=self.put("tasks/task-a/note.md"))
        self.prepare()
        plan = self.plan()
        (self.stage / "tasks/task-a/note.md").write_bytes(b"changed")
        before = hashes(self.stage)
        with self.assertRaises(ReferenceMappingError):
            apply_reference_changes(self.stage, plan)
        self.assertEqual(before, hashes(self.stage))
        (self.stage / "tasks/task-a/note.md").unlink()
        with self.assertRaises(ReferenceMappingError):
            apply_reference_changes(self.stage, plan)
        self.assertEqual(hashes(self.source), self.original_hashes)

    def test_changed_plan_is_rejected(self):
        self.task(note_path=self.put("tasks/task-a/note.md"))
        self.prepare()
        plan = self.plan()
        plan["changes"][0]["after"] = str(self.base / "wrong")
        with self.assertRaises(ReferenceMappingError) as caught:
            apply_reference_changes(self.stage, plan)
        self.assertEqual(caught.exception.code, "mapping_plan_changed")
        self.assertEqual(hashes(self.stage), self.preview_hashes)

    def test_unsupported_schema_unknown_paths_and_wrong_shapes(self):
        cases = [{"schema_version": 2}, {"future_path": "anything"}, {"future_paths": []},
                 {"frame_grids": {"path": "x"}}, {"summary_diagnostics": []},
                 {"note_path": 3}, {"frame_grids": [{"frame_paths": "wrong"}]},
                 {"nested": {"output_path": "unknown"}}]
        for extra in cases:
            with self.subTest(extra=extra):
                if self.snapshot.exists():
                    shutil.rmtree(self.snapshot)
                    shutil.rmtree(self.stage)
                self.task(**extra)
                self.prepare()
                self.assert_blocked()

    def test_unknown_companion_path_schema_is_rejected(self):
        self.task()
        self.put("tasks/task-a/future_artifact.json", b'{"new_path": "somewhere"}')
        self.prepare()
        self.assert_blocked("unsupported_reference_schema")

    def test_duplicate_keys_and_nonfinite_numbers_are_rejected(self):
        for raw in (b'{"id":"a","id":"b"}', b'{"a": NaN}', b'{"a": 1e999}', b'[] trailing'):
            with self.subTest(raw=raw), self.assertRaises(ReferenceMappingError):
                JsonDocument(raw)

    def test_cross_task_media_requires_exact_explicit_ancestry(self):
        media = self.put("tasks/parent/source.mp4")
        self.task("parent", media_path=media)
        self.task("child", source_task_id="parent", mode="rerun_from_media", source_media_path=media)
        self.prepare()
        plan = self.plan()
        self.assertEqual(len(plan["changes"]), 2)
        apply_reference_changes(self.stage, plan)
        result = json.loads((self.stage / "tasks/child/task.json").read_bytes())
        self.assertEqual(result["source_media_path"], str(self.destination / "tasks/parent/source.mp4"))

    def test_cross_task_sibling_missing_ancestor_and_part_mismatch_block(self):
        media = self.put("tasks/parent/source.mp4")
        self.task("parent", media_path=media, selected_resource={"url": "https://example.invalid/part2"})
        cases = [dict(source_task_id=""), dict(source_task_id="missing"),
                 dict(source_task_id="parent", selected_resource={"url": "https://example.invalid/part3"}),
                 dict(source_task_id="parent", page_url="https://example.invalid/video?p=3")]
        for extra in cases:
            with self.subTest(extra=extra):
                if self.snapshot.exists():
                    shutil.rmtree(self.snapshot)
                    shutil.rmtree(self.stage)
                self.task("child", mode="rerun_from_media", source_media_path=media, **extra)
                self.prepare()
                self.assert_blocked()

    def test_cross_task_selected_range_is_proven_and_never_expanded(self):
        media = self.put("tasks/parent/source.mp4")
        self.task("parent", media_path=media, media_integrity={"duration": 100})
        selected = {"start": 10, "end": 20, "original_start": 10, "original_end": 20}
        self.task("child", source_task_id="parent", mode="rerun_from_media", source_media_path=media, learning_range=selected)
        self.prepare()
        self.assertEqual(len(self.plan()["changes"]), 2)
        self.payloads["child"]["learning_range"]["original_end"] = 200
        self.save_task("child")
        shutil.rmtree(self.snapshot)
        shutil.rmtree(self.stage)
        self.prepare()
        self.assert_blocked("ancestor_range_mismatch")

    def test_fractional_nested_range_matches_decimal_producer(self):
        media = self.put("tasks/parent/selected-range.mp4")
        self.task("parent", media_path=media, media_integrity={"duration": 0.4},
                  learning_range={"start": 0.1, "end": 0.4, "original_start": 0.1, "original_end": 0.4})
        self.task("child", source_task_id="parent", mode="rerun_from_media", source_media_path=media,
                  learning_range={"start": 0.2, "end": 0.3, "original_start": 0.3, "original_end": 0.4})
        self.prepare()
        plan = self.plan()
        apply_reference_changes(self.stage, plan)
        child = json.loads((self.stage / "tasks/child/task.json").read_bytes())
        self.assertEqual(child["learning_range"], {"start": 0.2, "end": 0.3, "original_start": 0.3, "original_end": 0.4})
        self.assertEqual(hashes(self.source), self.original_hashes)

    def test_range_validation_rejects_malformed_and_nonfinite_parents(self):
        context = MappingContext(self.source, self.snapshot, self.destination, {})
        child = {"id": "child", "learning_range": {"start": 0.2, "end": 0.3, "original_start": 0.3, "original_end": 0.4}}
        malformed = [
            {"start": 0.1, "end": float("nan")},
            {"start": 0.1, "end": float("inf")},
            {"start": 0.1, "end": "0.4"},
            {"start": False, "end": 0.4},
            {"start": -0.1, "end": 0.4},
            {"start": 0.4, "end": 0.1},
            {"start": 0.1},
            {"start": 0.1, "end": 0.4, "original_start": 0.1},
            {"start": 0.1, "end": 0.4, "original_start": float("-inf"), "original_end": 0.4},
            {"start": 0.1, "end": 0.4, "original_start": 0.4, "original_end": 0.1},
            {"start": 0.1, "end": 10 ** 400},
        ]
        for selected in malformed:
            with self.subTest(selected=selected), self.assertRaises(ReferenceMappingError) as caught:
                context._range_link(child, {"learning_range": selected, "media_integrity": {"duration": 0.4}}, "source_media_path")
            self.assertEqual(caught.exception.code, "ancestor_range_mismatch")
        # Equal child/parent dictionaries do not bypass finite shape validation.
        equal = {"start": 0.1, "end": float("inf")}
        with self.assertRaises(ReferenceMappingError):
            context._range_link({"id": "child", "learning_range": equal}, {"learning_range": equal}, "source_media_path")
        for duration in (0, -1, True, "0.4", float("nan"), float("inf"), 10 ** 400):
            with self.subTest(duration=duration), self.assertRaises(ReferenceMappingError):
                context._range_link(child, {"learning_range": {"start": 0.1, "end": 0.4}, "media_integrity": {"duration": duration}}, "source_media_path")

    def test_decimal_parent_interval_cannot_expand_by_float_rounding(self):
        context = MappingContext(self.source, self.snapshot, self.destination, {})
        parent = {"learning_range": {"start": 0.1, "end": 0.4, "original_start": 0.1, "original_end": 0.4},
                  "media_integrity": {"duration": 0.4}}
        child = {"id": "child", "learning_range": {"start": 0.2, "end": 0.30000000000000004,
                 "original_start": 0.3, "original_end": 0.4}}
        with self.assertRaises(ReferenceMappingError):
            context._range_link(child, parent, "source_media_path")

    def test_cross_task_subtitle_requires_caption_identity_and_matching_pointer(self):
        media = self.put("tasks/parent/source.mp4")
        subtitle = self.put("tasks/parent/source.srt")
        note = self.put("tasks/child/captions.md")
        transcript = self.put("tasks/child/transcript.json", b'{"segments": []}')
        sha = "a" * 64
        self.task("parent", media_path=media, subtitle_path=subtitle)
        self.task("child", source_task_id="parent", mode="subtitle_only", source_media_path=media, media_path=media,
                  subtitle_path=subtitle, note_path=note, transcript_path=transcript, summary_source="subtitle-extract",
                  options={"content_mode": "subtitles"}, media_integrity={"sha256": sha},
                  source_identity={"platform": "local", "platform_id": sha[:16], "media_sha256": sha, "resource_fingerprint": sha})
        self.prepare()
        self.assertTrue(any(item.get("json_pointer") == "/subtitle_path" and item["file"].startswith("tasks/child") for item in self.plan()["changes"]))
        self.payloads["child"]["source_identity"]["platform_id"] = "wrong"
        self.save_task("child")
        shutil.rmtree(self.snapshot)
        shutil.rmtree(self.stage)
        self.prepare()
        self.assert_blocked("subtitle_identity_mismatch")

    def test_exact_owned_upload_and_ambiguous_prefix_are_distinct(self):
        upload = self.put("uploads/task-a_original.mp4")
        self.task(source_media_path=upload)
        self.prepare()
        plan = self.plan()
        self.assertEqual(plan["changes"][0]["after"], str(self.destination / "uploads/task-a_original.mp4"))

    def test_catalog_only_enumerated_columns_change_and_values_survive(self):
        self.task(note_path=self.put("tasks/task-a/note.md"), media_path=self.put("tasks/task-a/source.mp4"))
        db = self.catalog(evidence=True, fts=True)
        original = self.insert_catalog_task(db)
        db.execute("INSERT INTO source_evidence VALUES (?,?,?,?,?,?,?,?,?,?)", ("evidence-1", 1, "video", "title", "source", "1s", "exact text", "task-a", '{"hash":"same"}', "then"))
        db.execute("INSERT INTO library_tasks_fts VALUES (?,?,?,?)", ("task-a", "title", "source", "unchanged fts"))
        db.commit()
        db.close()
        self.prepare()
        plan = self.plan()
        self.assertEqual(plan["catalog_proof"]["nonpath_before"], plan["catalog_proof"]["nonpath_after"])
        apply_reference_changes(self.stage, plan)
        with sqlite3.connect(self.stage / "library.sqlite3") as changed:
            row = changed.execute("SELECT * FROM library_tasks").fetchone()
            self.assertEqual(row[:9], original[:9])
            self.assertEqual(row[11:], original[11:])
            self.assertEqual(row[9], str(self.destination / "tasks/task-a/note.md"))
            self.assertEqual(changed.execute("SELECT text FROM source_evidence").fetchone()[0], "exact text")
            self.assertEqual(changed.execute("SELECT content FROM library_tasks_fts").fetchone()[0], "unchanged fts")
        self.assertEqual(hashes(self.source), self.original_hashes)
        self.assertEqual(hashes(self.snapshot), self.preview_hashes)

    def test_material_original_and_ocr_metadata_are_exactly_owned(self):
        key = "a" * 32
        original = b"synthetic pdf original"
        stored = self.put(f"materials/{key}/file.pdf", original)
        ocr = self.put(f"materials/{key}/ocr-{'b' * 64}.json", b'{"pages": []}')
        db = self.catalog()
        metadata = '{ "ocr_path" : ' + json.dumps(ocr) + ', "revision": "stay", "number": 1.000 }'
        row = (key, 1, "doc", "file.pdf", "pdf", "application/pdf", f"local://materials/{key}", digest(original), len(original),
               "ready", "", 0, "[]", 1, stored, metadata, "created", "updated")
        db.execute("INSERT INTO library_materials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        db.commit()
        db.close()
        self.prepare()
        plan = self.plan()
        self.assertEqual(len(plan["changes"]), 2)
        apply_reference_changes(self.stage, plan)
        with sqlite3.connect(self.stage / "library.sqlite3") as changed:
            result = changed.execute("SELECT * FROM library_materials").fetchone()
        self.assertEqual(result[:14], row[:14])
        self.assertEqual(result[16:], row[16:])
        self.assertEqual(result[15], metadata.replace(json.dumps(ocr), json.dumps(str(self.destination / f"materials/{key}/ocr-{'b' * 64}.json"))))
        self.assertEqual(plan["catalog_proof"]["nonpath_before"], plan["catalog_proof"]["nonpath_after"])

    def test_unknown_sql_schema_trigger_and_user_version_are_rejected(self):
        for sql in ("PRAGMA user_version=2", "CREATE TABLE unknown(path TEXT)",
                    "CREATE TRIGGER surprise AFTER UPDATE ON library_tasks BEGIN DELETE FROM library_meta; END"):
            with self.subTest(sql=sql):
                if self.snapshot.exists():
                    shutil.rmtree(self.snapshot)
                    shutil.rmtree(self.stage)
                    (self.source / "library.sqlite3").unlink()
                self.task()
                db = self.catalog()
                db.execute(sql)
                db.commit()
                db.close()
                self.prepare()
                self.assert_blocked()

    def test_wal_family_is_read_in_private_copy_and_consolidated_only_in_stage(self):
        self.task(note_path=self.put("tasks/task-a/note.md"))
        db = self.catalog(wal=True)
        self.insert_catalog_task(db)
        self.assertTrue((self.source / "library.sqlite3-wal").stat().st_size)
        self.prepare()
        plan = self.plan()
        self.assertIn("library.sqlite3-wal", plan["removed_paths"])
        self.assertIn("library.sqlite3-shm", plan["catalog_proof"]["original_family_sha256"])
        self.assertEqual(hashes(self.source), self.original_hashes)
        apply_reference_changes(self.stage, plan)
        self.assertFalse((self.stage / "library.sqlite3-wal").exists())
        self.assertFalse((self.stage / "library.sqlite3-shm").exists())
        with sqlite3.connect(self.stage / "library.sqlite3") as changed:
            self.assertEqual(changed.execute("SELECT note_path FROM library_tasks").fetchone()[0], str(self.destination / "tasks/task-a/note.md"))
            self.assertEqual(changed.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(hashes(self.source), self.original_hashes)

    def test_all_direct_task_and_diagnostic_pointer_slots_are_enumerated(self):
        fields = {
            "audio_path": "audio.wav", "subtitle_path": "subtitle.srt", "transcript_path": "transcript.json",
            "media_integrity_path": "media_integrity.json", "evidence_coverage_path": "evidence_coverage.json",
            "resource_inventory_path": "resource_inventory.json", "resource_usage_path": "resource_usage.json",
            "page_preflight_report_path": "page_preflight_report.json",
        }
        values = {key: self.put("tasks/task-a/" + name, b"{}" if name.endswith(".json") else b"artifact") for key, name in fields.items()}
        diagnostic = {key: self.put("tasks/task-a/" + key.removesuffix("_path") + ".json", b"{}")
                      for key in ("note_quality_path", "note_document_path", "claim_evidence_map_path", "transcript_quality_path")}
        self.task(**values, summary_diagnostics=diagnostic, frame_grids=[{"frame_paths": [], "important_frame_paths": []}])
        self.prepare()
        plan = self.plan()
        self.assertEqual(len(plan["changes"]), len(fields) + len(diagnostic))
        apply_reference_changes(self.stage, plan)

    def test_unknown_app_metadata_reference_is_not_silently_left_behind(self):
        self.task()
        self.put("preferences.json", json.dumps({"future_uri": str(self.source / "tasks/task-a/task.json")}).encode())
        self.prepare()
        self.assert_blocked("unsupported_reference_schema")

    def test_unknown_selected_root_pointer_with_repeated_separator_blocks(self):
        self.task()
        pointer = str(self.source / "tasks/task-a/task.json")
        pointer = pointer.replace(os.sep + "original" + os.sep, os.sep * 2 + "original" + os.sep, 1)
        self.put("preferences.json", json.dumps({"future_uri": pointer}).encode())
        self.prepare()
        self.assert_blocked("unsupported_reference_schema")

    def test_unknown_absolute_aliases_are_rejected_without_probing_them(self):
        self.task()
        entered = str(self.base / "outside") + os.sep + ".." + os.sep + "original" + os.sep + "tasks" + os.sep + "task-a" + os.sep + "task.json"
        leading = os.sep + str(self.source / "tasks/task-a/task.json")
        variants = [entered]
        if os.name != "nt":
            variants.append(leading)
        real_open = os.open
        for value in variants:
            with self.subTest(value=value):
                if self.snapshot.exists():
                    shutil.rmtree(self.snapshot)
                    shutil.rmtree(self.stage)
                self.put("preferences.json", json.dumps({"future_uri": value}).encode())
                self.prepare()
                before_stage = hashes(self.stage)
                def snapshot_only_lstat(path, *args, **kwargs):
                    if path != self.snapshot and path not in self.snapshot.parents and not path.is_relative_to(self.snapshot):
                        raise AssertionError("recorded/original pointer was probed")
                    return os.stat(path, follow_symlinks=False)
                def snapshot_only_open(path, *args, **kwargs):
                    if not Path(path).is_relative_to(self.snapshot):
                        raise AssertionError("recorded/original pointer was opened")
                    return real_open(path, *args, **kwargs)
                with patch.object(Path, "lstat", snapshot_only_lstat), \
                        patch.object(Path, "stat", side_effect=AssertionError("recorded pointer stat")), \
                        patch("os.open", snapshot_only_open), \
                        self.assertRaises(ReferenceMappingError) as caught:
                    self.plan()
                self.assertEqual(caught.exception.code, "unsupported_reference_schema")
                self.assertEqual(hashes(self.source), self.original_hashes)
                self.assertEqual(hashes(self.snapshot), self.preview_hashes)
                self.assertEqual(hashes(self.stage), before_stage)
                self.assertFalse(self.destination.exists())

    def test_ambiguous_absolute_reference_rejection_is_purely_lexical(self):
        cases = [
            ("/tmp/selected/data", "/tmp/outside/../selected/data/task.json"),
            ("/tmp/selected/data", "//tmp/selected/data/task.json"),
            ("/tmp/selected/data", "///tmp/selected/data/task.json"),
            ("/tmp/selected/data", "/unrelated/../file.json"),
            (r"C:\Selected\Data", r"c:\outside\..\Selected\Data\task.json"),
            (r"C:\Selected\Data", "c:/outside/../Selected/Data/task.json"),
            (r"C:\Selected\Data", r"\\?\C:\Selected\Data\task.json"),
        ]
        with patch.object(Path, "stat", side_effect=AssertionError("no stat")), \
                patch.object(Path, "lstat", side_effect=AssertionError("no lstat")), \
                patch("os.open", side_effect=AssertionError("no open")):
            for source, value in cases:
                with self.subTest(source=source, value=value):
                    self.assertTrue(_lexically_under_source(value, source))
                    self.assertFalse(_lexically_under_source("text mentioning " + value, source))

    def test_unknown_windows_reference_detection_is_case_and_slash_aware(self):
        source = r"C:\Data"
        references = [r"c:\data\tasks\task-a\note.md", "c:/DATA/tasks/task-a/note.md",
                      r"C:\Data/tasks/task-a/note.md", "C:/data", r"C:\DATA\tasks\..\elsewhere"]
        with patch.object(Path, "stat", side_effect=AssertionError("no recorded-pointer stat")), \
                patch.object(Path, "lstat", side_effect=AssertionError("no recorded-pointer lstat")), \
                patch("os.open", side_effect=AssertionError("no recorded-pointer open")):
            for value in references:
                with self.subTest(value=value):
                    self.assertTrue(_lexically_under_source(value, source))
            for value in (r"C:\Database\tasks\task-a\note.md", "C:/Data-other/tasks/task-a/note.md",
                          r"D:\Data\tasks\task-a\note.md", "text mentioning C:/Data/tasks/task-a/note.md",
                          "https://example.invalid/C:/Data/tasks/task-a/note.md", r"C:Data\tasks\task-a\note.md"):
                with self.subTest(value=value):
                    self.assertFalse(_lexically_under_source(value, source))
        self.assertTrue(_lexically_under_source("/selected/data/tasks/task-a/note.md", "/selected/data"))
        self.assertFalse(_lexically_under_source("/selected/database/tasks/task-a/note.md", "/selected/data"))
        self.assertFalse(_lexically_under_source("text mentioning /selected/data/note.md", "/selected/data"))

    def test_unrecognized_nonpath_metadata_is_preserved_even_as_array(self):
        self.task()
        raw = b'[ {"id": "unchanged", "score": 1.000}, false, null ]\n'
        self.put("tasks/task-a/extra-metadata.json", raw)
        self.prepare()
        apply_reference_changes(self.stage, self.plan())
        self.assertEqual((self.stage / "tasks/task-a/extra-metadata.json").read_bytes(), raw)

    def test_cross_task_media_cannot_switch_to_an_unrecorded_owned_file(self):
        media = self.put("tasks/parent/source.mp4")
        other = self.put("tasks/parent/other.mp4")
        self.task("parent", media_path=media)
        self.task("child", source_task_id="parent", mode="rerun_from_media", source_media_path=other)
        self.prepare()
        self.assert_blocked("ancestor_pointer_mismatch")

    def test_material_identity_filename_ownership_and_hash_fail_closed(self):
        cases = [("not-uuid", "file.pdf", "owned", "correct"), ("a" * 32, "../file.pdf", "owned", "correct"),
                 ("a" * 32, "file.pdf", "foreign", "correct"), ("a" * 32, "file.pdf", "owned", "wrong")]
        for key, filename, owner, checksum in cases:
            with self.subTest(key=key, filename=filename, owner=owner, checksum=checksum):
                if self.snapshot.exists():
                    shutil.rmtree(self.snapshot)
                    shutil.rmtree(self.stage)
                    (self.source / "library.sqlite3").unlink()
                raw = b"original"
                stored = self.put(f"materials/{key}/file.pdf", raw)
                if owner == "foreign":
                    stored = str(self.base / "foreign/materials" / key / "file.pdf")
                db = self.catalog()
                row = (key, 1, "doc", filename, "pdf", "application/pdf", f"local://materials/{key}",
                       digest(raw) if checksum == "correct" else "f" * 64, len(raw), "ready", "", 0, "[]", 1, stored, "{}", "created", "updated")
                db.execute("INSERT INTO library_materials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
                db.commit()
                db.close()
                self.prepare()
                self.assert_blocked()

    def test_copied_catalog_never_opens_source_sqlite(self):
        self.task(note_path=self.put("tasks/task-a/note.md"))
        db = self.catalog()
        self.insert_catalog_task(db)
        db.close()
        self.prepare()
        real_connect = sqlite3.connect
        def only_disposable(database, *args, **kwargs):
            if str(self.source) in str(database) or str(self.snapshot) in str(database) or str(self.stage) in str(database):
                raise AssertionError("catalog must open only private copies")
            return real_connect(database, *args, **kwargs)
        with patch("sqlite3.connect", only_disposable):
            plan = self.plan()
            apply_reference_changes(self.stage, plan)
        self.assertEqual(hashes(self.source), self.original_hashes)

    @unittest.skipUnless(hasattr(os, "link"), "hardlinks unavailable")
    def test_linked_staged_metadata_cannot_mutate_source(self):
        self.task(note_path=self.put("tasks/task-a/note.md"))
        self.prepare()
        plan = self.plan()
        path = self.stage / "tasks/task-a/task.json"
        path.unlink()
        os.link(self.source / "tasks/task-a/task.json", path)
        before = hashes(self.stage)
        with self.assertRaises(ReferenceMappingError) as caught:
            apply_reference_changes(self.stage, plan)
        self.assertEqual(caught.exception.code, "linked_or_changed_stage")
        self.assertEqual(hashes(self.stage), before)
        self.assertEqual(hashes(self.source), self.original_hashes)

    def test_rollback_journal_never_reaches_sqlite_recovery(self):
        db = self.catalog()
        db.close()
        for raw in (b"", b"hot rollback journal with /outside/super-journal pointer"):
            with self.subTest(raw=raw):
                if self.snapshot.exists():
                    shutil.rmtree(self.snapshot)
                    shutil.rmtree(self.stage)
                self.put("library.sqlite3-journal", raw)
                self.prepare()
                with patch("sqlite3.connect", side_effect=AssertionError("rollback recovery must never run")):
                    self.assert_blocked("catalog_rollback_recovery_required")
                self.assertEqual(hashes(self.stage), self.preview_hashes)

    def test_orphaned_catalog_family_is_rejected(self):
        self.put("library.sqlite3-wal", b"not a complete stopped family")
        self.prepare()
        self.assert_blocked("catalog_family_incomplete")


if __name__ == "__main__":
    unittest.main()
