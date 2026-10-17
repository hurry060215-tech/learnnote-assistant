"""Failure diagnostics for the real queued callback fixture, without browser I/O."""
import concurrent.futures
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import sqlite3
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("controls_fixture", ROOT / "scripts/assistant-runs-fixture.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class ControlsStartupDiagnosticsTests(unittest.TestCase):
    def test_failed_callback_and_completed_future_are_retained_without_private_fields(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            manifest = root / "task.json"
            manifest.write_text(json.dumps({"id": "synthetic", "status": "failed", "secret": "exclude"}), encoding="utf-8")
            queue = types.SimpleNamespace(path=root / "queue.sqlite3", jobs={})
            with contextlib.closing(sqlite3.connect(queue.path)) as db:
                db.execute("CREATE TABLE jobs(task_id,state,generation,callback_finished)")
                db.execute("INSERT INTO jobs VALUES('synthetic','failed','generation-1',1)")
                db.commit()
            future = concurrent.futures.Future()
            future.set_exception(RuntimeError("synthetic callback failure"))
            queue.jobs["synthetic"] = (None, future)
            entered, started = threading.Event(), threading.Event()
            entered.set()
            report = fixture.controls_startup_diagnostics("synthetic", queue, manifest, entered, started, ["synthetic traceback"])
            self.assertTrue(report["callback_entered"])
            self.assertFalse(report["running_state_written"])
            self.assertEqual(report["intent"]["state"], "failed")
            self.assertEqual(report["future"]["exception"], "synthetic callback failure")
            self.assertEqual(report["callback_errors"], ["synthetic traceback"])
            self.assertNotIn("secret", report["task"])
            output = root / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                fixture.write_controls_startup_report(output, report)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)

    def test_missing_state_is_diagnostic_not_replacement_failure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            queue = types.SimpleNamespace(path=root / "missing" / "queue.sqlite3", jobs={})
            report = fixture.controls_startup_diagnostics("synthetic", queue, root / "task.json", threading.Event(), threading.Event(), [])
            self.assertEqual(report["task_read_error"], "FileNotFoundError")
            self.assertEqual(report["intent_read_error"], "OperationalError")
            self.assertFalse(report["future"]["retained"])
            self.assertEqual(report["future"]["unavailable_reason"], "queue_entry_removed_or_not_admitted")
            self.assertFalse(report["callback_entered"])

    def test_report_write_failure_preserves_primary_startup_error(self):
        with patch.object(Path, "write_text", side_effect=OSError("synthetic write failure")), contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaisesRegex(RuntimeError, "Synthetic callback did not start"):
                try:
                    raise RuntimeError("Synthetic callback did not start")
                finally:
                    fixture.write_controls_startup_report("ignored", {"ready": False})
            self.assertIn("diagnostic write failed: OSError", stderr.getvalue())

    def test_real_queue_failure_records_intent_even_after_future_is_removed(self):
        # Isolated subprocess keeps actual catalog/config roots out of the test host.
        code = r"""
import importlib.util, json, os, socket, threading
from pathlib import Path
from unittest.mock import patch
root = Path.cwd()
spec = importlib.util.spec_from_file_location('fixture', root / 'scripts/assistant-runs-fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
with patch.object(socket.socket, 'connect', side_effect=AssertionError('No network in queue failure fixture')):
    from app.task_queue import LocalTaskQueue
    data = Path(os.environ['LEARNNOTE_DATA_DIR'])
    queue = LocalTaskQueue(data)
    try:
        def fail_before_control_callback():
            raise RuntimeError('synthetic pre-callback failure')
        future = queue.enqueue('synthetic', 'summary', fail_before_control_callback, generation='fixture-generation')
        try:
            future.result(timeout=5)
        except RuntimeError as exc:
            assert str(exc) == 'synthetic pre-callback failure'
        else:
            raise AssertionError('Actual worker failure was not propagated')
        assert 'synthetic' not in queue.jobs
        report = fixture.controls_startup_diagnostics('synthetic', queue, data / 'missing-task.json', threading.Event(), threading.Event(), [])
        assert report['intent']['state'] == 'failed'
        assert report['intent']['callback_finished'] == 1
        assert report['intent']['generation'] == 'fixture-generation'
        assert report['future']['retained'] is False
        assert report['future']['unavailable_reason'] == 'queue_entry_removed_or_not_admitted'
        assert not report['callback_entered']
        assert report['callback_errors'] == []
        print(json.dumps(report))
    finally:
        queue.stop()
"""
        with tempfile.TemporaryDirectory() as name:
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("LEARNNOTE_", "OPENAI_", "AZURE_", "ANTHROPIC_"))}
            env.update(LEARNNOTE_DATA_DIR=name, PYTHONPATH=str(ROOT / "backend"), PYTHONUTF8="1")
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('"state": "failed"', result.stdout)

    def test_original_wait_and_cancellation_contract_remain(self):
        source = (ROOT / "scripts/assistant-runs-fixture.py").read_text(encoding="utf-8")
        self.assertIn("ready = started.wait(5)", source)
        self.assertIn("mark_task_cancelled(task_id, expected_generation=generation)", source)
        self.assertLess(source.index('status="running"'), source.index("started.set()"))
        caller = (ROOT / "scripts/assistant-controls-visual-acceptance.cjs").read_text(encoding="utf-8")
        self.assertIn("'--startup-report',path.join(out,'controls-startup.json')", caller)
        self.assertIn("report.actual_worker_cancelled=true", caller)
        self.assertIn("assert.deepEqual(fs.readFileSync(originalPath),original)", caller)


if __name__ == "__main__":
    unittest.main()
