"""Bounded lane slots per data directory, including separate local processes."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import threading

_held = threading.local()


def has_worker_lease(root: Path, lane: str) -> bool:
    return any(key[:2] == (str(root.resolve()), lane) for key in getattr(_held, "keys", set()))


@contextmanager
def worker_lease(root: Path, blocking: bool = True, *, lane: str = "heavy", slot: int = 0):
    if lane not in {"heavy", "light", "download"}:
        raise ValueError("Unknown worker lane")
    if not isinstance(slot, int) or not 0 <= slot < 4:
        raise ValueError("Unknown worker slot")
    suffix = ("" if lane == "heavy" else "-" + lane) + (f"-{slot}" if slot else "")
    key = (str(root.resolve()), lane, slot)
    held = getattr(_held, "keys", set())
    _held.keys = held
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        api.CreateMutexW.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.ReleaseMutex.argtypes = [wintypes.HANDLE]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        name = "Local\\LearnNoteWorker-" + hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()
        name += suffix
        handle = api.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = False
        try:
            result = api.WaitForSingleObject(handle, 0xFFFFFFFF if blocking else 0)
            acquired = result in (0, 0x80)
            if result not in (0, 0x80, 0x102):
                raise ctypes.WinError(ctypes.get_last_error())
            if acquired:
                held.add(key)
            yield acquired
        finally:
            if acquired:
                held.discard(key)
                api.ReleaseMutex(handle)
            api.CloseHandle(handle)
    else:
        import fcntl
        with (root / ("worker" + suffix + ".lock")).open("a") as handle:
            acquired = False
            try:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                    acquired = True
                except BlockingIOError:
                    pass
                if acquired:
                    held.add(key)
                yield acquired
            finally:
                if acquired:
                    held.discard(key)
                    fcntl.flock(handle, fcntl.LOCK_UN)
