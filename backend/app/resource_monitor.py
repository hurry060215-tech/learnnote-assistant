"""Small, dependency-free process and disk resource monitor.

The monitor is deliberately local and best-effort: it records only process
resource counters and free space for a caller-provided local directory.  It
never inspects task contents, URLs, environment variables, or credentials.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

try:  # ``resource`` is not available on stock Windows Python.
    import resource as _resource
except ImportError:  # pragma: no cover - exercised on Windows runners
    _resource = None


def _process_rss_bytes() -> int | None:
    """Return current process RSS when the host exposes it."""

    if os.name == "nt":
        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        api = ctypes.windll.psapi.GetProcessMemoryInfo
        api.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Counters), ctypes.c_ulong]
        api.restype = ctypes.c_int
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.argtypes = []
        get_current_process.restype = ctypes.c_void_p
        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        try:
            ok = api(
                get_current_process(),
                ctypes.byref(counters),
                counters.cb,
            )
        except (AttributeError, OSError):
            return None
        return int(counters.WorkingSetSize) if ok else None

    if _resource is None:
        return None
    try:
        value = int(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None
    # Linux reports KiB, macOS reports bytes.
    return value * 1024 if sys.platform != "darwin" else value


def _disk_free_bytes(path: Path) -> int | None:
    try:
        target = path if path.exists() else path.parent
        return int(shutil.disk_usage(target).free)
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class ResourceSample:
    elapsed_seconds: float
    process_cpu_percent: float | None
    rss_bytes: int | None
    disk_free_bytes: int | None


@dataclass(frozen=True)
class ResourceSummary:
    sample_count: int
    monitoring_supported: bool
    process_cpu_percent_mean: float | None
    process_cpu_percent_peak: float | None
    rss_peak_bytes: int | None
    disk_free_before_bytes: int | None
    disk_free_min_bytes: int | None
    disk_free_after_bytes: int | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class ResourceMonitor:
    """Collect process CPU/RSS and local disk-free samples in a thread."""

    def __init__(self, path: Path, interval_seconds: float = 1.0):
        self.path = Path(path)
        self.interval_seconds = max(0.05, float(interval_seconds))
        self._started_at = 0.0
        self._started_cpu = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[ResourceSample] = []

    @property
    def samples(self) -> tuple[ResourceSample, ...]:
        return tuple(self._samples)

    def _sample(self) -> ResourceSample:
        now = time.monotonic()
        elapsed = max(0.0, now - self._started_at)
        cpu = max(0.0, time.process_time() - self._started_cpu)
        cpu_percent = round(cpu / elapsed * 100.0, 3) if elapsed > 0 else None
        sample = ResourceSample(
            elapsed_seconds=round(elapsed, 3),
            process_cpu_percent=cpu_percent,
            rss_bytes=_process_rss_bytes(),
            disk_free_bytes=_disk_free_bytes(self.path),
        )
        self._samples.append(sample)
        return sample

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def start(self) -> "ResourceMonitor":
        if self._thread is not None:
            return self
        self.path.mkdir(parents=True, exist_ok=True)
        self._started_at = time.monotonic()
        self._started_cpu = time.process_time()
        self._sample()
        self._thread = threading.Thread(target=self._run, name="learnnote-resource-monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> ResourceSummary:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2.0))
            self._thread = None
        if not self._samples:
            self.start()
        self._sample()
        cpu_values = [s.process_cpu_percent for s in self._samples if s.process_cpu_percent is not None]
        rss_values = [s.rss_bytes for s in self._samples if s.rss_bytes is not None]
        disk_values = [s.disk_free_bytes for s in self._samples if s.disk_free_bytes is not None]
        return ResourceSummary(
            sample_count=len(self._samples),
            monitoring_supported=bool(cpu_values or rss_values or disk_values),
            process_cpu_percent_mean=round(sum(cpu_values) / len(cpu_values), 3) if cpu_values else None,
            process_cpu_percent_peak=round(max(cpu_values), 3) if cpu_values else None,
            rss_peak_bytes=max(rss_values) if rss_values else None,
            disk_free_before_bytes=disk_values[0] if disk_values else None,
            disk_free_min_bytes=min(disk_values) if disk_values else None,
            disk_free_after_bytes=disk_values[-1] if disk_values else None,
        )
