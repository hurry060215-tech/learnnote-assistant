"""Opt-in, bounded contention evidence for the synthetic reference fixture only.

No production imports this module. Wrappers time existing calls; they do not
change lock ordering, acquire timeouts, persisted data, task selection or SLOs.
I/O-bearing function spans include their decoding/validation work, not just OS
I/O. Thread CPU belongs to synchronous operations; HTTP envelope CPU is omitted.
No source text, configuration values, filenames/paths, or stack dumps are saved.
owner_at_entry is only a point-in-time snapshot, not complete wait attribution.
Outer hold time ends immediately before the real release call; that call and
post-release observer recording are excluded. Slow events are bounded samples,
and nested spans are inclusive, so their durations must not be added together.
The product task lock has no Condition/private release-and-restore consumer.
"""
from collections import deque
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
import functools
import heapq
import itertools
import os
import platform
import re
import threading
import time
from unittest.mock import patch

SCHEMA_VERSION = 1
SLOW_SECONDS = .020
MAX_METRICS = 32
_current = ContextVar("reference_contention_operation", default=None)
_section = ContextVar("reference_contention_section", default="unlabelled")


def _task_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{12}", value) else ""


def _clock():
    return time.perf_counter(), time.thread_time()


class Collector:
    def __init__(self, max_operations=256, max_events=256, max_slow_events=64, max_active=128):
        limits = (max_operations, max_events, max_slow_events, max_active)
        if any(type(value) is not int or not 1 <= value <= 512 for value in limits):
            raise ValueError("diagnostic bounds must be integers between 1 and 512")
        self.limits = dict(operations=max_operations, recent_events=max_events,
                          slow_events=max_slow_events, active=max_active, metrics=MAX_METRICS)
        # Reserve the same total budget by kind: long list/projection boundaries
        # must not displace every lock owner/waiter. Largest remainders keep even
        # tiny test budgets deterministic without exceeding the configured cap.
        weights = dict(lock_wait=2, lock_hold=2, lease_wait=1, boundary=3)
        quotas = {kind: max_slow_events * weight // 8 for kind, weight in weights.items()}
        order = sorted(weights, key=lambda kind: -(max_slow_events * weights[kind] % 8))
        for kind in order[:max_slow_events - sum(quotas.values())]:
            quotas[kind] += 1
        self.limits["slow_events_by_kind"] = quotas
        self.mutex = threading.RLock()  # Collector metadata only; never obtains a product lock.
        self.operations = deque(maxlen=max_operations)
        self.events = deque(maxlen=max_events)
        self.slow = {kind: [] for kind in weights}
        self.active = {}
        self.dropped = dict(operations=0, recent_events=0, slow_events=0, active=0, metrics=0)
        self.dropped["slow_events_by_kind"] = dict.fromkeys(weights, 0)
        self.serial = itertools.count(1)
        self.epoch_wall, self.epoch_monotonic = time.time(), time.perf_counter()
        self.lock = None
        self.totals = {}

    def identity(self):
        current = _current.get()
        if current is not None:
            return {key: current[key] for key in ("id", "name", "task_id", "phase")}
        # Task workers have stable names, but no arbitrary caller data is logged.
        name = "worker" if threading.current_thread().name.startswith("learnnote-task-") else "unscoped"
        return dict(id=0, name=name, task_id="", phase="")

    @contextmanager
    def operation(self, name, task_id="", phase="", *, cpu=True):
        # Only static wrapper labels are accepted. This is a fixture API, not a logger.
        if not re.fullmatch(r"[a-z_]{1,40}", name):
            raise ValueError("invalid diagnostic operation")
        phase = phase if isinstance(phase, str) and re.fullmatch(r"[a-z_]{1,40}", phase) else ""
        start = _clock()
        parent = _current.get()
        row = dict(id=next(self.serial), name=name, task_id=_task_id(task_id), phase=phase,
                   parent_id=parent["id"] if parent else None, thread_id=threading.get_ident(),
                   start_s=start[0]-self.epoch_monotonic, metrics={})
        with self.mutex:
            admitted = len(self.active) < self.limits["active"]
            if admitted:
                self.active[row["id"]] = row
            else:
                self.dropped["active"] += 1
        token = _current.set(row if admitted else None)
        failed = False
        try:
            yield row
        except BaseException:
            failed = True
            raise
        finally:
            end = _clock()
            _current.reset(token)
            with self.mutex:
                # snapshot() copies active rows under this same mutex. Final keys
                # must not resize a row while that bounded copy is in progress.
                row.update(end_s=end[0]-self.epoch_monotonic, wall_s=end[0]-start[0],
                           thread_cpu_s=end[1]-start[1] if cpu else None, raised=failed)
                self.active.pop(row["id"], None)
                if admitted:
                    if len(self.operations) == self.operations.maxlen:
                        self.dropped["operations"] += 1
                    self.operations.append(row)

    def metric(self, name, wall, cpu, *, count=1):
        row = _current.get()
        with self.mutex:
            collections = [self.totals]
            if row is not None:
                collections.append(row["metrics"])
            for target in collections:
                value = target.get(name)
                if value is None:
                    if len(target) >= MAX_METRICS:
                        self.dropped["metrics"] += 1
                        continue
                    value = target[name] = dict(count=0, wall_s=0., thread_cpu_s=0., max_wall_s=0.)
                value["count"] += count
                value["wall_s"] += wall
                value["thread_cpu_s"] += cpu
                value["max_wall_s"] = max(value["max_wall_s"], wall)

    def event(self, kind, name, start, end, **values):
        if kind not in self.slow:
            raise ValueError("invalid diagnostic event kind")
        # Retain only slow boundaries; every call still contributes to the aggregates.
        wall = end[0] - start[0]
        if wall < SLOW_SECONDS:
            return
        row = dict(kind=kind, name=name, start_s=start[0]-self.epoch_monotonic,
                   end_s=end[0]-self.epoch_monotonic, wall_s=wall,
                   thread_cpu_s=end[1]-start[1], operation=self.identity(),
                   thread_id=threading.get_ident(), **values)
        with self.mutex:
            if len(self.events) == self.events.maxlen:
                self.dropped["recent_events"] += 1
            self.events.append(row)
            entry = (wall, next(self.serial), row)
            heap = self.slow[kind]
            limit = self.limits["slow_events_by_kind"][kind]
            if len(heap) < limit:
                heapq.heappush(heap, entry)
            else:
                self.dropped["slow_events"] += 1
                self.dropped["slow_events_by_kind"][kind] += 1
                if limit and wall > heap[0][0]:
                    heapq.heapreplace(heap, entry)

    @contextmanager
    def span(self, name):
        if not re.fullmatch(r"[a-z_]{1,48}", name):
            raise ValueError("invalid diagnostic span")
        token = _section.set(name)
        start = _clock()
        try:
            yield
        finally:
            end = _clock()
            self.metric(name, end[0]-start[0], end[1]-start[1])
            self.event("boundary", name, start, end)
            _section.reset(token)

    def snapshot(self):
        # Deep-copy only the bounded report, outside measured product critical sections.
        import copy
        with self.mutex:
            result = dict(schema_version=SCHEMA_VERSION,
                clock=dict(unix_seconds=self.epoch_wall, monotonic_seconds=self.epoch_monotonic,
                           snapshot_monotonic_seconds=time.perf_counter()),
                host=dict(platform=platform.system(), python=platform.python_version(),
                          process_id=os.getpid(), logical_cpu_count=os.cpu_count()),
                scope="synthetic fixture; I/O-bearing boundaries include decoding and validation; nested spans are inclusive",
                bounds=self.limits, dropped=self.dropped, totals=self.totals,
                operations=list(self.operations), recent_events=list(self.events),
                slow_events=[entry[2] for entry in sorted(
                    (entry for heap in self.slow.values() for entry in heap), reverse=True)],
                active=list(self.active.values()), lock_owner=self.lock.owner if self.lock else None)
            return copy.deepcopy(result)


class MeasuredTaskLock:
    """The same underlying RLock, with bounded ownership and wait accounting."""
    def __init__(self, real, collector):
        self.real, self.collector = real, collector
        self.local = threading.local()
        self.owner = None
        self.serial = itertools.count(1)
        collector.lock = self

    def acquire(self, *args, **kwargs):
        with self.collector.mutex:
            owner = dict(self.owner) if self.owner else None
        start = _clock()
        acquired = self.real.acquire(*args, **kwargs)
        end = _clock()
        if acquired:
            depth = getattr(self.local, "depth", 0)
            if depth == 0:
                # The direct caller function is a static critical-section label,
                # never a stack dump or frame/argument capture.
                import sys
                frame = sys._getframe(1)
                if frame.f_code.co_name == "__enter__":
                    frame = frame.f_back
                label = frame.f_code.co_name
                del frame
                self.local.start = end
                self.local.owner = dict(hold_id=next(self.serial), thread_id=threading.get_ident(),
                    operation=self.collector.identity(), section=_section.get(),
                    critical=label, start_s=end[0]-self.collector.epoch_monotonic)
                with self.collector.mutex:
                    self.owner = self.local.owner
            self.local.depth = depth + 1
        self.collector.metric("task_lock_wait", end[0]-start[0], end[1]-start[1])
        self.collector.event("lock_wait", "task_lock", start, end, owner_at_entry=owner, acquired=bool(acquired))
        return acquired

    def release(self):
        depth = getattr(self.local, "depth", 0)
        if depth == 0:
            return self.real.release()  # Preserve the original wrong-thread/error behavior.
        owner = self.local.owner if depth == 1 else None
        if owner:
            with self.collector.mutex:
                self.owner = None
        end = _clock()
        result = self.real.release()
        self.local.depth = depth - 1
        if owner:
            start = self.local.start
            self.collector.metric("task_lock_hold", end[0]-start[0], end[1]-start[1])
            self.collector.event("lock_hold", "task_lock", start, end, owner=owner)
        return result

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()

    def __getattr__(self, name):
        return getattr(self.real, name)


class RequestEnvelope:
    """Pure ASGI timing; leaves bodies, streaming and cancellation unchanged."""
    def __init__(self, app, collector):
        self.app, self.collector = app, collector

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        match = re.fullmatch(r"/api/tasks(?:/([a-f0-9]{12})(?:/(start|cancel))?)?", path)
        if scope["type"] != "http" or not match:
            return await self.app(scope, receive, send)
        with self.collector.operation("http_request", match[1] or "", cpu=False):
            await self.app(scope, receive, send)


def _install(app, stack):
    """Call only after configure_fixture has verified its synthetic data marker."""
    from app import (storage, main, processor, processor_state, subtitle_notes,
                     pipeline_progress, progressive_sections, screen_subtitle_tasks,
                     duration_estimates, whole_duration_estimates)
    collector = Collector()
    real_lock = storage._lock
    measured = MeasuredTaskLock(real_lock, collector)
    for module, name in ((storage, "_lock"), (pipeline_progress, "_task_data_lock"),
                         (progressive_sections, "_task_data_lock"), (screen_subtitle_tasks, "_task_data_lock")):
        if getattr(module, name) is not real_lock:
            raise AssertionError("fixture task lock aliases disagree")
        stack.enter_context(patch.object(module, name, measured))

    def wrapped(function, label, operation=False):
        @functools.wraps(function)
        def call(*args, **kwargs):
            if operation:
                with collector.operation(label, args[0] if args else kwargs.get("task_id", ""), kwargs.get("phase", "")):
                    with collector.span(label):
                        return function(*args, **kwargs)
            with collector.span(label):
                return function(*args, **kwargs)
        return call

    def aliases(function, label, targets, operation=False):
        replacement = wrapped(function, label, operation)
        for module, name in targets:
            if getattr(module, name) is not function:
                raise AssertionError("fixture function alias disagrees: " + name)
            stack.enter_context(patch.object(module, name, replacement))
        return replacement

    aliases(storage.update_task, "update_task", [(module, "update_task") for module in
        (storage, main, processor, processor_state, subtitle_notes, progressive_sections, screen_subtitle_tasks)], True)
    # These defining-module boundaries cover actual I/O and decoder/index work.
    # Do not patch Path, open, json, sqlite, threading, or any shared runtime method.
    for module, name, label in (
        (storage, "get_task", "manifest_read_validate"),
        (storage, "read_json", "task_json_read_decode"),
        (storage, "atomic_write_text", "atomic_file_write"),
        (storage, "index_task", "library_index_sqlite"),
        (storage, "reconcile_stale_tasks", "list_reconcile"),
        (duration_estimates, "_read", "duration_file_read_decode"),
        (duration_estimates, "_history", "remaining_history"),
        (whole_duration_estimates, "_history", "whole_history"),
    ):
        original = getattr(module, name)
        stack.enter_context(patch.object(module, name, wrapped(original, label)))
    # Known imported read bindings in the reference path must point to the same wrappers.
    for module in (main, processor, processor_state, subtitle_notes, progressive_sections, screen_subtitle_tasks):
        stack.enter_context(patch.object(module, "get_task", storage.get_task))
    for module in (main, pipeline_progress, progressive_sections):
        stack.enter_context(patch.object(module, "read_json", storage.read_json))
    stack.enter_context(patch.object(whole_duration_estimates, "_read_evidence", duration_estimates._read))
    original_read = processor.read_transcript
    replacement = wrapped(original_read, "transcript_read_decode")
    for module in (processor, main):
        stack.enter_context(patch.object(module, "read_transcript", replacement))
    for name, label in (("list_tasks", "list_tasks"), ("task_payload", "task_projection")):
        stack.enter_context(patch.object(main, name, wrapped(getattr(main, name), label)))
    original_lease = storage.worker_lease

    @contextmanager
    def lease(*args, **kwargs):
        start = _clock()
        with original_lease(*args, **kwargs) as result:
            end = _clock()
            collector.metric("state_lease_enter", end[0]-start[0], end[1]-start[1])
            collector.event("lease_wait", "state_lease", start, end,
                            owner=measured.owner)
            yield result
    stack.enter_context(patch.object(storage, "worker_lease", lease))

    for route in app.routes:
        if getattr(route, "path", None) not in {"/api/tasks", "/api/tasks/{task_id}"} or "GET" not in getattr(route, "methods", ()):
            continue
        label = "list_handler" if route.path == "/api/tasks" else "selected_handler"
        stack.enter_context(patch.object(route.dependant, "call", wrapped(route.dependant.call, label, True)))
    previous_middleware, previous_stack = list(app.user_middleware), app.middleware_stack
    app.add_middleware(RequestEnvelope, collector=collector)
    def restore_middleware():
        app.user_middleware[:] = previous_middleware
        app.middleware_stack = previous_stack
    stack.callback(restore_middleware)
    return collector


def install(app, stack):
    """Restore a partially installed observer immediately if setup raises."""
    local = ExitStack()
    try:
        collector = _install(app, local)
    except BaseException:
        local.close()
        raise
    stack.enter_context(local)
    return collector
