from __future__ import annotations

from contextlib import ExitStack, closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import StudyCard
from app.study import save_cards


class LearningBackupCompletenessTests(unittest.TestCase):
    """A successful backup must include every recognized personal-data file."""

    @contextmanager
    def _local_client(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            for module in ("app.study", "app.personal_notes", "app.routers.notes"):
                stack.enter_context(patch(f"{module}.DATA_DIR", root))
            stack.enter_context(patch("app.study.ensure_dirs", return_value=None))
            client = TestClient(app, raise_server_exceptions=False)
            stack.callback(client.close)
            response = client.put("/api/study/plan", json={
                "title": "Synthetic export plan", "daily_target": 7,
                "paused": False, "timezone": "Asia/Shanghai",
            })
            self.assertEqual(response.status_code, 200, response.text)
            response = client.post("/api/study/activity", json={
                "kind": "reading", "source_id": "task:synthetic",
                "idempotency_key": "synthetic-reading",
            })
            self.assertEqual(response.status_code, 200, response.text)
            save_cards([StudyCard(card_id="synthetic-card", front="Question", back="Answer")])
            response = client.post("/api/study/cards/synthetic-card/review", json={
                "rating": 3, "idempotency_key": "synthetic-review",
            })
            self.assertEqual(response.status_code, 200, response.text)
            yield root, client

    def _write(self, root, relative, content):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def _annotation(self, annotation_id="synthetic-note", text="Synthetic personal note"):
        return {"id": annotation_id, "text": text, "quote": "Exact source quote", "anchor": {}}

    def _edition(self, source_id="synthetic", text="Synthetic edition"):
        return {
            "key": hashlib.sha256(f"task:{source_id}".encode("utf-8")).hexdigest(),
            "value": {
                "text": text, "revision": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "edited": True,
            },
        }

    def _healthy_files(self, root):
        annotation = self._annotation()
        edition = self._edition()
        self._write(root, "personal-notes/task-first.json", json.dumps({
            "schema_version": 2, "annotations": [annotation],
        }, indent=4) + "\n")
        self._write(root, f"user-editions/{edition['key']}.json", json.dumps(edition["value"], indent=4) + "\n")
        return annotation, edition

    def _state(self, root):
        # Record links themselves, never traverse them; include their synthetic
        # referents separately. Lock files are coordination, not personal data.
        files = {}

        def visit(path):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                files[relative] = ("symlink", str(path.readlink()))
            elif path.is_dir():
                files[relative] = ("directory",)
                for child in sorted(path.iterdir()):
                    visit(child)
            elif path.exists():
                files[relative] = ("file", path.read_bytes())

        for name in ("personal-notes", "user-editions", "personal-state/restore-pending", "outside", "outside.json"):
            visit(root / name)
        with closing(sqlite3.connect(root / "study.sqlite3")) as connection:
            study = tuple(connection.iterdump())
        return files, study

    def _assert_rejected_without_changes(self, root, client):
        before = self._state(root)
        for attempt in range(2):
            response = client.get("/api/study/backup")
            self.assertEqual(self._state(root), before, f"Export attempt {attempt} changed local data")
            self.assertIn(response.status_code, (409, 422), response.text)
            body = response.json()
            self.assertIsInstance(body.get("detail"), dict, response.text)
            self.assertTrue(body["detail"].get("code"), response.text)
            self.assertTrue(body["detail"].get("message"), response.text)
            self.assertNotIn("study", body, "Rejected backups must not contain a usable partial payload")
            self.assertNotIn("personal", body, "Rejected backups must not contain a usable partial payload")
            self.assertNotIn("exported_at", body)
        return response

    def test_future_annotation_schemas_are_not_exported_as_supported(self):
        for version in (999, "2", True):
            with self.subTest(version=version), self._local_client() as (root, client):
                self._healthy_files(root)
                self._write(root, "personal-notes/task-last.json", json.dumps({
                    "schema_version": version, "annotations": [self._annotation("future-note")],
                    "future_format": {"must_survive": "Synthetic future content"},
                }))
                self._assert_rejected_without_changes(root, client)

    def test_malformed_recognized_annotations_cannot_silently_disappear(self):
        malformed = {
            "truncated_json": b'{"schema_version":2,"annotations":[',
            "wrong_root": b"[]\n",
            "invalid_utf8": b"\xff\xfe",
            "unpaired_unicode_surrogate": b'{"annotations":[{"id":"note","text":"\\ud800"}]}',
            "missing_annotations": b'{"schema_version":2}',
            "wrong_annotations_type": b'{"schema_version":2,"annotations":{}}',
            "non_object_item": b'{"annotations":["Synthetic note"]}',
            "numeric_id": b'{"annotations":[{"id":123,"text":"Synthetic note"}]}',
            "numeric_text": b'{"annotations":[{"id":"note","text":123}]}',
            "duplicate_field": b'{"annotations":[{"id":"note","text":"Keep this"}],"annotations":[]}',
            "duplicate_item_field": b'{"annotations":[{"id":"note","text":"Keep this","text":"Replacement"}]}',
            "duplicate_note_id": b'{"annotations":[{"id":"note","text":"First"},{"id":"note","text":"Second"}]}',
            "non_finite_constant": b'{"annotations":[],"metadata":NaN}',
        }
        for name, content in malformed.items():
            with self.subTest(name=name), self._local_client() as (root, client):
                self._healthy_files(root)
                self._write(root, "personal-notes/task-last.json", content)
                self._assert_rejected_without_changes(root, client)

    def test_malformed_recognized_editions_cannot_silently_disappear(self):
        valid = self._edition("broken")
        revision = valid["value"]["revision"]
        malformed = {
            "truncated_json": b"{",
            "wrong_root": b"[]",
            "invalid_utf8": b"\xff",
            "bad_revision_hash": json.dumps({**valid["value"], "revision": "0" * 64}),
            "non_boolean_edited": json.dumps({**valid["value"], "edited": "false"}),
            "future_schema": json.dumps({**valid["value"], "schema_version": 999}),
            "duplicate_text": '{"text":"Lost edition","text":"Synthetic edition",'
                              f'"revision":"{revision}","edited":true}}',
        }
        for name, content in malformed.items():
            with self.subTest(name=name), self._local_client() as (root, client):
                self._healthy_files(root)
                self._write(root, f"user-editions/{valid['key']}.json", content)
                self._assert_rejected_without_changes(root, client)

    def test_directory_and_symlink_file_targets_are_rejected(self):
        for kind in ("annotation", "edition"):
            for target_kind in ("directory", "symlink", "dangling_symlink"):
                with self.subTest(kind=kind, target_kind=target_kind), self._local_client() as (root, client):
                    self._healthy_files(root)
                    relative = "personal-notes/task-last.json"
                    content = json.dumps({"annotations": [self._annotation("linked-note")]})
                    if kind == "edition":
                        edition = self._edition("linked")
                        relative = f"user-editions/{edition['key']}.json"
                        content = json.dumps(edition["value"])
                    target = root / relative
                    if target_kind == "directory":
                        target.mkdir()
                        (target / "preserve.bin").write_bytes(b"Synthetic directory contents\n")
                    else:
                        referent = root / "outside.json"
                        if target_kind == "symlink":
                            referent.write_text(content, encoding="utf-8")
                        try:
                            target.symlink_to(referent)
                        except (NotImplementedError, OSError) as exc:
                            self.skipTest(f"Test symlinks unavailable: {exc}")
                    self._assert_rejected_without_changes(root, client)

    def test_unsafe_personal_storage_roots_are_rejected(self):
        for name in ("personal-notes", "user-editions"):
            for root_kind in ("file", "symlink", "dangling_symlink"):
                with self.subTest(name=name, root_kind=root_kind), self._local_client() as (root, client):
                    target = root / name
                    if root_kind == "file":
                        target.write_bytes(b"Synthetic unexpected root file\n")
                    else:
                        outside = root / "outside"
                        if root_kind == "symlink":
                            outside.mkdir()
                            if name == "personal-notes":
                                self._write(outside, "task-linked.json", json.dumps({"annotations": [self._annotation()]}))
                            else:
                                edition = self._edition()
                                self._write(outside, f"{edition['key']}.json", json.dumps(edition["value"]))
                        try:
                            target.symlink_to(outside, target_is_directory=True)
                        except (NotImplementedError, OSError) as exc:
                            self.skipTest(f"Test symlinks unavailable: {exc}")
                    self._assert_rejected_without_changes(root, client)

    def test_pending_recovery_blocks_export_and_preserves_original_copies(self):
        for kind in ("directory", "file", "dangling_symlink"):
            with self.subTest(kind=kind), self._local_client() as (root, client):
                self._healthy_files(root)
                pending = root / "personal-state" / "restore-pending"
                pending.parent.mkdir(parents=True, exist_ok=True)
                if kind == "directory":
                    pending.mkdir()
                    (pending / "0.original").write_bytes(b"Exact synthetic pre-restore bytes\r\n")
                    (pending / "manifest.json").write_bytes(b'{"status":"prepared","files":[]}\n')
                elif kind == "file":
                    pending.write_bytes(b"Synthetic recovery marker\n")
                else:
                    try:
                        pending.symlink_to(root / "outside", target_is_directory=True)
                    except (NotImplementedError, OSError) as exc:
                        self.skipTest(f"Test symlinks unavailable: {exc}")
                response = self._assert_rejected_without_changes(root, client)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["detail"]["code"], "personal_restore_recovery_required")

    def test_supported_legacy_and_current_files_preserve_literal_text_and_bytes(self):
        for version in (None, 1, 2):
            with self.subTest(version=version), self._local_client() as (root, client):
                text = '  <script>literal()</script> & "quoted"\r\n中文笔记\n\tTrailing spaces  '
                quote = '  "Exact quote"\r\n第二行  '
                annotation = {**self._annotation(text=text), "quote": quote,
                              "anchor": {"source_revision": "synthetic-revision", "selected_text": quote},
                              "request_id": "synthetic-request"}
                envelope = {"annotations": [annotation]}
                if version is not None:
                    envelope["schema_version"] = version
                self._write(root, "personal-notes/task-synthetic.json", json.dumps(envelope, ensure_ascii=False, indent=4).replace("\n", "\r\n") + "\r\n")
                self._write(root, "personal-notes/material-synthetic.json", '{"schema_version":2,"annotations":[]}\n')
                edition = self._edition(text=text + "\r\nFinal edition line\r")
                self._write(root, f"user-editions/{edition['key']}.json", json.dumps(edition["value"], ensure_ascii=False, indent=4) + "\n")
                before = self._state(root)
                for attempt in range(2):
                    response = client.get("/api/study/backup")
                    self.assertEqual(response.status_code, 200, response.text)
                    backup = response.json()
                    self.assertEqual(backup["personal"], {
                        "annotations": [{"key": "material-synthetic", "items": []},
                                        {"key": "task-synthetic", "items": [annotation]}],
                        "editions": [edition],
                    })
                    self.assertEqual(backup["study"]["plan"]["title"], "Synthetic export plan")
                    self.assertEqual(len(backup["study"]["cards"]), 1)
                    self.assertEqual(len(backup["study"]["reviews"]), 1)
                    self.assertTrue(backup["study"]["activity_events"])
                    self.assertEqual(self._state(root), before, f"Successful export attempt {attempt} changed source data")

    def test_repairing_only_the_invalid_fixture_allows_a_complete_retry(self):
        for kind in ("annotation", "edition"):
            with self.subTest(kind=kind), self._local_client() as (root, client):
                annotation, edition = self._healthy_files(root)
                repaired_annotation = self._annotation("repaired-note", "Exact repaired synthetic note\r\n")
                repaired_edition = self._edition("repaired", "Exact repaired synthetic edition\r\n")
                relative = "personal-notes/task-last.json" if kind == "annotation" else f"user-editions/{repaired_edition['key']}.json"
                self._write(root, relative, b"{")
                self._assert_rejected_without_changes(root, client)
                repaired = {"schema_version": 2, "annotations": [repaired_annotation]} if kind == "annotation" else repaired_edition["value"]
                self._write(root, relative, json.dumps(repaired, ensure_ascii=False, indent=4) + "\n")
                before = self._state(root)
                expected = {"annotations": [{"key": "task-first", "items": [annotation]}], "editions": [edition]}
                if kind == "annotation":
                    expected["annotations"].append({"key": "task-last", "items": [repaired_annotation]})
                else:
                    expected["editions"] = sorted([edition, repaired_edition], key=lambda item: item["key"])
                for attempt in range(2):
                    response = client.get("/api/study/backup")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["personal"], expected)
                    self.assertEqual(self._state(root), before, f"Retry {attempt} changed repaired data")

    def test_unrelated_files_do_not_block_otherwise_complete_export(self):
        with self._local_client() as (root, client):
            annotation, edition = self._healthy_files(root)
            self._write(root, "personal-notes/README.json", b"Unrelated non-personal file")
            self._write(root, "personal-notes/task-unrelated.json.tmp", b"Synthetic temp bytes")
            self._write(root, "user-editions/README.json", b"Unrelated non-edition file")
            before = self._state(root)
            response = client.get("/api/study/backup")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["personal"], {
                "annotations": [{"key": "task-first", "items": [annotation]}], "editions": [edition],
            })
            self.assertEqual(self._state(root), before)


if __name__ == "__main__":
    unittest.main()
