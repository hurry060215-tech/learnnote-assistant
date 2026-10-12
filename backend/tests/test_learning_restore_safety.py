from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.storage import atomic_write_text


class LearningRestoreSafetyTests(unittest.TestCase):
    """Restore failures must preserve real local files and all study rows."""

    @contextmanager
    def _local_client(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            for module in ("app.study", "app.personal_notes", "app.routers.notes"):
                stack.enter_context(patch(f"{module}.DATA_DIR", root))
            # Study's normal initializer also creates unrelated application
            # directories. Every path this fixture uses already lives in root.
            stack.enter_context(patch("app.study.ensure_dirs", return_value=None))
            client = TestClient(app, raise_server_exceptions=False)
            stack.callback(client.close)
            response = client.put("/api/study/plan", json={
                "title": "Existing local plan", "daily_target": 7,
                "paused": False, "timezone": "Asia/Shanghai",
            })
            self.assertEqual(response.status_code, 200, response.text)
            response = client.post("/api/study/activity", json={
                "kind": "reading", "source_id": "task:local",
                "idempotency_key": "local-reading",
            })
            self.assertEqual(response.status_code, 200, response.text)
            yield root, client

    def _annotation(self, annotation_id="backup-note", text="Saved personal note"):
        return {"id": annotation_id, "text": text, "quote": "Source quote", "anchor": {}}

    def _edition(self, source_id, text="Saved user edition"):
        return {
            "key": hashlib.sha256(f"task:{source_id}".encode()).hexdigest(),
            "value": {
                "text": text, "revision": hashlib.sha256(text.encode()).hexdigest(),
                "edited": True,
            },
        }

    def _backup(self, client, keys=("task-synthetic",)):
        response = client.get("/api/study/backup")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        payload["study"].update({
            "cards": [{
                "card_id": "backup-card", "front": "Synthetic question",
                "back": "Synthetic answer", "source_evidence_ids": [],
                "status": "active", "due_at": "2026-01-02T00:00:00+00:00",
            }],
            "reviews": [{
                "card_id": "backup-card", "rating": 3,
                "reviewed_at": "2026-01-01T00:00:00+00:00",
                "due_at": "2026-01-02T00:00:00+00:00",
                "stability": 1.0, "difficulty": 5.0,
                "idempotency_key": "backup-review",
            }],
            "activity_events": [{
                "kind": "answer", "source_id": "card:backup-card",
                "occurred_at": "2026-01-01T00:00:00+00:00",
                "idempotency_key": "backup-answer",
            }],
            "quiz_attempts": [],
        })
        # Ensure a successful restore would change the plan, making rollback
        # assertions meaningful even on an already customized destination.
        payload["study"]["plan"].update({
            "title": "Plan from backup", "daily_target": 19,
            "timezone": "Europe/London", "timezone_initialized": True,
            "updated_at": "2099-01-01T00:00:00+00:00",
        })
        payload["personal"] = {
            "annotations": [{"key": key, "items": [self._annotation()]} for key in keys],
            "editions": [],
        }
        return payload

    def _write(self, root, relative, content):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def _state(self, root):
        files = {
            str(path.relative_to(root)): path.read_bytes()
            for name in ("personal-notes", "user-editions")
            for path in (root / name).rglob("*") if path.is_file()
        }
        with closing(sqlite3.connect(root / "study.sqlite3")) as connection:
            # A logical dump includes plan, activity, cards, review history,
            # quiz rows and their sequences, without relying on SQLite page
            # layout or journal bytes remaining identical after rollback.
            study = tuple(connection.iterdump())
        return files, study

    def _assert_invalid_without_changes(self, root, client, payload):
        before = self._state(root)
        with patch("app.personal_notes.atomic_write_text", wraps=atomic_write_text) as write:
            response = client.post("/api/study/backup/restore", json=payload)
        self.assertEqual(self._state(root), before, f"Restore mutated local state: {response.text}")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertTrue(response.json().get("detail"), response.text)
        write.assert_not_called()

    def test_future_annotation_schema_is_rejected_without_downgrade(self):
        for local_id in ("local-note", "backup-note"):
            with self.subTest(local_id=local_id), self._local_client() as (root, client):
                payload = self._backup(client)
                future = {
                    "schema_version": 999, "annotations": [self._annotation(local_id)],
                    "future_format": {"must_survive": ["unrecognized", "local data"]},
                }
                self._write(root, "personal-notes/task-synthetic.json", json.dumps(future, indent=4) + "\n")
                self._assert_invalid_without_changes(root, client, payload)

    def test_malformed_annotation_destinations_are_not_overwritten_or_skipped(self):
        malformed = {
            "list_root": b"[]\n",
            "truncated_json": b'{"schema_version": 2, "annotations": [',
            "invalid_utf8": b"\xff\xfe",
            "missing_items": b'{"schema_version": 2}',
            "wrong_items_type": b'{"schema_version": 2, "annotations": {}}',
            "non_object_item": b'{"schema_version": 2, "annotations": ["keep me"]}',
            "invalid_item": b'{"schema_version": 2, "annotations": [{"id": "local", "text": 42}]}',
            "numeric_id": b'{"schema_version": 2, "annotations": [{"id": 123, "text": "Local note"}]}',
            "duplicate_field": b'{"schema_version":2,"annotations":[{"id":"local","text":"Keep this note"}],"annotations":[]}',
            "non_finite_constant": b'{"schema_version":2,"annotations":[],"unrecognized_metadata":NaN}',
        }
        for name, content in malformed.items():
            with self.subTest(name=name), self._local_client() as (root, client):
                payload = self._backup(client)
                self._write(root, "personal-notes/task-synthetic.json", content)
                self._assert_invalid_without_changes(root, client, payload)

    def test_late_invalid_target_preserves_earlier_groups_and_study(self):
        with self._local_client() as (root, client):
            payload = self._backup(client, ("task-first", "task-new", "task-last"))
            self._write(root, "personal-notes/task-first.json", json.dumps({
                "schema_version": 2, "annotations": [self._annotation("local-note")],
            }, indent=4) + "\n")
            self._write(root, "personal-notes/task-last.json", b'{"schema_version":999,"annotations":[]}\n')
            self._assert_invalid_without_changes(root, client, payload)

    def test_late_annotation_capacity_error_does_not_partially_restore(self):
        with self._local_client() as (root, client):
            payload = self._backup(client, ("task-first", "task-full"))
            self._write(root, "personal-notes/task-first.json", '{"schema_version":2,"annotations":[]}\n')
            self._write(root, "personal-notes/task-full.json", json.dumps({
                "schema_version": 2,
                "annotations": [self._annotation(f"local-{index}") for index in range(500)],
            }))
            self._assert_invalid_without_changes(root, client, payload)

    def test_malformed_late_edition_preserves_annotations_and_study(self):
        for content in (b"{", b"[]", b'{"text":"local edition","revision":"incorrect","edited":true}'):
            with self.subTest(content=content), self._local_client() as (root, client):
                payload = self._backup(client)
                edition = self._edition("synthetic")
                payload["personal"]["editions"] = [edition]
                self._write(root, f"user-editions/{edition['key']}.json", content)
                self._assert_invalid_without_changes(root, client, payload)

    def test_duplicate_annotation_groups_are_rejected_before_writing(self):
        with self._local_client() as (root, client):
            payload = self._backup(client)
            payload["personal"]["annotations"].append({
                "key": "task-synthetic", "items": [self._annotation("second-note")],
            })
            self._assert_invalid_without_changes(root, client, payload)

    def test_duplicate_edition_keys_are_rejected_before_writing(self):
        with self._local_client() as (root, client):
            payload = self._backup(client)
            payload["personal"]["editions"] = [
                self._edition("synthetic", "First copy"),
                self._edition("synthetic", "Conflicting copy"),
            ]
            self._assert_invalid_without_changes(root, client, payload)

    def test_directory_destinations_are_rejected_without_changing_the_batch(self):
        for kind in ("annotation", "edition"):
            with self.subTest(kind=kind), self._local_client() as (root, client):
                payload = self._backup(client)
                relative = "personal-notes/task-synthetic.json"
                if kind == "edition":
                    edition = self._edition("synthetic")
                    payload["personal"]["editions"] = [edition]
                    relative = f"user-editions/{edition['key']}.json"
                target = root / relative
                target.mkdir(parents=True)
                sentinel = target / "do-not-delete.bin"
                sentinel.write_bytes(b"An existing directory must stay untouched.\n")
                self._assert_invalid_without_changes(root, client, payload)
                self.assertTrue(target.is_dir())
                self.assertEqual(sentinel.read_bytes(), b"An existing directory must stay untouched.\n")

    def test_symlink_destinations_are_rejected_without_touching_the_referent(self):
        for kind in ("annotation", "edition"):
            with self.subTest(kind=kind), self._local_client() as (root, client):
                payload = self._backup(client)
                relative = "personal-notes/task-synthetic.json"
                content = json.dumps({"schema_version": 2, "annotations": []})
                if kind == "edition":
                    edition = self._edition("synthetic")
                    payload["personal"]["editions"] = [edition]
                    relative = f"user-editions/{edition['key']}.json"
                    content = json.dumps(edition["value"])
                referent = self._write(root, "outside-personal-storage.json", content + "\n")
                original = referent.read_bytes()
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.symlink_to(referent)
                except (NotImplementedError, OSError) as exc:
                    self.skipTest(f"This platform cannot create test symlinks: {exc}")
                self._assert_invalid_without_changes(root, client, payload)
                self.assertTrue(target.is_symlink())
                self.assertEqual(referent.read_bytes(), original)

    def test_late_write_failure_rolls_back_files_and_study_and_can_retry(self):
        for failure_at, fail_after_replace in ((2, False), (4, False), (2, True)):
            with self.subTest(failure_at=failure_at, fail_after_replace=fail_after_replace), self._local_client() as (root, client):
                payload = self._backup(client, ("task-existing", "task-new"))
                payload["personal"]["editions"] = [self._edition("one"), self._edition("two")]
                self._write(root, "personal-notes/task-existing.json", json.dumps({
                    "schema_version": 2, "annotations": [self._annotation("local-note")],
                }, indent=4) + "\n")
                before = self._state(root)
                completed = []
                attempted = 0
                injected = False

                def fail_once(path, text):
                    nonlocal attempted, injected
                    attempted += 1
                    if attempted == failure_at:
                        if fail_after_replace:
                            atomic_write_text(path, text)
                        injected = True
                        raise OSError("Synthetic disk write failure")
                    atomic_write_text(path, text)
                    completed.append(Path(path))

                with patch("app.personal_notes.atomic_write_text", side_effect=fail_once):
                    response = client.post("/api/study/backup/restore", json=payload)
                self.assertTrue(injected, "The test must reach the intended write failure")
                self.assertTrue(completed, "At least one real write must precede the failure")
                self.assertIn(response.status_code, (422, 500), response.text)
                self.assertEqual(self._state(root), before, "A failed restore left partial files or study rows")

                retry = client.post("/api/study/backup/restore", json=payload)
                self.assertEqual(retry.status_code, 200, retry.text)
                self.assertEqual(retry.json()["merge"]["restored_annotations"], 2)
                self.assertEqual(retry.json()["merge"]["restored_editions"], 2)
                restored = self._state(root)
                repeated = client.post("/api/study/backup/restore", json=payload)
                self.assertEqual(repeated.status_code, 200, repeated.text)
                self.assertTrue(all(count == 0 for count in repeated.json()["merge"].values()))
                self.assertEqual(self._state(root), restored)

    def test_study_commit_failure_rolls_back_already_written_personal_files(self):
        from app import study

        with self._local_client() as (root, client):
            payload = self._backup(client, ("task-existing", "task-new"))
            payload["personal"]["editions"] = [self._edition("synthetic")]
            self._write(root, "personal-notes/task-existing.json", json.dumps({
                "schema_version": 2, "annotations": [self._annotation("local-note")],
            }, indent=4) + "\n")
            before = self._state(root)
            connect = study._connect

            class FailingCommit:
                def __init__(self):
                    self.connection = connect()

                def __getattr__(self, name):
                    return getattr(self.connection, name)

                def commit(self):
                    raise sqlite3.OperationalError("Synthetic study commit failure")

            with patch("app.study._connect", side_effect=FailingCommit), patch(
                "app.personal_notes.atomic_write_text", wraps=atomic_write_text,
            ) as write:
                response = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(write.call_count, 3, "The commit failure must occur after personal files were written")
            self.assertEqual(response.status_code, 500, response.text)
            self.assertEqual(self._state(root), before)
            retry = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(retry.status_code, 200, retry.text)

    def test_rollback_conflict_preserves_newer_external_edit_and_original_recovery_copy(self):
        with self._local_client() as (root, client):
            payload = self._backup(client, ("task-existing", "task-new"))
            original = json.dumps({
                "schema_version": 2, "annotations": [self._annotation("local-note")],
            }, indent=4).encode("utf-8") + b"\n"
            path = self._write(root, "personal-notes/task-existing.json", original)
            newer = json.dumps({
                "schema_version": 2,
                "annotations": [self._annotation("local-note", "Newer edit from another file editor")],
            }, indent=4).encode("utf-8") + b"\n"
            before = self._state(root)
            completed = []

            def change_earlier_target_then_fail(target, text):
                if completed:
                    path.write_bytes(newer)
                    raise OSError("Synthetic late write failure after an outside edit")
                atomic_write_text(target, text)
                completed.append(Path(target))

            with patch("app.personal_notes.atomic_write_text", side_effect=change_earlier_target_then_fail):
                response = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(len(completed), 1)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["detail"]["code"], "personal_restore_recovery_required")
            self.assertEqual(path.read_bytes(), newer, "Rollback must not overwrite a newer outside edit")
            self.assertFalse((root / "personal-notes/task-new.json").exists())
            self.assertEqual(self._state(root)[1], before[1])
            pending = root / "personal-state" / "restore-pending"
            recovery = {str(item.relative_to(pending)): item.read_bytes() for item in pending.rglob("*") if item.is_file()}
            self.assertIn(original, recovery.values(), "The original must remain recoverable after rollback is blocked")
            blocked_state = self._state(root)
            retry = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(retry.status_code, 409, retry.text)
            self.assertEqual(self._state(root), blocked_state)
            self.assertEqual({str(item.relative_to(pending)): item.read_bytes() for item in pending.rglob("*") if item.is_file()}, recovery)

    def test_recovery_directory_created_during_preflight_is_never_claimed_or_removed(self):
        with self._local_client() as (root, client):
            payload = self._backup(client)
            before = self._state(root)
            pending = root / "personal-state" / "restore-pending"
            original_mkdir = Path.mkdir
            sentinel = b"Synthetic earlier recovery bytes must survive"

            def create_competing_directory(path, *args, **kwargs):
                if path == pending:
                    original_mkdir(path)
                    (path / "earlier.original").write_bytes(sentinel)
                return original_mkdir(path, *args, **kwargs)

            with patch.object(Path, "mkdir", create_competing_directory):
                response = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual((pending / "earlier.original").read_bytes(), sentinel)
            self.assertEqual(self._state(root), before)

    def test_cleanup_failure_retains_recovery_and_reports_uncertain_completion(self):
        with self._local_client() as (root, client):
            payload = self._backup(client, ("task-existing", "task-new"))
            original = json.dumps({
                "schema_version": 2, "annotations": [self._annotation("local-note")],
            }, indent=4).encode("utf-8") + b"\n"
            self._write(root, "personal-notes/task-existing.json", original)
            with patch("app.personal_restore.shutil.rmtree", side_effect=OSError("Synthetic recovery cleanup failure")):
                response = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["detail"]["code"], "personal_restore_recovery_required")
            self.assertNotEqual(response.json().get("ok"), True)
            # Cleanup happens after commit; these writes are already durable.
            # Report uncertainty and preserve recovery instead of pretending
            # that the failed request made no changes or retrying the merge.
            blocked_export = client.get("/api/study/backup")
            self.assertEqual(blocked_export.status_code, 409, blocked_export.text)
            exported = client.get("/api/study/export").json()
            self.assertEqual(len(exported["cards"]), 1)
            self.assertEqual(len(exported["reviews"]), 1)
            self.assertEqual(len(exported["activity_events"]), 2)
            self.assertEqual(exported["plan"]["title"], "Plan from backup")
            self.assertTrue((root / "personal-notes/task-new.json").is_file())
            pending = root / "personal-state" / "restore-pending"
            recovery = {str(item.relative_to(pending)): item.read_bytes() for item in pending.rglob("*") if item.is_file()}
            self.assertIn(original, recovery.values())
            committed_state = self._state(root)
            retry = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(retry.status_code, 409, retry.text)
            self.assertEqual(self._state(root), committed_state)
            self.assertEqual({str(item.relative_to(pending)): item.read_bytes() for item in pending.rglob("*") if item.is_file()}, recovery)

    def test_interrupted_restore_preserves_recovery_copies_and_blocks_another_restore(self):
        with self._local_client() as (root, client):
            payload = self._backup(client, ("task-existing", "task-new"))
            original = json.dumps({
                "schema_version": 2, "annotations": [self._annotation("local-note")],
            }, indent=4).encode("utf-8") + b"\n"
            self._write(root, "personal-notes/task-existing.json", original)
            before = self._state(root)
            script = """
import json
import os
import sys
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.storage import atomic_write_text

def interrupt_after_write(path, text):
    atomic_write_text(path, text)
    os._exit(73)

payload = json.load(sys.stdin)
with patch('app.personal_notes.atomic_write_text', side_effect=interrupt_after_write):
    TestClient(app).post('/api/study/backup/restore', json=payload)
raise SystemExit(74)
"""
            environment = dict(os.environ)
            environment["LEARNNOTE_DATA_DIR"] = str(root)
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            process = subprocess.run(
                [sys.executable, "-c", script], input=json.dumps(payload),
                text=True, capture_output=True, env=environment, timeout=20,
            )
            self.assertEqual(process.returncode, 73, process.stderr)
            self.assertEqual(self._state(root)[1], before[1], "An uncommitted interrupted study transaction must roll back")
            pending = root / "personal-state" / "restore-pending"
            self.assertTrue(pending.is_dir(), "An interrupted restore must retain a recovery marker")
            recovery = {str(path.relative_to(pending)): path.read_bytes() for path in pending.rglob("*") if path.is_file()}
            self.assertIn(original, recovery.values(), "The exact original bytes must remain available")
            interrupted = self._state(root)
            response = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["detail"]["code"], "personal_restore_recovery_required")
            self.assertEqual(self._state(root), interrupted)
            self.assertEqual({str(path.relative_to(pending)): path.read_bytes() for path in pending.rglob("*") if path.is_file()}, recovery)

            blocked_writes = (
                ("post", "/api/personal/task/synthetic", {"text": "New annotation"}),
                ("delete", "/api/personal/task/synthetic/local-note", None),
                ("put", "/api/tasks/editions/task/synthetic", {"text": "New edition", "revision": "before"}),
            )
            for method, url, body in blocked_writes:
                with self.subTest(blocked_write=url):
                    response = client.request(method, url, **({"json": body} if body is not None else {}))
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(self._state(root), interrupted)
                    self.assertEqual({str(path.relative_to(pending)): path.read_bytes() for path in pending.rglob("*") if path.is_file()}, recovery)

    def test_supported_current_and_legacy_files_preserve_bytes_and_local_edits(self):
        for version in (None, 1, 2):
            with self.subTest(version=version), self._local_client() as (root, client):
                payload = self._backup(client)
                envelope = {"annotations": [self._annotation(text="Newer local correction")]}
                if version is not None:
                    envelope["schema_version"] = version
                self._write(root, "personal-notes/task-synthetic.json", json.dumps(envelope, indent=4) + "\n")
                backup_edition = self._edition("synthetic", "Older backup edition")
                current_edition = self._edition("synthetic", "Newer local edition")
                payload["personal"]["editions"] = [backup_edition]
                self._write(root, f"user-editions/{current_edition['key']}.json", json.dumps(current_edition["value"], indent=4) + "\n")
                personal_before = self._state(root)[0]
                response = client.post("/api/study/backup/restore", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["merge"]["restored_annotations"], 0)
                self.assertEqual(response.json()["merge"]["restored_editions"], 0)
                self.assertEqual(self._state(root)[0], personal_before)
                restored = self._state(root)
                repeated = client.post("/api/study/backup/restore", json=payload)
                self.assertEqual(repeated.status_code, 200, repeated.text)
                self.assertTrue(all(count == 0 for count in repeated.json()["merge"].values()))
                self.assertEqual(self._state(root), restored)

    def test_current_and_legacy_snapshots_restore_and_retry_idempotently(self):
        for study_version in (3, 4):
            with self.subTest(study_version=study_version), self._local_client() as (root, client):
                payload = self._backup(client)
                payload["study"]["schema_version"] = study_version
                payload["personal"]["editions"] = [self._edition("synthetic")]
                response = client.post("/api/study/backup/restore", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                for key in ("restored_cards", "restored_reviews", "restored_activity", "restored_plan", "restored_annotations", "restored_editions"):
                    self.assertEqual(response.json()["merge"][key], 1, key)
                exported = client.get("/api/study/backup").json()
                self.assertEqual(exported["study"]["plan"]["title"], "Plan from backup")
                self.assertEqual(len(exported["study"]["activity_events"]), 2)
                self.assertEqual(len(exported["study"]["reviews"]), 1)
                restored = self._state(root)
                repeated = client.post("/api/study/backup/restore", json=payload)
                self.assertEqual(repeated.status_code, 200, repeated.text)
                self.assertTrue(all(count == 0 for count in repeated.json()["merge"].values()))
                self.assertEqual(self._state(root), restored)

    def test_merging_missing_annotations_keeps_newer_local_items(self):
        for version in (None, 1, 2):
            with self.subTest(version=version), self._local_client() as (root, client):
                payload = self._backup(client)
                local_item = self._annotation(text="Newer local correction")
                local_item["request_id"] = "existing-request"
                local_item["anchor"] = {"source_revision": "local-revision", "selected_text": "Source quote"}
                envelope = {"annotations": [local_item]}
                if version is not None:
                    envelope["schema_version"] = version
                self._write(root, "personal-notes/task-synthetic.json", json.dumps(envelope))
                payload["personal"]["annotations"][0]["items"].append(self._annotation("missing-note"))
                response = client.post("/api/study/backup/restore", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["merge"]["restored_annotations"], 1)
                stored = json.loads((root / "personal-notes/task-synthetic.json").read_text(encoding="utf-8"))
                self.assertEqual({item["id"] for item in stored["annotations"]}, {"backup-note", "missing-note"})
                self.assertEqual(next(item for item in stored["annotations"] if item["id"] == "backup-note"), local_item)
                restored = self._state(root)
                repeated = client.post("/api/study/backup/restore", json=payload)
                self.assertEqual(repeated.status_code, 200, repeated.text)
                self.assertEqual(self._state(root), restored)

    def test_newer_local_plan_survives_restore(self):
        with self._local_client() as (root, client):
            payload = self._backup(client)
            plan_before = client.get("/api/study/plan").json()["plan"]
            payload["study"]["plan"]["updated_at"] = "2000-01-01T00:00:00+00:00"
            response = client.post("/api/study/backup/restore", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["merge"]["restored_plan"], 0)
            self.assertEqual(client.get("/api/study/plan").json()["plan"], plan_before)

    def test_concurrent_restores_merge_both_additions_without_duplicate_study_rows(self):
        with self._local_client() as (root, client):
            payload = self._backup(client)
            other = copy.deepcopy(payload)
            other["personal"]["annotations"][0]["items"] = [self._annotation("other-note")]
            start = threading.Barrier(2)

            def restore(value):
                start.wait(timeout=10)
                return TestClient(app, raise_server_exceptions=False).post("/api/study/backup/restore", json=value)

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(restore, value) for value in (payload, other)]
                responses = [future.result(timeout=20) for future in futures]
            for value, response in zip((payload, other), responses):
                self.assertIn(response.status_code, (200, 409), response.text)
                if response.status_code == 409:
                    self.assertTrue(response.json().get("detail"), response.text)
                    response = client.post("/api/study/backup/restore", json=value)
                self.assertEqual(response.status_code, 200, response.text)
            stored = json.loads((root / "personal-notes/task-synthetic.json").read_text(encoding="utf-8"))
            self.assertEqual({item["id"] for item in stored["annotations"]}, {"backup-note", "other-note"})
            exported = client.get("/api/study/backup").json()["study"]
            self.assertEqual(len(exported["cards"]), 1)
            self.assertEqual(len(exported["reviews"]), 1)
            self.assertEqual(len(exported["activity_events"]), 2)


if __name__ == "__main__":
    unittest.main()
