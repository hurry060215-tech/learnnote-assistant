"""Probe control contracts; only the hosted report can establish Windows outcomes."""
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("stdin_probe", ROOT / "scripts/windows-media-stdin-probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class WindowsMediaStdinProbeTests(unittest.TestCase):
    def test_exact_command_identity_preserves_flags_and_rejects_other_paths(self):
        source, directory = Path("owned/input.mp4"), Path("owned/case")
        command = ["ffmpeg", "-y", "-i", str(source), "-c:v", "copy", str(directory / "temp/out.mp4")]
        self.assertEqual(probe.command_identity(command, source, directory),
                         ["ffmpeg", "-y", "-i", "<owned-input>", "-c:v", "copy", "<owned-output>"])
        for altered in ([*command[:-1], "other/out.mp4"], [*command, str(source)]):
            with self.assertRaises(AssertionError): probe.command_identity(altered, source, directory)

    def test_completion_requires_real_control_identity_and_cleanup_evidence(self):
        case = {"mode": "inherited", "stdin": "inherited", "outcome": "completed", "worker_exit_code": 0,
                "reader_threads_drained": True, "child_count": 1, "direct_children_reaped": True,
                "tool_executable": "/owned/ffmpeg", "expected_tool_executable": "/owned/ffmpeg",
                "output_bytes": 123, "output_sha256": "c" * 64, "worker_pid": 11, "child_pid": 12, "command": ["ffmpeg"], "input_sha256": "a" * 64, "child_exit_codes": [0]}
        case["child_launches"] = [{key: case[key] for key in
            ("mode", "worker_pid", "child_pid", "input_sha256", "command", "stdin", "tool_executable")}]
        self.assertTrue(probe.case_complete(case))
        self.assertTrue(probe.case_complete({**case, "outcome": "timeout", "error_type": "TimeoutError"}))
        for change in ({"worker_exit_code": 1}, {"reader_threads_drained": False}, {"child_count": 0},
                       {"direct_children_reaped": False}, {"child_launches": []}, {"stdin": "DEVNULL"},
                       {"parser_errors": ["bad"]}, {"cleanup_error": "failed"}, {"harness_error": "failed"},
                       {"outcome": "worker_timeout"}, {"outcome": "error", "error_type": "AssertionError"},
                       {"input_sha256": "b" * 64}, {"input_sha256": None}, {"worker_pid": 13},
                       {"child_exit_codes": [None]}, {"child_exit_codes": [1]}, {"output_sha256": None},
                       {"output_bytes": -1}, {"stdout_bytes": -1}, {"expected_tool_executable": "/other/ffmpeg"}):
            self.assertFalse(probe.case_complete({**case, **change}), change)

    def test_launch_failure_is_a_retained_case(self):
        with patch.object(probe.subprocess, "Popen", side_effect=OSError("owned launch failed")):
            case = probe.run_case(Path("source"), Path("output"), "devnull")
        self.assertEqual(case["outcome"], "launch_error")
        self.assertIn("owned launch failed", case["harness_error"])
        self.assertFalse(probe.case_complete(case))

    def test_malformed_and_oversized_output_remains_bounded_and_drains(self):
        code = "import sys; sys.stdin.readline(); print('x'*20000, flush=True); print('{}',flush=True); sys.stdin.readline()"
        case = probe.run_case(Path("source"), Path("output"), "inherited",
                              command=[sys.executable, "-c", code], deadline=.3)
        self.assertEqual(case["outcome"], "worker_timeout")
        self.assertGreater(len(case["parser_errors"]), 0)
        self.assertLessEqual(len(case["parser_errors"]), 4)
        self.assertTrue(case["reader_threads_drained"])
        self.assertEqual(case["worker_exit_code"], 0)
        self.assertEqual(case["worker_cleanup"], "cooperative")

    def test_missing_final_identity_is_not_backfilled_from_launch(self):
        record = {"mode": "inherited", "child_pid": 12, "command": ["ffmpeg"], "stdin": "inherited",
                  "tool_executable": sys.executable, "input_sha256": "a" * 64}
        code = ("import sys,os,json; assert sys.stdin.readline().strip()=='start'; "
                f"start={record!r}; start['worker_pid']=os.getpid(); print(json.dumps({{'child_started':start}}),flush=True); "
                "result=dict(start,outcome='completed',child_count=1,direct_children_reaped=True,child_exit_codes=[0],"
                "output_bytes=12,output_sha256='b'*64); del result['input_sha256']; "
                "print(json.dumps({'probe_result':result}),flush=True); sys.stdin.readline()")
        tools = {name: {"executable": sys.executable} for name in ("ffmpeg", "ffprobe")}
        case = probe.run_case(Path("source"), Path("output"), "inherited",
                              command=[sys.executable, "-c", code], tools=tools)
        self.assertEqual(case["outcome"], "completed")
        self.assertNotIn("input_sha256", case)
        self.assertFalse(probe.case_complete(case))
        self.assertTrue(case["reader_threads_drained"])

    def test_primary_timeout_survives_cleanup_error(self):
        # An already exited owned process makes the injected cleanup error safe.
        command = [sys.executable, "-c", "import sys; assert sys.stdin.readline().strip()=='start'"]
        original = probe.stop_owned
        def fail_after_cleanup(child, expected, **kwargs):
            original(child, expected, **kwargs)
            raise RuntimeError("secondary cleanup diagnostic")
        with patch.object(probe, "stop_owned", side_effect=fail_after_cleanup):
            case = probe.run_case(Path("source"), Path("output"), "devnull", command=command, deadline=.3)
        self.assertIn("before its deadline", case["harness_error"])
        self.assertIn("secondary", case["cleanup_error"])
        self.assertTrue(case["reader_threads_drained"])
        self.assertFalse(probe.case_complete(case))

    def test_exact_owned_process_tree_stops_descendant_after_live_or_exited_parent(self):
        for exits_first in (False, True, "cooperative"):
            with self.subTest(exits_first=exits_first), tempfile.TemporaryDirectory(prefix="stdin-probe-cleanup-") as temporary:
                marker = Path(temporary) / "child.pid"
                code = ("import subprocess,sys,time; assert sys.stdin.readline().strip()=='start'; "
                        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                        f"open({str(marker)!r},'w').write(str(p.pid)); " + ("sys.stdin.readline()" if exits_first == "cooperative" else "" if exits_first else "time.sleep(60)"))
                command = [sys.executable, "-c", code]
                child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, start_new_session=os.name != "nt")
                job = None
                try:
                    job = probe.create_owned_job(child)
                    child.stdin.write("start\n"); child.stdin.flush()
                    deadline = time.monotonic() + 5
                    while not marker.exists() and time.monotonic() < deadline: time.sleep(.01)
                    self.assertTrue(marker.exists())
                    descendant = int(marker.read_text())
                    if exits_first is True: self.assertEqual(child.wait(5), 0)
                    with self.assertRaises(AssertionError): probe.stop_owned(child, [sys.executable, "wrong"], job=job)
                    self.assertEqual(probe.stop_owned(child, command, cooperative_seconds=.05, job=job),
                                     "owned_tree_after_cooperative_exit" if exits_first == "cooperative" else
                                     "owned_tree_after_parent_exit" if exits_first else "owned_tree_fallback")
                    child.communicate(timeout=3)
                    self.assertIsNotNone(child.poll())
                    if job: self.assertEqual(job.active(), 0)
                    if os.name == "nt":
                        import ctypes
                        from ctypes import wintypes
                        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                        kernel.OpenProcess.restype = wintypes.HANDLE
                        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                        kernel.WaitForSingleObject.restype = wintypes.DWORD
                        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                        handle = kernel.OpenProcess(0x00100000, False, descendant)
                        if handle:
                            try: self.assertEqual(kernel.WaitForSingleObject(handle, 3000), 0)
                            finally: kernel.CloseHandle(handle)
                        else: self.assertEqual(ctypes.get_last_error(), 87)
                    else:
                        state = Path(f"/proc/{descendant}/stat")
                        self.assertTrue(not state.exists() or state.read_text().split()[2] == "Z")
                finally:
                    if child.poll() is None: probe.stop_owned(child, command, cooperative_seconds=.05, job=job)
                    if job: job.close()
                    for stream in (child.stdin, child.stdout, child.stderr): stream.close()

    def test_containment_failure_never_releases_start_handshake(self):
        with tempfile.TemporaryDirectory(prefix="stdin-probe-start-") as temporary:
            marker = Path(temporary) / "started"
            code = f"import sys; sys.stdin.readline(); open({str(marker)!r},'w').write('started')"
            with patch.object(probe, "create_owned_job", side_effect=OSError("assignment denied")):
                case = probe.run_case(Path("source"), Path("output"), "inherited", command=[sys.executable, "-c", code])
            self.assertIn("assignment denied", case["harness_error"])
            self.assertIsNotNone(case["worker_exit_code"])
            self.assertFalse(marker.exists())

    def test_main_retains_both_cases_before_failing_incomplete_control(self):
        with tempfile.TemporaryDirectory(prefix="stdin-probe-report-") as temporary:
            output = Path(temporary) / "report"
            fixture = SimpleNamespace(generate_media=lambda root, shutdown: root / "owned.mp4")
            offline = SimpleNamespace(offline_network=nullcontext)
            runtime = SimpleNamespace(ffmpeg_bin=lambda: sys.executable, ffprobe_bin=lambda: sys.executable)
            cases = [{"mode": "inherited", "outcome": "worker_timeout", "harness_error": "primary deadline"},
                     {"mode": "devnull", "outcome": "completed", "worker_exit_code": 0}]
            with patch.object(probe, "load_script", side_effect=[offline, fixture]), \
                 patch.dict(sys.modules, {"app.runtime": runtime}), \
                 patch.object(probe.subprocess, "run", return_value=SimpleNamespace(stdout="owned version\n")), \
                 patch.object(probe, "run_case", side_effect=cases) as run, \
                 patch.object(sys, "argv", ["probe", str(output)]), patch.dict(os.environ):
                with self.assertRaisesRegex(RuntimeError, "control, identity or cleanup"):
                    probe.main()
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(run.call_count, 2)
            self.assertEqual(report["cases"], cases)
            self.assertFalse(report["diagnostic_complete"])

    def test_explicit_arms_override_changed_production_child_defaults(self):
        for previous in (None, subprocess.PIPE, subprocess.DEVNULL):
            for mode, expected in (("inherited", None), ("devnull", subprocess.DEVNULL)):
                options = {"stdin": previous, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
                probe.set_child_stdin(options, mode)
                self.assertEqual(options, {"stdin": expected, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE})
        with self.assertRaises(ValueError): probe.set_child_stdin({}, "unknown")

    def test_worker_deadline_and_control_order_are_fixed(self):
        source = (ROOT / "scripts/windows-media-stdin-probe.py").read_text()
        worker = source[source.index("def worker("):source.index("def stop_owned(")]
        self.assertLess(worker.index("from app import media"), worker.index("reader.start()"))
        self.assertLess(worker.index("reader.start()"), worker.index("media.normalize_video"))
        self.assertEqual(probe.NORMALIZATION_DEADLINE, 15)
        self.assertEqual(probe.WORKER_DEADLINE, 25)
        self.assertIn("set_child_stdin(kwargs, stdin_mode)", worker)
        self.assertIn('"child_started"', worker)
        self.assertNotIn('"-nostdin"', worker)


if __name__ == "__main__": unittest.main()
