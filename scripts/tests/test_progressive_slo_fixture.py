"""Real loopback HTTP/worker contracts; these are not browser latency results."""
import ast
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OPTIONS = {"content_mode": "text", "visual_understanding": False, "local_ocr": False,
           "llm_api_key": "", "use_saved_connection": False,
           "llm_base_url": "http://127.0.0.1:9/v1", "llm_model": "slo-reference"}


def reference_request(minutes, label):
    duration = minutes * 60
    return {"mode": "subtitle_only", "title": f"SLO reference {minutes}m {label}", "page_url": "https://example.test/reference",
        "handoff_id": f"slo-reference-{minutes}-{label}", "options": OPTIONS, "active_video": {"duration": duration},
        "browser_subtitles": [{"start": start, "end": start + 30,
            "text": f"Reference lesson source statement at {start} seconds."} for start in range(0, duration, 30)]}


class ProgressiveSloFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="learnnote-slo-contract-")
        self.data = Path(self.temp.name)
        self.child = None
        self.logs = []

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def stop(self):
        if self.child:
            if self.child.poll() is None:
                self.child.kill()
            self.child.wait(10)
            self.reader.join(5)
            self.child.stdout.close()
            self.child = None

    def launch(self, *, resume=False, pause_before_summary=False):
        env = {key: value for key, value in os.environ.items() if key.upper() in
               {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL"}}
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, str(ROOT / "scripts/progressive-slo-fixture.py"),
            "--data-dir", str(self.data), *(["--resume"] if resume else [])]
        if pause_before_summary:
            # Pause the actual product call immediately after its draft publication,
            # before the fixture's summary adapter can set its waiting marker.
            bootstrap = """
import importlib.util, pathlib, sys, time
from unittest.mock import patch
path = pathlib.Path('scripts/progressive-slo-fixture.py').resolve()
spec = importlib.util.spec_from_file_location('paused_reference', path)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
original = fixture.configure_fixture

def configure(root, data, stack, **kwargs):
    app, metadata = original(root, data, stack, **kwargs)
    from app import subtitle_notes
    update = subtitle_notes.update_task
    def pause(task_id, **fields):
        if fields.get('phase') == 'summarizing':
            (data / 'before-summary-entered').write_text(task_id)
            deadline = time.monotonic() + 15
            while not (data / 'before-summary-release').exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError('Test summary admission was not released')
                time.sleep(.01)
        return update(task_id, **fields)
    stack.enter_context(patch.object(subtitle_notes, 'update_task', pause))
    return app, metadata

fixture.configure_fixture = configure
sys.argv = [str(path), '--data-dir', sys.argv[1]]
fixture.main()
"""
            command = [sys.executable, "-c", bootstrap, str(self.data)]
        self.child = subprocess.Popen(command, cwd=ROOT,
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        lines = queue.Queue()
        def read():
            for line in self.child.stdout:
                self.logs.append(line)
                if line.startswith('{"fixture_origin":'):
                    lines.put(json.loads(line))
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        try:
            end = time.monotonic() + 30
            while True:
                try:
                    self.fixture = lines.get(timeout=.1)
                    break
                except queue.Empty:
                    if self.child.poll() is not None or time.monotonic() >= end:
                        raise
        except queue.Empty:
            self.fail("Fixture failed to start: " + "".join(self.logs))
        self.base = self.fixture["fixture_origin"]
        self.wait(lambda: self.api("/health"), "HTTP health")
        self.assertTrue(self.fixture["offline_network"])

    def api(self, route, data=None, method=None):
        request = Request(self.base + route, data=None if data is None else json.dumps(data).encode(),
                          method=method, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    def wait(self, check, label):
        end = time.monotonic() + 20
        while time.monotonic() < end:
            try:
                value = check()
            except ConnectionError:
                value = None
            if value:
                return value
            time.sleep(.03)
        self.fail(label + "\n" + "".join(self.logs))

    def state(self, task_id):
        return self.api(f"/_fixture/tasks/{task_id}")

    def test_real_admission_draft_sse_cancel_retry_and_process_restart(self):
        self.launch()
        request = reference_request(5, "contract")
        created = self.api("/api/tasks/from-current-page?defer=true", request)
        task_id = created["task_id"]
        expected_generation = created["task"]["control_generation"]
        self.assertRegex(expected_generation, r"^[a-f0-9]{64}$")
        self.assertEqual(self.state(task_id)["continuation_calls"], 0)
        stream_url = self.base + f"/api/tasks/{task_id}/events/stream?after=0"
        with urlopen(stream_url, timeout=10) as response:
            self.assertIn("text/event-stream", response.headers["Content-Type"])
            self.assertIn("no-transform", response.headers["Cache-Control"])
            frame = {}
            while (line := response.readline().decode().strip()):
                name, value = line.split(": ", 1)
                frame[name] = value
        self.assertEqual(frame["event"], "task_created")
        # Feed an actual pre-submission HTTP frame through the browser observer's
        # parser. The request ID is transport metadata, not invented event data.
        code = """const fs=require('node:fs'); const f=require('./scripts/progressive-slo-api-acceptance.cjs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const source=f.streamIdentity(input.url,input.origin);
console.log(JSON.stringify(f.nativeSseRecord({requestId:'request-regression',eventName:input.frame.event,
eventId:input.frame.id,data:input.frame.data},new Map([['request-regression',source]]))));"""
        parsed = subprocess.run(["node", "-e", code], cwd=ROOT, input=json.dumps({"url": stream_url,
            "origin": self.base, "frame": frame}), text=True, capture_output=True, timeout=10, check=True)
        native = json.loads(parsed.stdout)
        self.assertEqual(native["task_id"], task_id)
        self.assertEqual(native["event"], "task_created")
        self.assertEqual(native["id"], frame["id"])
        self.assertEqual(self.state(task_id)["continuation_calls"], 0)
        with self.assertRaises(HTTPError) as rejected:
            self.api(f"/_fixture/tasks/{task_id}/visible?generation={self.state(task_id)['generation']}", method="POST")
        self.assertEqual(rejected.exception.code, 409)
        self.api(f"/api/tasks/{task_id}/start", OPTIONS)
        before = self.wait(lambda: (state if (state := self.state(task_id))["waiting"] else None), "held draft")
        self.assertEqual(before["status"], "running")
        self.assertEqual(before["generation"], expected_generation)
        self.assertEqual(before["queue"]["generation"], expected_generation)
        self.assertEqual(before["error_code"], "")
        self.assertFalse(before["awaiting_confirmation"])
        self.assertTrue(before["updated_at"])
        self.assertEqual(before["state_events"][-1]["status"], "running")
        self.assertEqual(set(before["hashes"]), {"transcript_path", "subtitle_path", "draft.md"})
        self.assertEqual(before["source_coverage"], {"duration": 300, "cue_count": 10,
            "first_start": 0, "last_end": 300, "reference_cues_complete": True,
            "section_count": 1, "final_section_end": 300})
        self.assertTrue(before["queue"]["generation"])
        self.assertFalse(before["queue"]["requires_context"])
        edition = self.api(f"/api/tasks/editions/task/{task_id}")
        self.assertIn("按时间段的阅读提纲", edition["text"])
        self.assertIn("不是 AI 主题总结", edition["text"])
        self.assertIn("Reference lesson source statement at 0 seconds.", edition["text"])
        # Actual HTTP SSE framing/replay, no event generator replacement.
        with urlopen(self.base + f"/api/tasks/{task_id}/events/stream?after=0", timeout=10) as response:
            self.assertIn("text/event-stream", response.headers["Content-Type"])
            frames = []
            for _ in range(300):
                line = response.readline().decode()
                frames.append(line)
                if line == "\n" and "event: draft_ready\n" in frames:
                    break
        self.assertIn("event: draft_ready\n", frames)
        self.assertTrue(any(line.startswith("id: ") and int(line[4:]) > 0 for line in frames))
        visible = self.api(f"/_fixture/tasks/{task_id}/visible?generation={self.state(task_id)['generation']}", method="POST")
        self.assertGreaterEqual(visible["after_transcript_visible_ack_seconds"], 0)
        self.assertGreaterEqual(visible["visible_ack_snapshot_seconds"], 0)
        self.api(f"/api/tasks/{task_id}/cancel", method="POST")
        cancelled = self.wait(lambda: (state if (state := self.state(task_id))["status"] == "cancelled"
            and not state["waiting"] and state["queue"]["callback_finished"] else None), "cancel callback drain")
        self.assertEqual(cancelled["hashes"], before["hashes"])
        self.assertEqual(cancelled["continuation_calls"], 1)
        with self.assertRaises(HTTPError) as rejected:
            self.api(f"/_fixture/tasks/{task_id}/visible?generation={before['generation']}", method="POST")
        self.assertEqual(rejected.exception.code, 409)
        with self.assertRaises(HTTPError) as rejected:
            self.api(f"/_fixture/tasks/{task_id}/release", method="POST")
        self.assertEqual(rejected.exception.code, 409)
        self.api(f"/api/tasks/{task_id}/retry-summary", OPTIONS)
        retry = self.wait(lambda: (state if (state := self.state(task_id))["waiting"] else None), "retry held")
        self.assertNotEqual(retry["generation"], before["generation"])
        self.assertEqual(retry["hashes"], before["hashes"])
        self.assertEqual(retry["continuation_calls"], 2)
        # An ACK from the original readable generation cannot survive retry.
        with self.assertRaises(HTTPError) as rejected:
            self.api(f"/_fixture/tasks/{task_id}/visible?generation={before['generation']}", method="POST")
        self.assertEqual(rejected.exception.code, 409)
        old_pid = self.fixture["worker_pid"]
        self.stop()
        self.launch(resume=True)
        self.assertNotEqual(self.fixture["worker_pid"], old_pid)
        recovered = self.wait(lambda: (state if (state := self.state(task_id))["waiting"] else None), "startup recovery")
        self.assertEqual(recovered["hashes"], before["hashes"])
        self.assertEqual(recovered["generation"], retry["generation"])
        self.assertEqual(recovered["queue"]["sequence"], retry["queue"]["sequence"])
        self.assertEqual(recovered["queue"]["generation"], retry["queue"]["generation"])
        startup = self.api("/_fixture/state")
        self.assertEqual(startup["startup_recovery"]["recovered"], 1)
        self.assertEqual(startup["startup_recovery"]["waiting_for_context"], 0)
        self.api(f"/_fixture/tasks/{task_id}/release", method="POST")
        completed = self.wait(lambda: (state if (state := self.state(task_id))["status"] == "success"
            and state["queue"]["callback_finished"] else None), "recovered completion")
        self.assertEqual(completed["hashes"], before["hashes"])
        self.assertEqual(self.api("/_fixture/state")["forbidden_attempts"], [])

    def test_persisted_readable_draft_precedes_held_summary_adapter(self):
        self.launch(pause_before_summary=True)
        task_id = self.api("/api/tasks/from-current-page?defer=true", reference_request(5, "early-readable"))["task_id"]
        self.api(f"/api/tasks/{task_id}/start", OPTIONS)
        self.wait(lambda: (self.data / "before-summary-entered").exists(), "actual post-draft pre-summary boundary")
        before = self.state(task_id)
        self.assertEqual(before["status"], "running")
        self.assertFalse(before["waiting"])
        self.assertEqual(before["continuation_calls"], 0)
        self.assertTrue(any(event["event"] == "draft_ready" for event in before["stages"]))
        edition = self.api(f"/api/tasks/editions/task/{task_id}")
        self.assertIn("按时间段的阅读提纲", edition["text"])
        self.assertIn("Reference lesson source statement at 0 seconds.", edition["text"])
        with urlopen(self.base + f"/api/tasks/{task_id}/events/stream?after=0", timeout=10) as response:
            frames = []
            for _ in range(300):
                line = response.readline().decode()
                frames.append(line)
                if line == "\n" and "event: draft_ready\n" in frames:
                    break
        self.assertIn("event: draft_ready\n", frames)
        # The actual ACK succeeds while the deterministic summary barrier is closed.
        visible = self.api(f"/_fixture/tasks/{task_id}/visible?generation={before['generation']}", method="POST")
        self.assertFalse(visible["waiting"])
        self.assertEqual(visible["continuation_calls"], 0)
        self.assertEqual(visible["hashes"], before["hashes"])
        self.assertFalse((self.data / "before-summary-release").exists())
        for generation in ("", "b" * 64):
            with self.assertRaises(HTTPError) as rejected:
                self.api(f"/_fixture/tasks/{task_id}/visible?generation={generation}", method="POST")
            self.assertEqual(rejected.exception.code, 409)
        with self.assertRaises(HTTPError) as rejected:
            self.api(f"/_fixture/tasks/{task_id}/release", method="POST")
        self.assertEqual(rejected.exception.code, 409)
        (self.data / "before-summary-release").write_text("release this test boundary")
        held = self.wait(lambda: (state if (state := self.state(task_id))["waiting"] else None), "real summary adapter entry")
        self.assertEqual(held["hashes"], before["hashes"])
        self.assertEqual(held["generation"], before["generation"])
        self.assertEqual(held["continuation_calls"], 1)
        self.assertEqual(self.api(f"/_fixture/tasks/{task_id}/visible?generation={self.state(task_id)['generation']}", method="POST")["status"], "running")
        self.api(f"/_fixture/tasks/{task_id}/release", method="POST")
        self.wait(lambda: self.state(task_id)["status"] == "success" and self.state(task_id)["queue"]["callback_finished"], "test continuation drains")

    def test_fresh_and_resume_directory_guards_preserve_existing_files(self):
        original = self.data / "unrelated.txt"
        original.write_text("keep this", encoding="utf-8")
        for resume in (False, True):
            result = subprocess.run([sys.executable, str(ROOT / "scripts/progressive-slo-fixture.py"),
                "--data-dir", str(self.data), *(["--resume"] if resume else [])], capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(original.read_text(), "keep this")
        self.assertEqual(list(self.data.iterdir()), [original])

    def test_forbidden_attempt_survives_process_restart(self):
        self.launch()
        created = self.api("/api/tasks/from-current-page?defer=true", {"mode": "download_only",
            "title": "SLO reference forbidden download", "page_url": "https://example.test/reference",
            "handoff_id": "slo-forbidden-download", "options": OPTIONS})
        task_id = created["task_id"]
        self.api(f"/api/tasks/{task_id}/start", OPTIONS)
        self.wait(lambda: self.state(task_id)["status"] == "failed", "forbidden download rejected")
        failed = self.state(task_id)
        self.assertEqual(failed["error_code"], "processing_failed")
        self.assertIn("Forbidden fixture operation: download", failed["error_detail"])
        self.assertEqual(failed["state_events"][-1]["error_code"], failed["error_code"])
        self.assertLessEqual(len(failed["state_events"]), 16)
        before = self.api("/_fixture/state")["forbidden_attempts"]
        self.assertIn("download", before)
        self.stop()
        self.launch(resume=True)
        self.assertEqual(self.api("/_fixture/state")["forbidden_attempts"], before)

    def test_all_reference_durations_keep_complete_persisted_source_and_outline(self):
        self.launch()
        for minutes in (5, 30, 60, 180):
            with self.subTest(minutes=minutes):
                task_id = self.api("/api/tasks/from-current-page?defer=true", reference_request(minutes, "coverage"))["task_id"]
                self.api(f"/api/tasks/{task_id}/start", OPTIONS)
                before = self.wait(lambda: (state if (state := self.state(task_id))["waiting"] else None), "complete source held")
                self.assertEqual(before["source_coverage"], {"duration": minutes * 60, "cue_count": minutes * 2,
                    "first_start": 0, "last_end": minutes * 60, "reference_cues_complete": True,
                    "section_count": minutes // 5, "final_section_end": minutes * 60})
                self.api(f"/_fixture/tasks/{task_id}/release", method="POST")
                after = self.wait(lambda: (state if (state := self.state(task_id))["status"] == "success"
                    and state["queue"]["callback_finished"] else None), "reference completion")
                self.assertEqual(after["hashes"], before["hashes"])
        self.assertEqual(self.api("/_fixture/state")["forbidden_attempts"], [])

    def test_update_preferences_keep_startup_local_and_forced_check_is_denied(self):
        self.launch()
        for _ in range(3):
            status = self.api("/api/update/status")
            self.assertTrue(status["ok"])
            self.assertFalse(status["check_due"])
            self.assertFalse(status["preferences"]["auto_check"])
            self.assertFalse(status["preferences"]["auto_download"])
        self.assertEqual(self.api("/_fixture/state")["forbidden_attempts"], [])
        forced = self.api("/api/update/check", method="POST")
        self.assertFalse(forced["ok"])
        state = self.api("/_fixture/state")
        self.assertEqual(state["forbidden_attempts"], ["external_network_blocked"])
        diagnostic = state["network_diagnostics"][0]
        self.assertEqual(diagnostic["host"], "api.github.com")
        self.assertEqual(diagnostic["path"], "/repos/hurry060215-tech/learnnote-assistant/releases/latest")
        self.assertIn("fetch_latest_release", [location["function"] for location in diagnostic["locations"]])
        self.assertNotIn("headers", diagnostic)
        self.assertNotIn("url", diagnostic)
        self.assertNotIn("?", diagnostic["path"])
        self.stop()
        self.launch(resume=True)
        resumed = self.api("/_fixture/state")
        self.assertEqual(resumed["forbidden_attempts"], state["forbidden_attempts"])
        self.assertEqual(resumed["network_diagnostics"], state["network_diagnostics"])
        self.assertFalse(self.api("/api/update/status")["check_due"])


class VisibleReceiptContractTests(unittest.TestCase):
    def test_actual_handler_receipt_excludes_slow_snapshot_and_rejects_stale_states(self):
        # Execute the real endpoint body with deterministic clocks and snapshot
        # barriers; no alternate implementation or calculated browser timestamp.
        from types import SimpleNamespace
        from fastapi import HTTPException
        source = ast.parse((ROOT / "scripts/progressive-slo-fixture.py").read_text())
        handler = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == "visible")
        handler.decorator_list = []
        generation = "a" * 64
        queue = {"task_id": "owned", "generation": generation, "state": "running", "callback_finished": 0}
        state = {"task_id": "owned", "generation": generation, "status": "running", "queue": queue,
                 "hashes": {"transcript_path": "t", "subtitle_path": "s", "draft.md": "d"},
                 "stages": [{"event": "draft_ready"}], "waiting": False}
        task = SimpleNamespace(status="running", generation=generation)
        record = {"transcript_recorded": 10, "transcript_generation": generation}
        clock = [11]
        def snapshot(task_id):
            self.assertEqual(clock[0], 11)
            clock[0] += 13
            return state
        import re
        context = {"time": SimpleNamespace(monotonic=lambda: clock[0]), "register": lambda _: record,
                   "snapshot": snapshot, "storage": SimpleNamespace(get_task=lambda _: task),
                   "read_queue_job": lambda *_: queue, "data": None, "task_generation": lambda value: value.generation,
                   "re": re, "HTTPException": HTTPException}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), "actual-visible-handler", "exec"), context)
        result = context["visible"]("owned", generation)
        self.assertEqual(result["after_transcript_visible_ack_seconds"], 1)
        self.assertEqual(result["visible_ack_snapshot_seconds"], 13)
        self.assertFalse(result["waiting"])
        # Real receipt later than five seconds remains late, even with cheap proof.
        clock[0] = 16
        context["snapshot"] = lambda _: state
        self.assertEqual(context["visible"]("owned", generation)["after_transcript_visible_ack_seconds"], 6)
        for patch in ({"status": "cancelled"}, {"generation": "b" * 64}):
            old = dict(state); state.update(patch)
            with self.assertRaises(HTTPException): context["visible"]("owned", generation)
            state.clear(); state.update(old)
        record["transcript_recorded"] = 17
        with self.assertRaises(HTTPException): context["visible"]("owned", generation)
        record["transcript_recorded"] = 10
        task.generation = "b" * 64
        with self.assertRaises(HTTPException): context["visible"]("owned", generation)
        context["storage"].get_task = lambda _: (_ for _ in ()).throw(HTTPException(404, "deleted"))
        with self.assertRaises(HTTPException) as deleted: context["visible"]("owned", generation)
        self.assertEqual(deleted.exception.status_code, 404)
