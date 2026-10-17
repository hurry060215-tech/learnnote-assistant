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

    def launch(self):
        env = {key: value for key, value in os.environ.items() if key.upper() in
               {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL"}}
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        self.child = subprocess.Popen([sys.executable, str(ROOT / "scripts/progressive-visual-fixture.py"),
            "--data-dir", str(self.data)], cwd=ROOT, env=env, start_new_session=os.name != "nt", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8")
        lines = queue.Queue()
        def read():
            for line in self.child.stdout:
                self.logs.append(line)
                if line.startswith('{"fixture_origin":'): lines.put(json.loads(line))
        self.reader = threading.Thread(target=read, daemon=True); self.reader.start()
        deadline = time.monotonic() + 45
        while True:
            try:
                self.fixture = lines.get(timeout=.1); break
            except queue.Empty:
                if self.child.poll() is not None or time.monotonic() >= deadline:
                    self.fail("Visual fixture startup failed: " + "".join(self.logs))
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
        initial = self.api(f"/api/tasks/{task_id}/partial-note")
        self.assertFalse(initial["verified"])
        self.assertEqual([s["kind"] for s in initial["sections"]], ["temporal_outline"])
        self.api(f"/_fixture/tasks/{task_id}/release/2", method="POST")
        second = self.wait(lambda: (state if len((state := self.task(task_id))["calls"]) == 3 else None), "later dispatch after second completion")
        partial = self.api(f"/api/tasks/{task_id}/partial-note")
        batches = [s for s in partial["sections"] if s["kind"] == "vision_batch"]
        self.assertEqual(len(batches), 1); self.assertIn("Synthetic visual batch 2", batches[0]["markdown"])
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
        self.launch()
        self.api("/api/update/status")
        self.assertEqual(self.api("/_fixture/state")["forbidden_attempts"], [])
        self.client.post(self.base + "/api/update/check")
        state = self.api("/_fixture/state")
        self.assertIn("external_network_blocked", state["forbidden_attempts"])
        self.assertGreater(state["forbidden_attempt_count"], 0)



class OwnedGenerationCleanupTests(unittest.TestCase):
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
            command = [sys.executable, "-c", "import os, pathlib, sys, time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)", str(marker)]
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
