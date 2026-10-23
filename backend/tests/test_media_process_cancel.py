from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.media import _run, media_cancellation
from app import media, media_process


class MediaProcessCancelTests(unittest.TestCase):
    def test_posix_session_cleanup_keeps_original_failure_and_closes_pipes(self):
        for cleanup_error in (None, OSError("synthetic cleanup failure")):
            with self.subTest(cleanup_error=cleanup_error):
                process = Mock(pid=123, stdin=None)
                process.communicate.return_value = ("", "")
                killpg = Mock(side_effect=cleanup_error)
                failure = TimeoutError("synthetic deadline")
                with patch.object(media_process, "os", SimpleNamespace(name="posix", killpg=killpg)), \
                     patch.object(media_process, "signal", SimpleNamespace(SIGKILL=9)), \
                     patch.object(media_process.subprocess, "Popen", return_value=process) as launch:
                    with self.assertRaises(TimeoutError) as caught:
                        with media_process.owned_media_process(["owned-tool"], stdin=subprocess.DEVNULL):
                            raise failure
                self.assertIs(caught.exception, failure)
                self.assertTrue(launch.call_args.kwargs["start_new_session"])
                killpg.assert_called_once_with(123, 9)
                process.stdout.close.assert_called_once()
                process.stderr.close.assert_called_once()

    def assert_process_exited(self, pid):
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes as w
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = (w.DWORD, w.BOOL, w.DWORD), w.HANDLE
            kernel.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
            kernel.CloseHandle.argtypes = (w.HANDLE,)
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if handle:
                try:
                    self.assertEqual(kernel.WaitForSingleObject(handle, 1000), 0, "Owned descendant remains alive")
                finally:
                    kernel.CloseHandle(handle)
            else:
                self.assertEqual(ctypes.get_last_error(), 87)
        else:
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                    stat = Path(f"/proc/{pid}/stat")
                    if stat.exists() and stat.read_text().split()[2] == "Z":
                        return
                except ProcessLookupError:
                    return
                time.sleep(.01)
            self.fail("Owned descendant remains alive")

    def test_descendants_exit_on_cancellation_timeout_success_and_failure(self):
        # The child detaches its stdio, so pipe draining cannot pretend to prove
        # that it stopped. Its actual OS process state is checked independently.
        for outcome in ("cancel", "timeout", "success", "failure"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory) / "descendant.pid"
                script = (
                    "import subprocess,sys,time;from pathlib import Path;"
                    "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],"
                    "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                    "Path(sys.argv[1]).write_text(str(child.pid));"
                    + ("time.sleep(5)" if outcome in {"cancel", "timeout"} else f"sys.exit({7 if outcome == 'failure' else 0})")
                )
                error_type = TimeoutError if outcome == "timeout" else RuntimeError
                def check():
                    if outcome in {"cancel", "timeout"} and marker.exists():
                        raise error_type("synthetic task stop")
                started = time.monotonic()
                with media_cancellation(check):
                    if outcome in {"cancel", "timeout"}:
                        with self.assertRaisesRegex(error_type, "synthetic task stop"):
                            _run([sys._base_executable, "-c", script, str(marker)], "command failed")
                    elif outcome == "failure":
                        with self.assertRaises(media.MediaProcessingError):
                            _run([sys._base_executable, "-c", script, str(marker)], "command failed")
                    else:
                        _run([sys._base_executable, "-c", script, str(marker)], "command failed")
                self.assertLess(time.monotonic() - started, 2)
                self.assert_process_exited(int(marker.read_text()))

    @unittest.skipUnless(os.name == "nt", "Windows suspended launch contract")
    def test_failed_containment_never_executes_command_and_closes_job(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "must-not-start"
            command = [sys._base_executable, "-c", "import sys;from pathlib import Path;Path(sys.argv[1]).touch()", str(marker)]
            jobs, processes = [], []
            real_job, real_popen = media_process.WindowsJob, subprocess.Popen
            def job(process):
                value = real_job(process)
                jobs.append(value)
                return value
            def launch(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process
            with patch.object(media_process, "WindowsJob", side_effect=job), \
                 patch.object(real_job, "resume", side_effect=OSError("synthetic resume failure")), \
                 patch.object(subprocess, "Popen", side_effect=launch), media_cancellation(lambda: None):
                with self.assertRaisesRegex(OSError, "synthetic resume failure"):
                    _run(command, "command failed")
            self.assertFalse(marker.exists())
            self.assertIsNone(jobs[0].handle)
            self.assertIsNotNone(processes[0].returncode)
            self.assertTrue(processes[0].stdout.closed)
            self.assertTrue(processes[0].stderr.closed)

    def test_cancellation_kills_an_already_running_child(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'started'
            command = [sys._base_executable, '-c', 'import sys,time;from pathlib import Path;Path(sys.argv[1]).touch();time.sleep(30)', str(marker)]
            children = []
            real_popen = subprocess.Popen
            def launch(*args, **kwargs):
                child = real_popen(*args, **kwargs)
                children.append(child)
                return child
            def cancelled():
                if marker.exists():
                    raise RuntimeError('test cancellation')
            started = time.monotonic()
            with patch('app.media.subprocess.Popen', side_effect=launch):
                with self.assertRaisesRegex(RuntimeError, 'test cancellation'):
                    with media_cancellation(cancelled):
                        _run(command, 'child failed')
            self.assertTrue(marker.exists())
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNotNone(children[0].poll())
