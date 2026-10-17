"""Opt-in synthetic benchmark observer; never imported by the application.

RSS is a sequential same-pass sum (shared pages count in each process). CPU is
only observed own-user/system increments; unobserved initial/final tails and
processes that live entirely between samples are unknowable, not zero.
"""
from __future__ import annotations

from collections import deque
import copy
import math
import os
import platform
import threading
import time


INTERVAL_SECONDS = 0.05
MAX_IDENTITIES = 128
MAX_SAMPLES = 256


class OwnedProcessTreeSampler:
    """Observe this dedicated fixture process and validated descendant identities."""

    def __init__(self):
        self._api = None
        self._root = None
        self._processes = {}
        self._samples = deque(maxlen=MAX_SAMPLES)
        self._errors = {name: 0 for name in (
            "dependency_unavailable", "access_denied", "unsupported", "invalid_counter",
            "identity_mismatch", "identity_capacity", "observer_error")}
        self._gaps = {name: 0 for name in (
            "exits_observed", "disappeared_during_read", "ownership_races", "late_samples")}
        self._stop = threading.Event()
        self._thread = None
        self._result = None
        self._started = self._last_start = 0.0
        self._sample_count = self._samples_dropped = 0
        self._max_gap = self._max_span = 0.0
        self._rss_peak = None
        self._peak_sample = None
        self._observer_cpu = 0.0

    def _identity(self, process):
        created = float(process.create_time())
        pid = int(process.pid)
        if pid <= 0 or not math.isfinite(created) or created <= 0:
            raise ValueError("invalid identity")
        return pid, created

    def _current(self, key):
        process = self._api.Process(key[0])
        if self._identity(process) != key:
            self._errors["identity_mismatch"] += 1
            raise self._api.NoSuchProcess(key[0])
        return process

    def _error(self, exc):
        if isinstance(exc, self._api.AccessDenied):
            key = "access_denied"
        elif isinstance(exc, (NotImplementedError, AttributeError)):
            key = "unsupported"
        elif isinstance(exc, (ValueError, TypeError, OverflowError)):
            key = "invalid_counter"
        else:
            key = "observer_error"
        self._errors[key] += 1

    def _admit(self, key):
        if key in self._processes:
            return
        if len(self._processes) >= MAX_IDENTITIES:
            # Counts rejected observations, not unique unknown processes.
            self._errors["identity_capacity"] += 1
            return
        self._processes[key] = {"pid": key[0], "create_time_unix": key[1],
            "first_observed_s": None, "last_observed_s": None, "baseline_cpu_s": None,
            "last_cpu_s": None, "exited_observed": False, "read_count": 0}

    def _retire(self, key):
        row = self._processes[key]
        if not row["exited_observed"]:
            row["exited_observed"] = True
            self._gaps["exits_observed"] += 1

    def _discover(self):
        # Already observed descendants remain owned after reparenting. New
        # identities require a presently validated direct parent-child edge.
        queue = [key for key, row in self._processes.items() if not row["exited_observed"]]
        seen = set(queue)
        for parent in queue:
            try:
                children = self._current(parent).children(recursive=False)
                self._current(parent)
            except self._api.NoSuchProcess:
                self._retire(parent)
                continue
            except Exception as exc:
                self._error(exc)
                continue
            for child in children:
                try:
                    key = self._identity(child)
                    if key in seen:
                        continue
                    current = self._current(key)
                    if current.ppid() != parent[0] or key[1] < parent[1]:
                        self._gaps["ownership_races"] += 1
                        continue
                    self._current(parent)
                    self._current(key)
                    self._admit(key)
                    if key in self._processes:
                        seen.add(key)
                        queue.append(key)
                except self._api.NoSuchProcess:
                    self._gaps["ownership_races"] += 1
                except Exception as exc:
                    self._error(exc)

    def _sample(self):
        cpu_started = time.thread_time()
        start = time.monotonic()
        gap = start - self._last_start if self._sample_count else 0.0
        self._max_gap = max(self._max_gap, gap)
        if gap > INTERVAL_SECONDS * 2:
            self._gaps["late_samples"] += 1
        self._last_start = start
        self._discover()
        readings = []
        missing = 0
        for key, row in self._processes.items():
            if row["exited_observed"]:
                continue
            try:
                process = self._current(key)
                with process.oneshot():
                    rss = int(process.memory_info().rss)
                    cpu = process.cpu_times()
                    own_cpu = float(cpu.user) + float(cpu.system)
                self._current(key)  # Never merge a reused PID's counters.
                if rss < 0 or not math.isfinite(own_cpu) or own_cpu < 0:
                    raise ValueError("invalid counter")
                if row["last_cpu_s"] is not None and own_cpu < row["last_cpu_s"]:
                    raise ValueError("counter moved backwards")
                observed = time.monotonic() - self._started
                if row["baseline_cpu_s"] is None:
                    row["baseline_cpu_s"] = own_cpu
                    row["first_observed_s"] = observed
                row.update(last_cpu_s=own_cpu, last_observed_s=observed,
                           read_count=row["read_count"] + 1)
                readings.append({"pid": key[0], "create_time_unix": key[1], "rss_bytes": rss})
            except self._api.NoSuchProcess:
                missing += 1
                self._gaps["disappeared_during_read"] += 1
                self._retire(key)
            except Exception as exc:
                missing += 1
                self._error(exc)
        end = time.monotonic()
        total = sum(row["rss_bytes"] for row in readings) if readings else None
        sample = {"start_s": start - self._started, "end_s": end - self._started,
            "collection_span_s": end - start, "gap_from_previous_start_s": gap,
            "rss_observed_sum_bytes": total, "processes_read": len(readings),
            "missing_readings": missing}
        self._max_span = max(self._max_span, end - start)
        if total is not None and (self._rss_peak is None or total > self._rss_peak):
            self._rss_peak = total
            self._peak_sample = dict(sample, processes=readings)
        if len(self._samples) == MAX_SAMPLES:
            self._samples_dropped += 1
        self._samples.append(sample)
        self._sample_count += 1
        self._observer_cpu += time.thread_time() - cpu_started

    def _run(self):
        try:
            while not self._stop.wait(INTERVAL_SECONDS):
                self._sample()
        except Exception as exc:
            self._error(exc)

    def start(self):
        if self._started:
            return self
        self._started = time.monotonic()
        try:
            import psutil
            self._api = psutil
        except (ImportError, OSError):
            self._errors["dependency_unavailable"] += 1
            return self
        try:
            self._root = self._identity(self._api.Process(os.getpid()))
            self._admit(self._root)
            self._sample()
            self._thread = threading.Thread(target=self._run, name="fixture-process-tree", daemon=True)
            self._thread.start()
        except Exception as exc:
            self._error(exc)
        return self

    def stop(self):
        if self._result is not None:
            return copy.deepcopy(self._result)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                # Do not copy data still being changed by a stuck observer.
                self._result = {"status": "unavailable", "reason": "observer_did_not_stop",
                    "budget_status": "not_established", "observer_still_running": True,
                    "sample_count": None, "rss_observed_sum_peak_bytes": None,
                    "cpu_observed_seconds": None}
                return copy.deepcopy(self._result)
        if self._api is not None and self._root is not None:
            try:
                self._sample()
            except Exception as exc:
                self._error(exc)
        rows = list(self._processes.values())
        observed = [row for row in rows if row["last_cpu_s"] is not None]
        cpu = sum(row["last_cpu_s"] - row["baseline_cpu_s"] for row in observed) if observed else None
        root_ok = (self._root in self._processes
            and self._processes[self._root]["read_count"] > 0
            and not self._processes[self._root]["exited_observed"])
        status = "unavailable" if not root_ok else "incomplete" if any(self._errors.values()) else "sampled"
        self._result = {"status": status, "budget_status": "not_established",
            "scope": "dedicated fixture process and observed descendants; no content or command-line capture",
            "rss_semantics": "sequential same-pass observed RSS sum; shared pages double count; unsampled peaks unknown",
            "cpu_semantics": "sum of observed own user+system increments; excludes children counters; initial/final tails missing",
            "coverage": "processes born and exited between discovery passes and unobserved reparented descendants are unknown",
            "platform": platform.system(), "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(), "psutil_version": getattr(self._api, "__version__", None),
            "root": {"pid": self._root[0], "create_time_unix": self._root[1]} if self._root else None,
            "interval_seconds": INTERVAL_SECONDS, "identity_limit": MAX_IDENTITIES, "sample_limit": MAX_SAMPLES,
            "elapsed_seconds": time.monotonic() - self._started,
            "sample_count": self._sample_count, "sample_details_dropped": self._samples_dropped,
            "maximum_gap_seconds": self._max_gap, "maximum_collection_span_seconds": self._max_span,
            "rss_observed_sum_peak_bytes": self._rss_peak, "rss_peak_sample": self._peak_sample,
            "cpu_observed_seconds": cpu, "observer_sampling_cpu_seconds": self._observer_cpu,
            "errors": self._errors, "sampling_gaps": self._gaps, "processes": rows,
            "recent_samples": list(self._samples)}
        return copy.deepcopy(self._result)
