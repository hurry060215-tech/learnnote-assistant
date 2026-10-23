"""Own cancellable media process trees for their complete lifetime."""
from __future__ import annotations

from contextlib import contextmanager
import os
import signal
import subprocess
import time


class WindowsJob:
    """An unnamed job assigned before the suspended command can spawn children."""

    def __init__(self, process):
        import ctypes
        from ctypes import wintypes as w

        self.ctypes, self.handle, self.pid = ctypes, None, process.pid
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, ctypes.c_void_p], w.BOOL),
            "Thread32Next": ([w.HANDLE, ctypes.c_void_p], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = arguments, result

        class Limits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", w.DWORD),
                ("min_working", ctypes.c_size_t), ("max_working", ctypes.c_size_t), ("active_limit", w.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Limits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def resume(self, pid):
        # Popen closes the initial thread handle. Reopen only the thread owned
        # by this still-suspended process, whose process handle remains live.
        c = self.ctypes
        from ctypes import wintypes as w

        class ThreadEntry(c.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("thread", w.DWORD),
                ("owner", w.DWORD), ("base_priority", w.LONG), ("delta_priority", w.LONG), ("flags", w.DWORD)]

        snapshot = self.kernel.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = c.sizeof(entry)
            found = self.kernel.Thread32First(snapshot, c.byref(entry))
            while found:
                if entry.owner == pid:
                    thread = self.kernel.OpenThread(0x2, False, entry.thread)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise c.WinError(c.get_last_error())
                    try:
                        if self.kernel.ResumeThread(thread) != 1:
                            raise RuntimeError("Owned media command was not suspended exactly once")
                    finally:
                        self.kernel.CloseHandle(thread)
                    return
                found = self.kernel.Thread32Next(snapshot, c.byref(entry))
            raise RuntimeError("Owned media command has no suspended initial thread")
        finally:
            self.kernel.CloseHandle(snapshot)

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
            if time.monotonic() >= deadline:
                raise TimeoutError("Owned media descendants did not exit")
            time.sleep(.01)

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            self.kernel.CloseHandle(handle)


@contextmanager
def owned_media_process(command, **kwargs):
    """Contain before execution; reap the tree without replacing a task failure."""
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x4 | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    job = None
    failure = None
    try:
        if os.name == "nt":
            job = WindowsJob(process)
            job.resume(process.pid)
        yield process
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            if job:
                job.terminate()
            elif os.name == "nt":
                # Failed containment leaves a suspended child that cannot spawn.
                if process.poll() is None:
                    process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.communicate(timeout=5)
        except BaseException as cleanup:
            if failure is None:
                raise
            failure.add_note(f"Owned media cleanup failed: {type(cleanup).__name__}")
        finally:
            if job:
                job.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
