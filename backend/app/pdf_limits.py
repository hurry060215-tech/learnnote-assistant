"""PDF worker limits, including macOS's large pre-existing VM mappings."""
from __future__ import annotations

from functools import lru_cache
import os
import subprocess
import sys
import time


@lru_cache(maxsize=1)
def _darwin_api():
    import ctypes

    class TaskInfo(ctypes.Structure):
        # Public proc_taskinfo ABI in Apple's bsd/sys/proc_info.h.
        _fields_ = [('virtual_size', ctypes.c_uint64), ('resident_size', ctypes.c_uint64),
                    ('times', ctypes.c_uint64 * 4), ('counters', ctypes.c_int32 * 12)]

    library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    function = library.proc_pidinfo
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    function.restype = ctypes.c_int
    return ctypes, TaskInfo, function


def darwin_memory(pid):
    ctypes, task_type, function = _darwin_api()
    info = task_type()
    size = ctypes.sizeof(info)
    if function(pid, 4, 0, ctypes.byref(info), size) != size:  # PROC_PIDTASKINFO
        raise OSError(ctypes.get_errno(), 'Cannot inspect PDF worker memory')
    return info.virtual_size, info.resident_size


def install_worker_limits(memory_bytes, *, cpu_seconds=25, output_bytes=32 * 1024 * 1024):
    if os.name == 'nt':
        return  # Supervisor assigns the suspended child to its bounded JobObject.
    import resource
    address_limit = memory_bytes
    if sys.platform == 'darwin':
        # XNU rejects RLIMIT_AS below map->size. Shared/cache/allocator mappings
        # can already exceed 1 GiB before Python loads a document. Keep a hard
        # cap on additional mappings and separately supervise actual resident use.
        virtual, resident = darwin_memory(os.getpid())
        if resident >= memory_bytes:
            raise MemoryError('PDF worker startup exceeds memory budget')
        address_limit = virtual + memory_bytes - resident
    resource.setrlimit(resource.RLIMIT_AS, (address_limit, address_limit))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))


def wait_for_pdf_worker(process, *, timeout, memory_bytes):
    if sys.platform != 'darwin':
        return process.wait(timeout=timeout)
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        try:
            _, resident = darwin_memory(process.pid)
        except OSError:
            if process.poll() is not None:
                break
            raise  # Never silently drop supervision.
        if resident > memory_bytes:
            raise MemoryError('PDF worker resident memory budget exceeded')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            process.wait(timeout=min(.02, remaining))
        except subprocess.TimeoutExpired:
            pass
    return process.returncode
