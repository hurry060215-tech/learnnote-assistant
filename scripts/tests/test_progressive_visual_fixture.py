"""Real owned-media/HTTP/worker contracts, not browser or provider-quality claims."""
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import signal
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx2 as httpx

ROOT = Path(__file__).resolve().parents[2]


class ProgressiveVisualFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="learnnote-visual-join-")
        self.data = Path(self.temp.name)
        self.child = None
        self.logs = []
        self.client = httpx.Client(timeout=15, trust_env=False)

    def tearDown(self):
        if self.child:
            if self.child.poll() is None:
                try:
                    self.child.stdin.write("shutdown\n"); self.child.stdin.flush(); self.child.wait(5)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    if os.name == "nt": subprocess.run(["taskkill", "/PID", str(self.child.pid), "/T", "/F"], check=True, timeout=10)
                    else: os.killpg(self.child.pid, signal.SIGKILL)
            self.child.wait(10)
            self.child.stdin.close()
            self.reader.join(5)
            self.child.stdout.close()
        self.client.close()
        self.temp.cleanup()

    def launch(self, bootstrap=None):
        env = {key: value for key, value in os.environ.items() if key.upper() in
               {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL"}}
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        script = ROOT / "scripts/progressive-visual-fixture.py"
        command = [sys.executable, str(script)]
        if bootstrap:
            source = ("import importlib.util, pathlib, sys, time\n"
                f"spec=importlib.util.spec_from_file_location('fixture', {str(script)!r})\n"
                "fixture=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)\n"
                + bootstrap + "\nfixture.main()\n")
            command = [sys.executable, "-c", source]
        self.child = subprocess.Popen([*command, "--data-dir", str(self.data)], cwd=ROOT, env=env, start_new_session=os.name != "nt", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8")
        lines = queue.Queue()
        def read():
            for line in self.child.stdout:
                self.logs.append(line)
                if line.startswith('{"fixture_origin":'): lines.put(json.loads(line))
        self.reader = threading.Thread(target=read, daemon=True); self.reader.start()
        started = time.monotonic()
        deadline = started + 45
        while True:
            try:
                self.fixture = lines.get(timeout=.1); break
            except queue.Empty:
                if self.child.poll() is not None or time.monotonic() >= deadline:
                    if self.child.poll() is not None: self.reader.join(1)
                    self.fail(f"Visual fixture startup failed after {time.monotonic()-started:.3f}s "
                              f"(exit={self.child.poll()}): " + "".join(self.logs))
        self.base = self.fixture["fixture_origin"]
        self.wait(lambda: self.client.get(self.base + "/health").is_success, "health")

    def api(self, path, data=None, method="GET"):
        response = self.client.request(method, self.base + path, json=data)
        self.assertTrue(response.is_success, response.text + "\n" + "".join(self.logs))
        return response.json()

    def wait(self, fn, label):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try: value = fn()
            except httpx.ConnectError: value = None
            if value: return value
            time.sleep(.03)
        self.fail(label + "\n" + "".join(self.logs))

    def task(self, task_id):
        return self.api(f"/_fixture/tasks/{task_id}")

    def upload(self, variant="a"):
        media = self.client.get(self.base + "/_fixture/media/" + variant); self.assertTrue(media.is_success)
        response = self.client.post(self.base + "/api/tasks/from-local", data={
            "title": "Visual join API contract " + variant, "options": json.dumps(self.fixture["options"])},
            files={"file": ("synthetic.mp4", media.content, "video/mp4")})
        self.assertTrue(response.is_success, response.text)
        return response.json()["task_id"]

    def assert_native_visual_join(self, task_id, projection, persisted):
        fields = {}
        with self.client.stream("GET", self.base + f"/api/tasks/{task_id}/events/stream?after=0") as response:
            self.assertTrue(response.is_success)
            for line in response.iter_lines():
                if not line:
                    if fields.get("event") == "partial_section_ready": break
                    fields = {}
                elif ": " in line:
                    key, value = line.split(": ", 1); fields[key] = value
        self.assertEqual(fields.get("event"), "partial_section_ready")
        event = {"requestId": "actual-http-frame", "eventId": fields["id"],
                 "eventName": fields["event"], "data": fields["data"]}
        script = """
const assert=require('node:assert/strict');
const {streamIdentity,nativeSseRecord}=require('./scripts/progressive-slo-api-acceptance.cjs');
const {visualEventDetail,visualEventMatches}=require('./scripts/progressive-visual-api-acceptance.cjs');
let input='';process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',()=>{
 const v=JSON.parse(input),url=v.base+'/api/tasks/'+v.task_id+'/events/stream?after=0';
 const native=nativeSseRecord(v.event,new Map([[v.event.requestId,streamIdentity(url,v.base)]]));
 assert(visualEventMatches(visualEventDetail(v.event),native,v.projection,v.persisted));
});
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, timeout=15,
            input=json.dumps({"base": self.base, "task_id": task_id, "event": event,
                              "projection": projection, "persisted": persisted}))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_media_batches_partial_api_cancel_and_source_preservation(self):
        self.launch()
        task_id = self.upload()
        first = self.wait(lambda: (state if (state := self.task(task_id))["active_completions"] == 2 else None), "two actual held calls")
        self.assertEqual(first["status"], "running")
        self.assertGreaterEqual(first["grid_count"], 3)
        self.assertGreaterEqual(first["frame_count"], first["grid_count"])
        self.assertEqual(first["transcript"]["source"], "embedded-subtitle")
        self.assertEqual([(cue["start"], cue["end"]) for cue in first["transcript"]["segments"]], [(0,12),(12,24),(24,36)])
        self.assertEqual(sorted(call["batch"] for call in first["calls"]), [1,2])
        diagnostics = self.api("/_fixture/diagnostics")
        self.assertEqual(diagnostics["worker_pid"], self.fixture["worker_pid"])
        self.assertTrue(any(location["function"] == "completion"
            and location["file"] == "scripts/progressive-visual-fixture.py"
            for thread in diagnostics["threads"] for location in thread["locations"]))
        self.assertLessEqual(len(diagnostics["threads"]), diagnostics["thread_limit"])
        initial = self.api(f"/api/tasks/{task_id}/partial-note")
        self.assertFalse(initial["verified"])
        self.assertEqual([s["kind"] for s in initial["sections"]], ["temporal_outline"])
        self.api(f"/_fixture/tasks/{task_id}/release/2", method="POST")
        second = self.wait(lambda: (state if len((state := self.task(task_id))["calls"]) == 3 else None), "later dispatch after second completion")
        partial = self.api(f"/api/tasks/{task_id}/partial-note")
        batches = [s for s in partial["sections"] if s["kind"] == "vision_batch"]
        evidence = json.dumps({"projection": {key: partial.get(key) for key in
            ("status", "reason", "attempt_id", "revision", "source_revision", "generation_revision")},
            "section_kinds": [section.get("kind") for section in partial["sections"][:8]],
            "persisted_identity": second["partial"],
            "calls": [{key: call.get(key) for key in ("batch", "state")} for call in second["calls"][:4]],
            "recent_events": [{key: event.get(key) for key in ("event", "phase", "status")}
                              for event in second["events"][-8:]]}, sort_keys=True)
        self.assertEqual(len(batches), 1, evidence)
        self.assertIn("Synthetic visual batch 2", batches[0]["markdown"])
        self.assertFalse(partial["verified"])
        self.assertEqual(partial["attempt_id"], initial["attempt_id"])
        self.assertEqual(partial["source_revision"], initial["source_revision"])
        self.assertTrue(any(e["event"] == "partial_section_ready" for e in second["events"]))
        self.assert_native_visual_join(task_id, partial, second["partial"])
        self.assertLessEqual(len(second["events"]), second["event_snapshot_limit"])
        self.api(f"/_fixture/tasks/{task_id}/release/1", method="POST")
        self.wait(lambda: len([s for s in self.api(f"/api/tasks/{task_id}/partial-note")["sections"] if s["kind"] == "vision_batch"]) == 2, "first batch joins second")
        before = self.wait(lambda: (state if (state := self.task(task_id))["active_completions"] == 2 and len(state["calls"]) == 4 else None), "later calls held")
        started = time.monotonic(); self.api(f"/api/tasks/{task_id}/cancel", method="POST")
        cancelled = self.wait(lambda: (state if (state := self.task(task_id))["status"] == "cancelled"
            and state["active_completions"] == 0 and state["queue"]["callback_finished"] else None), "queue and held completions drain")
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(cancelled["calls"]), len(before["calls"]))
        self.assertEqual(cancelled["hashes"], before["hashes"])
        self.assertEqual(cancelled["assets"], before["assets"])
        self.assertEqual(cancelled["hashes"]["source_media_path"], self.fixture["media_sha256"])
        self.assertEqual(cancelled["transcript"], first["transcript"])
        for name in ("source_media_path", "media_path", "transcript.json", "embedded_subtitle.srt", "draft.md"):
            self.assertEqual(cancelled["hashes"][name], first["hashes"][name])
        final = self.api(f"/api/tasks/{task_id}/partial-note")
        self.assertFalse(final["verified"])
        self.assertEqual(len([s for s in final["sections"] if s["kind"] == "vision_batch"]), 2)
        other = self.upload("b")
        self.wait(lambda: self.task(other)["active_completions"] == 2, "changed input has its own held attempt")
        changed = self.api(f"/api/tasks/{other}/partial-note")
        self.assertNotEqual(changed["source_revision"], initial["source_revision"])
        self.assertNotEqual(changed["attempt_id"], initial["attempt_id"])
        self.assertEqual([s["kind"] for s in changed["sections"]], ["temporal_outline"])
        self.api(f"/api/tasks/{other}/cancel", method="POST")
        self.wait(lambda: self.task(other)["active_completions"] == 0 and self.task(other)["queue"]["callback_finished"], "changed input drains")
        self.assertEqual(self.task(task_id)["hashes"], cancelled["hashes"])
        self.assertEqual(self.task(task_id)["assets"], cancelled["assets"])
        self.assertEqual(self.api("/_fixture/state")["forbidden_attempts"], [])

    def test_forced_release_check_is_denied_and_recorded(self):
        self.launch("""
phase = fixture.startup_phase
def assert_startup_order(value):
    controls = [thread for thread in fixture.threading.enumerate()
                if thread.name == 'visual-fixture-control']
    if value in {'offline_guard_imports', 'application_imports', 'application_ready'}:
        assert not controls, 'Native/application imports must precede the stdin reader'
    if value in {'media_a_tool_check', 'media_a_generation', 'media_b_generation'}:
        assert len(controls) == 1 and controls[0].is_alive(), 'Control must be live before generation'
    phase(value)
fixture.startup_phase = assert_startup_order
""")
        phases = [json.loads(line)["fixture_startup_phase"] for line in self.logs
                  if line.startswith('{"fixture_startup_phase":')]
        self.assertLess(phases.index("application_ready"), phases.index("control_start"))
        self.assertLess(phases.index("control_start"), phases.index("media_a_generation"))
        self.api("/api/update/status")
        self.assertEqual(self.api("/_fixture/state")["forbidden_attempts"], [])
        self.client.post(self.base + "/api/update/check")
        state = self.api("/_fixture/state")
        self.assertIn("external_network_blocked", state["forbidden_attempts"])
        self.assertGreater(state["forbidden_attempt_count"], 0)

    def test_missing_ffprobe_reports_the_actual_failed_startup_phase(self):
        bootstrap = f"sys.path.insert(0, {str(ROOT / 'backend')!r})\n" + """
from app import runtime
runtime.ffprobe_bin = lambda: None
"""
        with self.assertRaisesRegex(AssertionError, "Installed FFmpeg and FFprobe are required"):
            self.launch(bootstrap)
        self.assertNotEqual(self.child.returncode, 0)
        phases = [json.loads(line)["fixture_startup_phase"] for line in self.logs
                  if line.startswith('{"fixture_startup_phase":')]
        self.assertEqual(phases[-1], "media_a_tool_check")
        self.assertNotIn("media_a_generation", phases)
        self.assertNotIn("server_ready", phases)

    def test_blocked_startup_retains_one_stack_dump_before_failure(self):
        bootstrap = """
dump = fixture.faulthandler.dump_traceback_later
fixture.faulthandler.dump_traceback_later = lambda *a, **kw: dump(.1, repeat=False)
def blocked_startup(*args):
    fixture.startup_phase('test_blocked_import')
    time.sleep(.4)
    raise RuntimeError('Owned startup block finished')
fixture.configure_fixture = blocked_startup
"""
        with self.assertRaisesRegex(AssertionError, "Owned startup block finished"):
            self.launch(bootstrap)
        log = "".join(self.logs)
        self.assertEqual(log.count("Timeout ("), 1)
        self.assertIn("test_blocked_import", log)
        self.assertIn("in blocked_startup", log)
        self.assertNotIn("in control", log, "No stdin reader may block optional native imports")
        self.assertNotIn('"server_ready"', log)

    def test_control_reader_stops_and_reaps_generation_after_imports(self):
        bootstrap = """
def held_generation(directory, shutdown, variant):
    from app import media
    processes = []
    original = media.subprocess.Popen
    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    marker = directory / 'owned-generation.pid'
    command = [sys.executable, '-c',
        'import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)',
        str(marker)]
    try:
        with fixture.patch.object(media.subprocess, 'Popen', side_effect=spawn):
            fixture.run_owned_command(command, shutdown)
    finally:
        assert len(processes) == 1 and processes[0].poll() is not None, 'Owned child must be reaped'
        fixture.startup_phase('test_generation_reaped')
fixture.generate_media = held_generation
"""
        errors = []
        def request_shutdown():
            deadline = time.monotonic() + 15
            marker = self.data / "fixture-inputs/owned-generation.pid"
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            if not marker.exists():
                errors.append("Owned child did not start")
                return
            self.child.stdin.write("shutdown\n"); self.child.stdin.flush()
        stopper = threading.Thread(target=request_shutdown)
        stopper.start()
        try:
            with self.assertRaisesRegex(AssertionError, "Owned fixture generation was stopped"):
                self.launch(bootstrap)
        finally:
            stopper.join(16)
        self.assertFalse(stopper.is_alive())
        self.assertEqual(errors, [])
        self.assertNotEqual(self.child.returncode, 0)
        self.assertIn('"fixture_startup_phase": "test_generation_reaped"', "".join(self.logs))
        self.assertNotIn('"fixture_startup_phase": "server_ready"', "".join(self.logs))



class OwnedGenerationCleanupTests(unittest.TestCase):
    def test_thread_diagnostics_are_bounded_locations_without_locals_or_source(self):
        spec = importlib.util.spec_from_file_location("visual_fixture_diagnostics", ROOT / "scripts/progressive-visual-fixture.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        secret = "must-not-appear-in-diagnostic-locals"
        frame = sys._getframe()
        with patch.object(fixture.sys, "_current_frames", return_value={i: frame for i in range(40)}):
            result = fixture.thread_locations(ROOT)
        self.assertEqual(result["thread_count"], 40)
        self.assertTrue(result["threads_truncated"])
        self.assertEqual(len(result["threads"]), 32)
        for thread in result["threads"]:
            self.assertLessEqual(len(thread["locations"]), 32)
            for location in thread["locations"]:
                self.assertEqual(set(location), {"file", "function", "line"})
                self.assertFalse(Path(location["file"]).is_absolute())
        self.assertNotIn(secret, json.dumps(result))
        chain = None
        for _ in range(40):
            chain = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(ROOT / "backend/app/media.py"),
                co_name="_run"), f_lineno=61, f_back=chain)
        with patch.object(fixture.sys, "_current_frames", return_value={1: chain}):
            capped = fixture.thread_locations(ROOT)
        self.assertEqual(len(capped["threads"][0]["locations"]), 32)
        self.assertTrue(capped["threads"][0]["frames_truncated"])

    def test_generation_shutdown_reaps_the_actual_owned_child(self):
        spec = importlib.util.spec_from_file_location("visual_fixture_cleanup", ROOT / "scripts/progressive-visual-fixture.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        with patch.object(sys, "path", [str(ROOT / "backend"), *sys.path]):
            from app import media
        processes, errors, shutdown = [], [], threading.Event()
        original = subprocess.Popen
        def spawn(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        with tempfile.TemporaryDirectory(prefix="visual-generation-cleanup-") as directory:
            marker = Path(directory) / "owned-child.pid"
            # No packages are required by this fixture. Launch the interpreter
            # directly so the asserted PID is not a Windows venv redirector.
            command = [sys._base_executable, "-c", "import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)", str(marker)]
            def stop_when_started():
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                if not marker.exists(): errors.append("Owned generation child never started")
                shutdown.set()
            stopper = threading.Thread(target=stop_when_started)
            stopper.start()
            try:
                with patch.object(media.subprocess, "Popen", side_effect=spawn):
                    with self.assertRaisesRegex(RuntimeError, "generation was stopped"):
                        fixture.run_owned_command(command, shutdown)
                    self.assertTrue(processes and all(process.poll() is not None for process in processes),
                                    "Generation must reap its child before returning, before test cleanup")
            finally:
                shutdown.set(); stopper.join(6)
                for process in processes:
                    if process.poll() is None:
                        process.kill(); process.wait(5)
            self.assertFalse(stopper.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(processes), 1)
            self.assertEqual(int(marker.read_text()), processes[0].pid)
            self.assertIsNotNone(processes[0].returncode, "The actual owned child must be killed and reaped before generation returns")
