"""Synthetic transaction, interruption and no-source-write regression tests."""
from __future__ import annotations

from contextlib import closing

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from desktop import data_migration as migration
from desktop.data_migration_inventory import MigrationError, inventory, fingerprint

ROOT = Path(__file__).resolve().parents[2]


def initialize_producer_database(name, path):
    """Run actual production initializers, including dynamic ALTER migrations."""
    from app import activation, community, course_episodes, queue_controls, study, token_usage
    root = path.parent
    if name == "task-queue.sqlite3":
        db = sqlite3.connect(path)
        try:
            queue_controls.initialize_queue_schema(db)
        finally:
            db.close()
    elif name == "activation.sqlite3":
        with activation.database(root):
            pass
    elif name == "token-usage.sqlite3":
        with patch.object(token_usage, "DATA_DIR", root), token_usage._db():
            pass
    else:
        module = {"study.sqlite3": study, "course-episodes.sqlite3": course_episodes,
                  "community.sqlite3": community}[name]
        with patch.object(module, "DATA_DIR", root), patch.object(module, "ensure_dirs", return_value=None):
            module._connect().close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "data").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="migration-", dir=ROOT / "data")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source, self.target, self.app = [self.base / name for name in ("source", "target", "app")]
        for path in (self.source, self.target, self.app):
            path.mkdir()
        (self.source / ".desktop-session.lock").write_bytes(b"0")
        self.task_id = "a123456789bc"
        self.task_root = self.source / "tasks" / self.task_id
        self.task_root.mkdir(parents=True)
        (self.task_root / "note.md").write_text("# 合成笔记\n", encoding="utf-8")
        (self.task_root / "transcript.json").write_text('{"language":"zh","segments":[]}', encoding="utf-8")
        self.task = {"schema_version": 1, "id": self.task_id, "status": "success", "source_type": "local",
            "mode": "video", "note_path": str(self.task_root / "note.md"),
            "transcript_path": str(self.task_root / "transcript.json"), "source_media_path": "", "media_path": "",
            "summary_diagnostics": {}, "frame_grids": [], "source_task_id": "", "learning_range": {}}
        self.save_task()
        self.previous = json.dumps({"data_dir": str(self.source), "unrelated_setting": {"keep": "原值"}}, ensure_ascii=False, indent=3).encode("utf-8")
        (self.app / "learnnote-config.json").write_bytes(self.previous)

    def save_task(self):
        (self.task_root / "task.json").write_text(json.dumps(self.task, ensure_ascii=False, indent=2), encoding="utf-8")

    def prepare(self):
        self.before = inventory(self.source)
        self.plan = migration.preview_migration(self.source, self.target, self.app)
        self.request = migration.prepare_request(self.app, self.plan)
        self.receipt_dir = self.app / ".data-migrations" / self.request["token"]
        return self.request

    def apply(self, **kwargs):
        return migration.apply_request(self.app, self.request["token"], self.request["digest"], **kwargs)

    def assert_source(self):
        self.assertEqual(self.before, inventory(self.source))

    def assert_old_config(self):
        self.assertEqual(self.previous, (self.app / "learnnote-config.json").read_bytes())

    def test_preview_is_read_only_and_success_changes_only_destination_owned_paths(self):
        self.prepare()
        self.assert_old_config()
        self.assertEqual(list(self.target.iterdir()), [])
        self.assert_source()
        preview = migration.public_preview(self.plan)
        self.assertTrue(preview["preview"])
        self.assertIn("激活前复制或校验失败不会切换", preview["message"])
        self.assertIn("激活结果请查看迁移记录", preview["message"])
        self.assertIn("原目录与原配置备份仍保留", preview["message"])
        self.assertEqual(len(preview["changes"]), 2)
        result = self.apply()
        self.assertTrue(result["ok"])
        self.assert_source()
        configured = json.loads((self.app / "learnnote-config.json").read_bytes())
        self.assertEqual(configured["data_dir"], str(self.target))
        self.assertEqual(configured["unrelated_setting"], {"keep": "原值"})
        self.assertEqual((self.receipt_dir / "previous-config.bin").read_bytes(), self.previous)
        saved = json.loads((self.target / "tasks" / self.task_id / "task.json").read_bytes())
        self.assertEqual(saved["note_path"], str(self.target / "tasks" / self.task_id / "note.md"))
        # The unchanged production resolver can read an explicit native move.
        from app.task_paths import resolve_task_artifact
        resolved = resolve_task_artifact(self.target / "tasks" / self.task_id, self.task_id, saved["note_path"], field="note_path")
        self.assertEqual(resolved.read_text(encoding="utf-8"), "# 合成笔记\n")
        receipt = json.loads((self.receipt_dir / "receipt.json").read_bytes())
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["changes"], self.plan["references"]["changes"])

    def test_credentials_and_cache_are_excluded_before_reading(self):
        excluded = [self.source / "webview-profile" / "secret", self.task_root / "cookies.txt",
                    self.task_root / "subtitle_cookies.txt", self.source / "config" / "client-update-state.json"]
        for path in excluded:
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"synthetic credential sentinel")
        original = os.open
        def guarded(path, *args, **kwargs):
            if Path(path) in excluded:
                raise AssertionError("credential opened")
            return original(path, *args, **kwargs)
        with patch("os.open", side_effect=guarded):
            self.prepare()
            self.apply()
        for path in excluded:
            self.assertFalse((self.target / path.relative_to(self.source)).exists())
            self.assertEqual(path.read_bytes(), b"synthetic credential sentinel")

    def test_nonempty_destination_does_not_merge_or_change_config(self):
        (self.target / "keep.txt").write_bytes(b"existing")
        with self.assertRaisesRegex(MigrationError, "已有内容"):
            migration.preview_migration(self.source, self.target, self.app)
        self.assert_old_config()
        self.assertEqual((self.target / "keep.txt").read_bytes(), b"existing")

    def test_failed_task_identity_unknown_root_and_pending_restore_are_blockers(self):
        for name in ("mystery.dat", "restore-pending", "personal-state"):
            with self.subTest(name=name):
                path = self.source / name
                path.write_bytes(b"untouched")
                with self.assertRaises(MigrationError):
                    migration.preview_migration(self.source, self.target, self.app)
                self.assert_old_config()
                path.unlink()

    def test_changed_source_config_target_and_request_reject_before_activation(self):
        self.prepare()
        (self.task_root / "note.md").write_text("changed", encoding="utf-8")
        with self.assertRaises(MigrationError):
            self.apply()
        self.assert_old_config()
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual((self.task_root / "note.md").read_text(encoding="utf-8"), "changed")

    def test_tampered_request_digest_rejected(self):
        self.prepare()
        path = self.receipt_dir / "request.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(MigrationError):
            self.apply()
        self.assert_old_config()
        self.assert_source()

    def test_injected_failure_at_every_precommit_phase_preserves_source_and_config(self):
        for phase in ("stage_created", "copied", "verified", "destination_released", "published", "before_config"):
            with self.subTest(phase=phase):
                case = MigrationTests("test_preview_is_read_only_and_success_changes_only_destination_owned_paths")
                case.setUp()
                try:
                    case.prepare()
                    def interrupt(actual):
                        if actual == phase:
                            raise OSError("synthetic destination failure")
                    with case.assertRaises(OSError):
                        case.apply(checkpoint=interrupt)
                    case.assert_old_config()
                    case.assert_source()
                    case.assertEqual((case.receipt_dir / "previous-config.bin").read_bytes(), case.previous)
                finally:
                    case.doCleanups()

    def test_subprocess_abrupt_exit_has_old_config_until_atomic_activation(self):
        for phase in ("copied", "published", "before_config", "activated"):
            with self.subTest(phase=phase):
                case = MigrationTests("test_preview_is_read_only_and_success_changes_only_destination_owned_paths")
                case.setUp()
                try:
                    case.prepare()
                    script = "from pathlib import Path; import os,sys; from desktop.data_migration import apply_request; apply_request(Path(sys.argv[1]),sys.argv[2],sys.argv[3],checkpoint=lambda phase: os._exit(79) if phase==sys.argv[4] else None)"
                    result = subprocess.run([sys.executable, "-c", script, str(case.app), case.request["token"], case.request["digest"], phase], cwd=ROOT, capture_output=True)
                    self.assertEqual(result.returncode, 79, result.stderr.decode("utf-8", errors="replace"))
                    case.assert_source()
                    if phase == "activated":
                        self.assertEqual(json.loads((case.app / "learnnote-config.json").read_bytes())["data_dir"], str(case.target))
                        self.assertEqual(json.loads((case.receipt_dir / "receipt.json").read_bytes())["status"], "ready_to_activate")
                    else:
                        case.assert_old_config()
                finally:
                    case.doCleanups()

    def test_destination_race_never_overwrites_even_empty_directory(self):
        self.prepare()
        def race(phase):
            if phase == "destination_released":
                self.target.mkdir()
        with self.assertRaises((MigrationError, FileExistsError)):
            self.apply(checkpoint=race)
        self.assert_old_config()
        self.assert_source()
        self.assertTrue(self.target.is_dir())

    def test_source_symlink_and_special_file_reject_without_following(self):
        outside = self.base / "outside"
        outside.write_bytes(b"outside")
        linked = self.task_root / "linked.md"
        try:
            linked.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(MigrationError):
            migration.preview_migration(self.source, self.target, self.app)
        self.assertEqual(outside.read_bytes(), b"outside")
        self.assert_old_config()

    def test_other_database_preserves_every_row_and_unknown_schema_blocks(self):
        path = self.source / "token-usage.sqlite3"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE usage (at TEXT,model TEXT,host TEXT,purpose TEXT,status TEXT,input_tokens INTEGER,output_tokens INTEGER,total_tokens INTEGER,elapsed_ms INTEGER)")
            db.execute("INSERT INTO usage VALUES ('date','model','host','purpose','ok',1,2,3,4)")
        self.prepare()
        self.apply()
        self.assert_source()
        with closing(sqlite3.connect(self.target / path.name)) as db, db:
            self.assertEqual(db.execute("SELECT * FROM usage").fetchall(), [('date','model','host','purpose','ok',1,2,3,4)])
        unknown = self.source / "activation.sqlite3"
        with closing(sqlite3.connect(unknown)) as db, db:
            db.execute("CREATE TABLE mystery (path TEXT)")
        fresh = self.base / "new-target"
        fresh.mkdir()
        with self.assertRaises(MigrationError):
            migration.preview_migration(self.source, fresh, self.app)

    def test_pending_queue_is_rejected_on_snapshot_without_source_database_open(self):
        path = self.source / "task-queue.sqlite3"
        initialize_producer_database(path.name, path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("INSERT INTO jobs(task_id,kind,requires_context,state,updated_at) VALUES (?, 'summary', 0, 'queued', 1)", (self.task_id,))
        before = fingerprint(path)
        original = sqlite3.connect
        def guard(path_arg, *args, **kwargs):
            self.assertNotEqual(str(path_arg), str(path))
            return original(path_arg, *args, **kwargs)
        with patch("sqlite3.connect", side_effect=guard), self.assertRaises(MigrationError) as caught:
            migration.preview_migration(self.source, self.target, self.app)
        self.assertEqual(caught.exception.code, "tasks_running")
        self.assertEqual(before, fingerprint(path))
        self.assert_old_config()

    def test_stage_extras_and_postpromotion_changes_block_activation(self):
        for name in ("unexpected.txt", ".desktop-session.lock", "library.sqlite3-journal"):
            with self.subTest(name=name):
                case = MigrationTests("test_preview_is_read_only_and_success_changes_only_destination_owned_paths")
                case.setUp()
                try:
                    case.prepare()
                    def inject(phase):
                        if phase == "copied":
                            (case.target.parent / (".learnnote-migration-" + case.request["token"]) / name).write_bytes(b"unexpected")
                    with case.assertRaises(MigrationError):
                        case.apply(checkpoint=inject)
                    case.assert_old_config()
                    case.assert_source()
                finally:
                    case.doCleanups()
        self.prepare()
        def change(phase):
            if phase == "published":
                (self.target / "tasks" / self.task_id / "note.md").write_bytes(b"changed copied note")
        with self.assertRaises(MigrationError):
            self.apply(checkpoint=change)
        self.assert_old_config()
        self.assert_source()

    def test_journals_are_rejected_before_any_sqlite_open(self):
        sentinel = self.base / "outside-super-journal"
        sentinel.write_bytes(b"never touched")
        journal = self.source / "library.sqlite3-journal"
        journal.write_bytes(b"synthetic journal " + os.fsencode(sentinel))
        before = fingerprint(journal)
        with patch("sqlite3.connect", side_effect=AssertionError("SQLite must not open")), self.assertRaises(MigrationError):
            migration.preview_migration(self.source, self.target, self.app)
        self.assertEqual(before, fingerprint(journal))
        self.assertEqual(sentinel.read_bytes(), b"never touched")
        self.assert_old_config()

    def test_stopped_wal_family_is_preserved_while_stage_is_consolidated(self):
        path = self.source / "activation.sqlite3"
        script = "import os,sqlite3,sys; db=sqlite3.connect(sys.argv[1]); db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA wal_autocheckpoint=0'); db.execute('CREATE TABLE preferences (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL)'); db.execute('CREATE TABLE facts (name TEXT PRIMARY KEY, recorded REAL NOT NULL)'); db.execute(\"INSERT INTO facts VALUES ('synthetic',1.5)\"); db.commit(); os._exit(77)"
        run = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True)
        self.assertEqual(run.returncode, 77, run.stderr.decode("utf-8", errors="replace"))
        self.assertTrue(path.with_name(path.name + "-wal").is_file())
        self.prepare()
        self.apply()
        self.assert_source()
        self.assertFalse((self.target / (path.name + "-wal")).exists())
        with closing(sqlite3.connect(self.target / path.name)) as db, db:
            self.assertEqual(db.execute("SELECT * FROM facts").fetchall(), [("synthetic", 1.5)])

    def test_real_catalog_schema_survives_persisted_request_and_moved_api_reads(self):
        # Use the production model and actual producer DDL, not mapper constants.
        from app.models import TaskRecord
        from app import library
        record = TaskRecord(id=self.task_id, source_type="local", title="Synthetic lesson", status="success",
            created_at="2026-10-17", updated_at="2026-10-17", note_path=self.task["note_path"], transcript_path=self.task["transcript_path"])
        self.task = record.model_dump(mode="json")
        self.save_task()
        with closing(sqlite3.connect(self.source / "library.sqlite3")) as db, db:
            library._ensure_schema(db)
            db.execute("INSERT INTO library_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (self.task_id,"Synthetic lesson","","local","video","success","","2026-10-17","2026-10-17",self.task["note_path"],"","","synthetic search text"))
        self.prepare()
        self.apply()
        self.assert_source()
        with closing(sqlite3.connect(self.target / "library.sqlite3")) as db, db:
            self.assertEqual(db.execute("SELECT note_path,content FROM library_tasks").fetchone(), (str(self.target / "tasks" / self.task_id / "note.md"), "synthetic search text"))
        script = "from fastapi.testclient import TestClient; from app.main import app; import sys; client=TestClient(app,raise_server_exceptions=False); paths=['note','transcript','exports/markdown','exports/bundle']; results=[client.get('/api/tasks/'+sys.argv[1]+'/'+p) for p in paths]; assert all(r.status_code==200 for r in results),[(p,r.status_code,r.text[:300]) for p,r in zip(paths,results)]; assert '合成笔记' in results[0].text"
        env = {**os.environ, "LEARNNOTE_DATA_DIR": str(self.target), "PYTHONPATH": str(ROOT / "backend")}
        result = subprocess.run([sys.executable, "-c", script, self.task_id], cwd=ROOT, env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assert_source()

    def test_real_personal_annotation_coordination_is_excluded_but_notes_survive(self):
        from app.models import TaskRecord
        from app import personal_notes
        record = TaskRecord(id=self.task_id, source_type="local", title="Synthetic lesson", status="success",
            created_at="2026-10-17", updated_at="2026-10-17", note_path=self.task["note_path"])
        with patch.object(personal_notes, "DATA_DIR", self.source), patch.object(personal_notes, "get_task", return_value=record):
            note = personal_notes.save_annotation("task", self.task_id, "自己的理解保留。")
        self.assertTrue((self.source / "personal-state").is_dir())
        self.prepare()
        self.apply()
        self.assert_source()
        copied = json.loads((self.target / "personal-notes" / ("task-" + self.task_id + ".json")).read_bytes())
        self.assertEqual(copied["annotations"][0]["id"], note["id"])
        self.assertEqual(copied["annotations"][0]["text"], "自己的理解保留。")
        self.assertFalse((self.target / "personal-state").exists())
        for name in ("restore-pending", "unknown"):
            pending = self.source / "personal-state" / name
            pending.mkdir()
            try:
                fresh = self.base / ("target-" + name)
                fresh.mkdir()
                with self.assertRaises(MigrationError):
                    migration.preview_migration(self.source, fresh, self.app)
            finally:
                pending.rmdir()

    def test_all_six_current_database_producers_match_exact_supported_schema(self):
        names = ("task-queue.sqlite3", "study.sqlite3", "token-usage.sqlite3", "course-episodes.sqlite3", "community.sqlite3", "activation.sqlite3")
        for name in names:
            initialize_producer_database(name, self.source / name)
        self.prepare()
        self.assertEqual(len(self.plan["databases"]), 6)
        self.apply()
        self.assert_source()
        receipt = json.loads((self.receipt_dir / "receipt.json").read_bytes())
        for proof in receipt["databases"]:
            self.assertEqual(proof["before"], proof["after"])

    def test_same_column_unknown_schema_required_table_and_application_id_block(self):
        changes = [
            "DROP TABLE facts; CREATE TABLE facts (name TEXT, recorded REAL NOT NULL)",
            "DROP TABLE facts; CREATE TABLE facts (name INTEGER PRIMARY KEY, recorded REAL NOT NULL)",
            "CREATE INDEX unknown_index ON facts(recorded)",
            "DROP TABLE preferences",
            "PRAGMA application_id=99",
        ]
        path = self.source / "activation.sqlite3"
        for sql in changes:
            with self.subTest(sql=sql):
                initialize_producer_database(path.name, path)
                db = sqlite3.connect(path)
                try:
                    db.executescript(sql)
                    db.commit()
                finally:
                    db.close()
                before = fingerprint(path)
                with self.assertRaises(MigrationError) as caught:
                    migration.preview_migration(self.source, self.target, self.app)
                self.assertEqual(caught.exception.code, "unsupported_database_schema")
                self.assertEqual(before, fingerprint(path))
                self.assert_old_config()
                path.unlink()

    def test_existing_personal_assistant_course_and_task_leases_block_stopped_copy(self):
        for name in ("personal-state", "assistant-operations", "course-state-locks", ".task-state"):
            directory = self.source / name
            directory.mkdir()
            (directory / "worker.lock").write_bytes(b"0")
        self.prepare()
        source_locks = {name: fingerprint(self.source / name / "worker.lock") for name in ("personal-state", "assistant-operations", "course-state-locks", ".task-state")}
        script = "from pathlib import Path; import sys; from app.worker_lease import worker_lease; context=worker_lease(Path(sys.argv[1]),blocking=False); assert context.__enter__(); print('held',flush=True); sys.stdin.readline(); context.__exit__(None,None,None)"
        for name in source_locks:
            with self.subTest(name=name):
                process = subprocess.Popen([sys.executable, "-c", script, str(self.source / name)], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
                try:
                    self.assertEqual(process.stdout.readline().strip(), "held")
                    with self.assertRaises(MigrationError) as caught:
                        self.apply()
                    self.assertEqual(caught.exception.code, "source_busy")
                    self.assert_old_config()
                    self.assert_source()
                finally:
                    _out, error = process.communicate("release\n", timeout=10)
                    self.assertEqual(process.returncode, 0, error)
        for name, before in source_locks.items():
            self.assertEqual(fingerprint(self.source / name / "worker.lock"), before)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_actual_completed_queued_caption_task_migrates_and_reopens(self):
        shutil.rmtree(self.task_root)  # Only this test's synthetic starter record.
        selected = self.base / "selected.srt"
        selected.write_text("1\n00:00:00,000 --> 00:00:03,000\nA real synthetic caption pipeline.\n", encoding="utf-8")
        script = """
from pathlib import Path
import json,sys
from unittest.mock import patch
from app import processor
from app.models import TaskOptions
from app.storage import create_task,get_task
from app.task_queue import LocalTaskQueue
options=TaskOptions(content_mode='subtitles',use_saved_connection=False)
task=create_task('local','Synthetic completed queue task',options=options)
queue=LocalTaskQueue(Path(sys.argv[1]))
with patch.object(processor,'_process_video_file',side_effect=AssertionError('No media/model processing')) as media, patch.object(processor,'summarize_with_diagnostics',side_effect=AssertionError('No model call')) as model:
    future=queue.enqueue(task.id,'local_light',lambda: processor.process_local_video_task(task.id,Path(sys.argv[1])/'unused.mp4',task.title,options,subtitle_path=Path(sys.argv[2])),generation=get_task(task.id).control_generation)
    future.result(timeout=20)
    queue.stop()
    assert not any(worker.is_alive() for worker in queue.workers.values())
    media.assert_not_called(); model.assert_not_called()
finished=get_task(task.id)
assert finished.status=='success',finished.model_dump()
assert queue.entries()[0]['state']=='done'
assert queue.entries()[0]['callback_finished']==1
print(json.dumps({'id':task.id}))
"""
        env = {**os.environ, "LEARNNOTE_DATA_DIR": str(self.source), "PYTHONPATH": str(ROOT / "backend")}
        run = subprocess.run([sys.executable, "-c", script, str(self.source), str(selected)], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        task_id = json.loads(run.stdout.strip().splitlines()[-1])["id"]
        self.prepare()
        self.apply()
        self.assert_source()
        reopened = """
import sys
from fastapi.testclient import TestClient
from app.main import app
from app.storage import get_task
from app.queue_journal import read_queue_entries
from pathlib import Path
client=TestClient(app,raise_server_exceptions=False)
for endpoint in ('note','transcript','exports/markdown','exports/subtitles','exports/bundle'):
    response=client.get('/api/tasks/'+sys.argv[1]+'/'+endpoint)
    assert response.status_code==200,(endpoint,response.status_code,response.text[:300])
assert 'A real synthetic caption pipeline.' in client.get('/api/tasks/'+sys.argv[1]+'/note').text
rows,_=read_queue_entries(Path(sys.argv[2]))
assert rows[0]['state']=='done' and rows[0]['callback_finished']==1
assert get_task(sys.argv[1]).status=='success'
"""
        run = subprocess.run([sys.executable, "-c", reopened, task_id, str(self.target)], cwd=ROOT, env={**env, "LEARNNOTE_DATA_DIR": str(self.target)}, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assert_source()
        self.assertEqual(selected.read_text(encoding="utf-8"), "1\n00:00:00,000 --> 00:00:03,000\nA real synthetic caption pipeline.\n")

    def test_receipt_reconciliation_reports_only_verified_config_commit(self):
        self.assertEqual(migration.migration_status(self.app)["status"], "none")
        self.prepare()
        self.assertEqual(migration.migration_status(self.app)["status"], "scheduled")
        self.apply()
        self.assertEqual(migration.migration_status(self.app)["status"], "complete")
        (self.app / "learnnote-config.json").write_bytes(self.previous)
        self.assertEqual(migration.migration_status(self.app)["status"], "incomplete")

    def test_postcommit_receipt_error_remains_committed_without_rollback(self):
        self.prepare()
        write = migration._atomic
        def fail_final(path, value):
            if value.get("status") == "complete":
                raise OSError("synthetic receipt write failure after commit")
            return write(path, value)
        with patch.object(migration, "_atomic", side_effect=fail_final):
            result = self.apply()
        self.assertTrue(result["ok"])
        self.assertEqual(migration.migration_status(self.app)["status"], "complete")
        self.assertEqual(json.loads((self.receipt_dir / "receipt.json").read_bytes())["status"], "ready_to_activate")
        self.assert_source()

    def test_actual_launcher_failure_after_commit_keeps_new_config_and_destination_edits(self):
        from desktop import main
        from unittest.mock import Mock
        self.prepare()
        session = Mock()
        session.acquire.return_value = True
        edited = self.target / "tasks" / self.task_id / "note.md"
        def startup_failure(*args):
            edited.write_text("new destination edit", encoding="utf-8")
            raise RuntimeError("synthetic backend startup failure")
        argv = ["LearnNote", "--apply-data-migration", self.request["token"], "--migration-digest", self.request["digest"], "--wait-for-parent", "12345"]
        with patch.object(main.sys, "argv", argv), patch.object(main, "application_root", return_value=self.app), patch.object(main, "bundled_root", return_value=ROOT), patch.object(main, "wait_for_process_exit") as wait, patch.object(main, "DesktopSession", return_value=session) as session_type, patch.object(main, "run_session", side_effect=startup_failure), patch.object(main, "report_startup_error") as report:
            self.assertEqual(main.run(), 1)
        wait.assert_called_once_with(12345)
        session_type.assert_called_once_with(self.target)
        self.assertEqual(str(report.call_args.args[0]), "synthetic backend startup failure")
        self.assertEqual(migration.migration_status(self.app)["status"], "complete")
        self.assertEqual(edited.read_text(encoding="utf-8"), "new destination edit")
        self.assert_source()

    def test_native_bridge_health_token_and_launch_fail_closed(self):
        from desktop import main
        from unittest.mock import Mock
        api = main.DesktopApi(self.source, "http://127.0.0.1:18880", self.app)
        window = Mock()
        window.create_file_dialog.return_value = [str(self.target)]
        api._bind_window(window)
        with patch.object(main, "backend_ready", return_value=False), patch.object(main.requests, "get") as get:
            blocked = api.choose_data_directory(True)
        self.assertEqual(blocked["code"], "task_status_unavailable")
        get.assert_not_called()  # No mutating GET /api/tasks preflight.
        self.assert_old_config()
        with patch.object(main, "backend_ready", return_value=True):
            preview = api.choose_data_directory(True)
        self.assertTrue(preview["preview"])
        self.assertTrue(all(isinstance(item["field"], str) for item in preview["changes"]))
        self.assertEqual(api.apply_data_directory("wrong-token")["code"], "preview_expired")
        with patch.object(main, "backend_ready", return_value=True):
            preview = api.choose_data_directory(True)
            with patch.object(main.subprocess, "Popen", side_effect=OSError("synthetic launch failure")), patch.object(main.threading, "Timer") as timer:
                result = api.apply_data_directory(preview["token"])
        self.assertFalse(result["ok"])
        timer.assert_not_called()
        self.assert_old_config()
        self.assertEqual(migration.migration_status(self.app)["status"], "failed")
        self.assertEqual(api.apply_data_directory(preview["token"])["code"], "preview_expired")
        with patch.object(main, "backend_ready", return_value=True):
            preview = api.choose_data_directory(True)
            with patch.object(main.subprocess, "Popen"), patch.object(main.threading, "Timer"):
                scheduled = api.apply_data_directory(preview["token"])
        self.assertTrue(scheduled["restarting"])
        self.assertIn("请查看迁移结果", scheduled["message"])
        self.assertNotIn("失败会继续使用原目录", scheduled["message"])
        self.assert_old_config()



if __name__ == "__main__":
    unittest.main()
