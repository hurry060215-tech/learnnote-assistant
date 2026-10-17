"""Bounded owned-input diagnostic; never substitutes for the visual acceptance gate."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NORMALIZATION_DEADLINE = 15
WORKER_DEADLINE = 25
RECORD_LIMIT = 16384


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command_identity(command, source, output_directory):
    values = list(map(str, command))
    if values.count(str(source)) != 1 or Path(values[-1]).parent.parent != output_directory:
        raise AssertionError("Diagnostic command must use only the exact owned source/output")
    return [Path(values[0]).name, *["<owned-input>" if value == str(source) else value
            for value in values[1:-1]], "<owned-output>"]


def set_child_stdin(options, mode):
    if mode not in {"inherited", "devnull"}: raise ValueError("Unknown diagnostic stdin arm")
    # Explicitly retain the historical comparison if production defaults change.
    # This touches only the normalization child, never the worker control input.
    options["stdin"] = None if mode == "inherited" else subprocess.DEVNULL


def worker(source, directory, stdin_mode):
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.update(LEARNNOTE_DATA_DIR=str(directory), HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1", ORT_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_TELEMETRY="1")
    shutdown = threading.Event()
    with ExitStack() as stack:
        stack.enter_context(load_script("stdin_probe_offline", "test-backend-offline.py").offline_network())
        from app import media
        # Match the fixture's reader, but never redirect its own control channel.
        def control():
            for line in sys.stdin:
                if line.strip() == "shutdown":
                    shutdown.set()
                    return
        reader = threading.Thread(target=control, name="stdin-probe-control", daemon=True)
        reader.start()
        result = {"mode": stdin_mode, "worker_pid": os.getpid(), "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "deadline_seconds": NORMALIZATION_DEADLINE, "stdout_bytes": None, "stderr_bytes": None}
        processes = []
        original = subprocess.Popen
        def launch(command, **kwargs):
            set_child_stdin(kwargs, stdin_mode)
            result["command"] = command_identity(command, source, directory)
            result["tool_executable"] = str(Path(command[0]).resolve())
            result["stdin"] = "DEVNULL" if kwargs.get("stdin") == subprocess.DEVNULL else "inherited"
            process = original(command, **kwargs)
            processes.append(process)
            result["child_pid"] = process.pid
            print(json.dumps({"child_started": {key: result[key] for key in
                ("mode", "worker_pid", "input_sha256", "command", "stdin", "child_pid", "tool_executable")}}), flush=True)
            communicate = process.communicate
            def observed_communicate(*args, **options):
                stdout, stderr = communicate(*args, **options)
                result["stdout_bytes"] = len((stdout or "").encode("utf-8"))
                result["stderr_bytes"] = len((stderr or "").encode("utf-8"))
                return stdout, stderr
            process.communicate = observed_communicate
            return process
        started = time.monotonic()
        def check():
            if shutdown.is_set(): raise RuntimeError("Owned diagnostic cancellation requested")
            if time.monotonic() - started >= NORMALIZATION_DEADLINE: raise TimeoutError("Owned normalization diagnostic deadline")
        try:
            with patch.object(media.subprocess, "Popen", side_effect=launch), media.media_cancellation(check):
                output = media.normalize_video(source, directory / "normalized.mp4")
            result.update(outcome="completed", output_bytes=output.stat().st_size,
                          output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
        except Exception as error:
            result.update(outcome="timeout" if isinstance(error, TimeoutError) else "error",
                          error_type=type(error).__name__, error=str(error)[:300])
        finally:
            result["elapsed_seconds"] = time.monotonic() - started
            result["child_count"] = len(processes)
            result["child_exit_codes"] = [process.poll() for process in processes]
            result["direct_children_reaped"] = bool(processes) and all(process.poll() is not None for process in processes)
        print(json.dumps({"probe_result": result}), flush=True)
        if not shutdown.wait(5):
            raise RuntimeError("Owned diagnostic control shutdown was not received")
        reader.join(1)
        if reader.is_alive():
            raise RuntimeError("Owned diagnostic control reader did not drain")


class WindowsJob:
    """Unnamed containment for this probe's one owned, start-gated worker tree."""
    def __init__(self, child):
        import ctypes
        from ctypes import wintypes as w
        self.ctypes, self.pid, self.handle = ctypes, child.pid, None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.kernel, name); function.argtypes, function.restype = arguments, result
        class Limits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", w.DWORD),
                ("min_working", ctypes.c_size_t), ("max_working", ctypes.c_size_t), ("active_limit", w.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Limits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]
        try:
            self.handle = self.kernel.CreateJobObjectW(None, None)
            if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
            limits = Extended(); limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.kernel.AssignProcessToJobObject(self.handle, int(child._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as error:
            try: self.close()
            except BaseException as cleanup: error.add_note(f"Job close also failed: {cleanup}")
            raise

    def active(self):
        c = self.ctypes
        class Accounting(c.Structure):
            _fields_ = [("times", c.c_int64 * 4), ("faults", c.c_uint32), ("total", c.c_uint32),
                        ("active", c.c_uint32), ("terminated", c.c_uint32)]
        value = Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, c.byref(value), c.sizeof(value), None):
            raise c.WinError(c.get_last_error())
        return value.active

    def terminate(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        deadline = time.monotonic() + 5
        while self.active():
            if time.monotonic() >= deadline: raise TimeoutError("Owned job descendants did not exit")
            time.sleep(.01)

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.kernel.CloseHandle(handle):
                raise self.ctypes.WinError(self.ctypes.get_last_error())


def stop_owned(child, expected_command, cooperative_seconds=5, job=None):
    if list(child.args) != expected_command or expected_command[0] != sys.executable:
        raise AssertionError("Cleanup requires the exact owned Python launch")
    if os.name == "nt" and (job is None or job.pid != child.pid):
        raise AssertionError("Cleanup requires the owned worker Job Object")
    outcome = "already_exited"
    if child.poll() is None:
        try:
            child.stdin.write("shutdown\n"); child.stdin.flush()
        except (BrokenPipeError, OSError): pass
        try:
            child.wait(cooperative_seconds)
            outcome = "cooperative"
        except subprocess.TimeoutExpired:
            outcome = "owned_tree_fallback"
    if job:
        if job.active():
            job.terminate()
            if outcome == "already_exited": outcome = "owned_tree_after_parent_exit"
            elif outcome == "cooperative": outcome = "owned_tree_after_cooperative_exit"
    else:
        # The owned isolated group remains addressable after its leader exits.
        try:
            os.killpg(child.pid, signal.SIGKILL)
            if outcome == "already_exited": outcome = "owned_tree_after_parent_exit"
            elif outcome == "cooperative": outcome = "owned_tree_after_cooperative_exit"
        except ProcessLookupError: pass
    child.wait(10)
    return outcome


def create_owned_job(child):
    return WindowsJob(child) if os.name == "nt" else None


def run_case(source, directory, stdin_mode, *, command=None, deadline=WORKER_DEADLINE, tools=None):
    command = command or [sys.executable, str(Path(__file__).resolve()), "--worker", stdin_mode,
               "--source", str(source), "--directory", str(directory)]
    env = {key: value for key, value in os.environ.items() if key.upper() in
           {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL"}}
    env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    if tools:
        env.update(FFMPEG_BIN_PATH=tools["ffmpeg"]["executable"], FFPROBE_BIN_PATH=tools["ffprobe"]["executable"])
    result = {"mode": stdin_mode, "outcome": "worker_timeout"}
    try:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env=env, start_new_session=os.name != "nt")
    except Exception as error:
        return {**result, "outcome": "launch_error", "harness_error": f"{type(error).__name__}: {error}"[:300]}
    result["worker_pid"] = child.pid
    job = None
    try:
        job = create_owned_job(child)
        child.stdin.write("start\n"); child.stdin.flush()
    except BaseException as error:
        result["harness_error"] = f"Containment/start failure: {type(error).__name__}: {error}"[:300]
        try:
            if child.poll() is None: child.kill()
            child.communicate(timeout=5)
        except BaseException as cleanup:
            result["cleanup_error"] = str(cleanup)[:300]
        finally:
            if job:
                try: job.close()
                except Exception as cleanup: result.setdefault("cleanup_error", str(cleanup)[:300])
            if child.poll() is not None:
                for stream in (child.stdin, child.stdout, child.stderr): stream.close()
        return {**result, "worker_exit_code": child.poll()}
    records, errors, stderr, started_records = queue.Queue(maxsize=1), [], [], []
    stderr_bytes = result_count = 0
    def record_error(message):
        if len(errors) < 4: errors.append(message[:200])
    def read_stdout():
        nonlocal result_count
        while line := child.stdout.readline(RECORD_LIMIT + 1):
            try:
                if len(line) > RECORD_LIMIT: raise ValueError("Diagnostic stdout record exceeds bound")
                value = json.loads(line)
                if not isinstance(value, dict): raise ValueError("Diagnostic record must be an object")
                if "child_started" in value:
                    if started_records: raise ValueError("Duplicate child launch record")
                    started = value["child_started"]
                    if (not isinstance(started, dict) or started.get("mode") != stdin_mode
                        or started.get("worker_pid") != child.pid or type(started.get("child_pid")) is not int
                        or started["child_pid"] <= 0
                        or not re.fullmatch(r"[a-f0-9]{64}", str(started.get("input_sha256", "")))
                        or not isinstance(started.get("command"), list) or not started["command"]
                        or not all(isinstance(arg, str) for arg in started["command"])):
                        raise ValueError("Child launch does not match the owned worker")
                    started_records.append(started)
                elif "probe_result" in value:
                    result_count += 1
                    if result_count != 1: raise ValueError("Duplicate result record")
                    records.put_nowait(value["probe_result"])
                else: raise ValueError("Unknown diagnostic record")
            except (ValueError, TypeError, queue.Full) as error:
                record_error(type(error).__name__ + ": " + str(error))
    def read_stderr():
        nonlocal stderr_bytes
        while chunk := child.stderr.read(4096):
            if stderr_bytes < RECORD_LIMIT: stderr.append(chunk[:RECORD_LIMIT-stderr_bytes])
            stderr_bytes += len(chunk)
    readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    for reader in readers: reader.start()
    try:
        received = records.get(timeout=deadline)
        if not isinstance(received, dict) or received.get("worker_pid") != child.pid or received.get("mode") != stdin_mode:
            raise ValueError("Diagnostic result does not match the owned worker")
        result.update(received)
    except queue.Empty:
        result["harness_error"] = "Owned worker did not return a complete result before its deadline"
        result["worker_exit_code_before_cleanup"] = child.poll()
    except Exception as error:
        result["harness_error"] = f"{type(error).__name__}: {error}"[:300]
    finally:
        try: result["worker_cleanup"] = stop_owned(child, command, job=job)
        except Exception as error:
            result["cleanup_error"] = f"{type(error).__name__}: {error}"[:300]
        finally:
            if job:
                try: job.close()
                except Exception as error: result.setdefault("cleanup_error", str(error)[:300])
        for reader in readers: reader.join(2)
        if tools: result["expected_tool_executable"] = tools["ffmpeg"]["executable"]
        if started_records and result["outcome"] == "worker_timeout":
            for key, value in started_records[0].items(): result.setdefault(key, value)
        result.update(worker_exit_code=child.poll(), reader_threads_drained=all(not reader.is_alive() for reader in readers),
                      parser_errors=errors, child_launches=started_records, worker_stderr="".join(stderr),
                      stderr_truncated=stderr_bytes > RECORD_LIMIT)
        if result["reader_threads_drained"]:
            for stream in (child.stdin, child.stdout, child.stderr): stream.close()
    return result


def case_complete(case):
    launches = case.get("child_launches", [])
    if len(launches) != 1 or not isinstance(launches[0], dict): return False
    keys = ("mode", "worker_pid", "child_pid", "input_sha256", "command", "stdin", "tool_executable")
    if any(key not in case or case[key] != launches[0].get(key) for key in keys): return False
    if (type(case["child_pid"]) is not int or case["child_pid"] <= 0
        or type(case["worker_pid"]) is not int or case["worker_pid"] <= 0
        or not isinstance(case["command"], list) or not case["command"]
        or not isinstance(case.get("tool_executable"), str) or not case["tool_executable"]
        or case["tool_executable"] != case.get("expected_tool_executable")): return False
    for key in ("stdout_bytes", "stderr_bytes"):
        if case.get(key) is not None and (type(case[key]) is not int or case[key] < 0): return False
    if case.get("outcome") == "completed" and (type(case.get("output_bytes")) is not int
        or case["output_bytes"] <= 0 or not re.fullmatch(r"[a-f0-9]{64}", str(case.get("output_sha256", "")))): return False
    exits = case.get("child_exit_codes")
    return (case.get("outcome") in {"completed", "timeout", "error"}
        and (case.get("outcome") != "error" or case.get("error_type") == "MediaProcessingError")
        and (case.get("outcome") != "timeout" or case.get("error_type") == "TimeoutError")
        and re.fullmatch(r"[a-f0-9]{64}", str(case.get("input_sha256", ""))) is not None
        and case.get("mode") in {"devnull", "inherited"}
        and case.get("stdin") == ("DEVNULL" if case.get("mode") == "devnull" else "inherited")
        and isinstance(exits, list) and len(exits) == 1 and type(exits[0]) is int
        and (case.get("outcome") != "completed" or exits[0] == 0)
        and case.get("worker_exit_code") == 0 and case.get("reader_threads_drained")
        and not case.get("parser_errors") and not case.get("harness_error") and not case.get("cleanup_error")
        and case.get("child_count") == 1 and case.get("direct_children_reaped") is True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=Path("build/media-stdin-probe"))
    parser.add_argument("--worker", choices=("inherited", "devnull"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.worker:
        if sys.stdin.readline().strip() != "start":
            raise RuntimeError("Owned worker requires containment before its start handshake")
        worker(args.source.resolve(), args.directory.resolve(), args.worker)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"diagnostic_complete": False, "platform": sys.platform, "windows_evidence": os.name == "nt", "cases": [],
              "scope": "Owned identical media/normalization; only FFmpeg child stdin differs. Not a visual acceptance pass."}
    primary = None
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        with tempfile.TemporaryDirectory(prefix="learnnote-stdin-probe-") as temporary, ExitStack() as stack:
            root = Path(temporary)
            os.environ["LEARNNOTE_DATA_DIR"] = str(root / "data")
            stack.enter_context(load_script("probe_parent_offline", "test-backend-offline.py").offline_network())
            fixture = load_script("probe_visual_input", "progressive-visual-fixture.py")
            from app.runtime import ffmpeg_bin, ffprobe_bin
            resolved = {name: str(Path(binary).resolve()) for name, binary in
                (("ffmpeg", ffmpeg_bin()), ("ffprobe", ffprobe_bin())) if binary and Path(binary).is_file()}
            if len(resolved) != 2: raise RuntimeError("Installed FFmpeg and FFprobe paths must be files")
            os.environ.update(FFMPEG_BIN_PATH=resolved["ffmpeg"], FFPROBE_BIN_PATH=resolved["ffprobe"])
            report["tools"] = {name: {"executable": binary, "version": subprocess.run(
                [binary, "-version"], stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()[0]}
                for name, binary in resolved.items()}
            source = fixture.generate_media(root, threading.Event())
            for mode in ("inherited", "devnull"):
                directory = root / mode; directory.mkdir()
                report["cases"].append(run_case(source, directory, mode, tools=report["tools"]))
                (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            left, right = report["cases"]
            report["identical_input_and_command"] = left.get("input_sha256") == right.get("input_sha256") and left.get("command") == right.get("command") and bool(left.get("command"))
            report["diagnostic_complete"] = report["identical_input_and_command"] and all(case_complete(case) for case in report["cases"])
    except BaseException as error:
        primary = error
        report["failure"] = f"{type(error).__name__}: {error}"[:500]
    finally:
        try: (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        except BaseException:
            if primary is None: raise
    if primary: raise primary
    if not report["diagnostic_complete"]: raise RuntimeError("Owned diagnostic control, identity or cleanup was incomplete; retained cases are not a visual gate pass")


if __name__ == "__main__": main()
