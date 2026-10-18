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
import inspect
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
_index_active = ContextVar("reference_contention_index_active", default=False)
_catalog_origin = ContextVar("reference_contention_catalog_origin", default=None)


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
        self.catalog_lock = None
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
                active=list(self.active.values()), lock_owner=self.lock.owner if self.lock else None,
                catalog_lock_owner=self.catalog_lock.owner if self.catalog_lock else None)
            return copy.deepcopy(result)


class MeasuredTaskLock:
    """The same underlying RLock, with bounded ownership and wait accounting."""
    def __init__(self, real, collector, name="task_lock"):
        if name not in {"task_lock", "catalog_lock"}:
            raise ValueError("invalid diagnostic lock name")
        self.real, self.collector = real, collector
        self.name = name
        self.local = threading.local()
        self.owner = None
        self.serial = itertools.count(1)
        if name == "task_lock":
            collector.lock = self
        else:
            collector.catalog_lock = self

    def _task_link(self):
        # Caller holds collector.mutex; this never obtains either product lock.
        owner = self.collector.lock.owner if self.collector.lock else None
        if self.name == "catalog_lock" and owner and owner["thread_id"] == threading.get_ident():
            return dict(lock_name="task_lock", hold_id=owner["hold_id"], thread_id=owner["thread_id"])
        return None

    def acquire(self, *args, **kwargs):
        with self.collector.mutex:
            owner = dict(self.owner) if self.owner else None
            task_link = self._task_link()
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
                    critical=label, start_s=end[0]-self.collector.epoch_monotonic,
                    lock_name=self.name)
                with self.collector.mutex:
                    if self.name == "catalog_lock":
                        self.local.owner.update(catalog_origin=_catalog_origin.get(), task_owner=self._task_link())
                    self.owner = self.local.owner
            self.local.depth = depth + 1
        self.collector.metric(self.name + "_wait", end[0]-start[0], end[1]-start[1])
        values = dict(owner_at_entry=owner, acquired=bool(acquired))
        if self.name == "catalog_lock":
            values["task_owner_at_entry"] = task_link
        self.collector.event("lock_wait", self.name, start, end, **values)
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
            self.collector.metric(self.name + "_hold", end[0]-start[0], end[1]-start[1])
            self.collector.event("lock_hold", self.name, start, end, owner=owner)
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
        method = scope.get("method", "")
        task_id = None
        if scope["type"] == "http":
            match = re.fullmatch(r"/api/tasks(?:/([a-f0-9]{12})(?:/(start|cancel))?)?", path)
            if match and method == ("POST" if match[2] else "GET"):
                task_id = match[1] or ""
            elif method == "GET":
                match = re.fullmatch(r"/api/tasks/editions/task/([a-f0-9]{12})(?:/personal-review)?", path)
                if match:
                    task_id = match[1]
            if task_id is None:
                match = re.fullmatch(r"/_fixture/tasks/([a-f0-9]{12})(/visible)?", path)
                if match and method == ("POST" if match[2] else "GET"):
                    task_id = match[1]
        if task_id is None:
            return await self.app(scope, receive, send)
        with self.collector.operation("http_request", task_id, cpu=False):
            await self.app(scope, receive, send)


def _install(app, stack):
    """Call only after configure_fixture has verified its synthetic data marker."""
    from app import (storage, main, processor, processor_state, subtitle_notes,
                     pipeline_progress, progressive_sections, screen_subtitle_tasks,
                     duration_estimates, whole_duration_estimates, library, knowledge, catalog_guard)
    collector = Collector()
    real_lock = storage._lock
    measured = MeasuredTaskLock(real_lock, collector)
    for module, name in ((storage, "_lock"), (pipeline_progress, "_task_data_lock"),
                         (progressive_sections, "_task_data_lock"), (screen_subtitle_tasks, "_task_data_lock")):
        if getattr(module, name) is not real_lock:
            raise AssertionError("fixture task lock aliases disagree")
        stack.enter_context(patch.object(module, name, measured))
    # All direct guards and guarded connections use this single module lookup.
    # The original connection retains its guard through close; no proxy is used.
    stack.enter_context(patch.object(catalog_guard, "_mutex",
        MeasuredTaskLock(catalog_guard._mutex, collector, "catalog_lock")))

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

    def require_sync(function):
        if any(not inspect.isfunction(target) or any(check(target) for check in
               (inspect.iscoroutinefunction, inspect.isgeneratorfunction, inspect.isasyncgenfunction))
               for target in (function, inspect.unwrap(function))):
            raise TypeError("fixture diagnostic target must remain an ordinary synchronous function")

    # These are function boundaries, not SQL statements or raw file-I/O timers.
    # The connection object is returned untouched; its later use/close stays in
    # the inclusive outer index span. Other callers of these aliases are untimed.
    def index_part(function, span):
        @functools.wraps(function)
        def call(*args, **kwargs):
            if not _index_active.get():
                return function(*args, **kwargs)
            with collector.span(span):
                return function(*args, **kwargs)
        return call
    for name, label in (
        ("_read_text", "index_artifact_text"),
        ("_connect", "index_connect_schema"),
        ("record_to_evidence", "index_note_evidence"),
        ("transcript_evidence", "index_transcript_evidence"),
        ("replace_task_evidence", "index_replace_evidence"),
    ):
        original = getattr(library, name)
        require_sync(original)
        stack.enter_context(patch.object(library, name, index_part(original, label)))

    # One direct caller frame only, never a stack walk, path, argument or retained
    # frame. Fixed known code identities label owners outside timed HTTP routes.
    # Unknown callers/direct outer guards remain explicitly unavailable (None).
    for module, names in (
        (library, ("index_task", "remove_task", "_remove_task_index", "rebuild_index",
                   "search_library", "library_status", "duplicate_groups", "backup_library",
                   "list_materials", "get_material", "_delete_material_locked",
                   "import_document_material", "register_task_material",
                   "_rewrite_document_material", "apply_material_ocr")),
        (knowledge, ("add_evidence", "replace_task_evidence", "remove_task_evidence",
                     "clear_task_evidence", "remove_evidence", "search_evidence",
                     "evidence_for_task", "evidence_by_ids", "evidence_ids_for_task", "redecode_evidence")),
    ):
        origins = {inspect.unwrap(getattr(module, name)).__code__: module.__name__.split(".")[-1] + "." + name
                   for name in names}
        def connection_label(function, origins):
            @functools.wraps(function)
            def call(*args, **kwargs):
                import sys
                frame = sys._getframe(1)
                origin = origins.get(frame.f_code)
                del frame
                token = _catalog_origin.set(origin)
                try:
                    return function(*args, **kwargs)
                finally:
                    _catalog_origin.reset(token)
            return call
        original = module._connect
        require_sync(original)
        stack.enter_context(patch.object(module, "_connect", connection_label(original, origins)))

    original_index = storage.index_task
    require_sync(original_index)
    @functools.wraps(original_index)
    def index_call(*args, **kwargs):
        token = _index_active.set(True)
        try:
            with collector.span("library_index_sqlite"):
                return original_index(*args, **kwargs)
        finally:
            _index_active.reset(token)
    stack.enter_context(patch.object(storage, "index_task", index_call))

    aliases(storage.update_task, "update_task", [(module, "update_task") for module in
        (storage, main, processor, processor_state, subtitle_notes, progressive_sections, screen_subtitle_tasks)], True)
    # These defining-module boundaries cover actual I/O and decoder/index work.
    # Do not patch Path, open, json, sqlite, threading, or any shared runtime method.
    for module, name, label in (
        (storage, "get_task", "manifest_read_validate"),
        (storage, "read_json", "task_json_read_decode"),
        (storage, "atomic_write_text", "atomic_file_write"),
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

    route_targets = {
        ("GET", "/api/tasks/editions/{kind}/{source_id}"): ("edition_handler", "source_id", 1),
        ("GET", "/api/tasks/editions/{kind}/{source_id}/personal-review"): ("personal_review_handler", "source_id", 1),
        ("GET", "/_fixture/tasks/{task_id}"): ("fixture_state_handler", "task_id", 0),
        ("POST", "/_fixture/tasks/{task_id}/visible"): ("visible_handler", "task_id", 0),
    }
    def reader_handler(function, label, key, position):
        @functools.wraps(function)
        def call(*args, **kwargs):
            if key == "source_id" and (args[0] if args else kwargs.get("kind")) != "task":
                return function(*args, **kwargs)
            task_id = args[position] if len(args) > position else kwargs.get(key, "")
            with collector.operation(label, task_id):
                with collector.span(label):
                    return function(*args, **kwargs)
        return call
    found = set()
    reader_routes = list(app.routes)
    # FastAPI 0.143 (also pinned on Windows) dispatches included notes routes
    # through lazy effective dependants. Resolve only this known router, before
    # serving; restore calls first, then these exact cache references at teardown.
    for branch in app.routes:
        if getattr(branch, "original_router", None) is main.notes_router:
            for name in ("_effective_candidates", "_effective_candidates_version"):
                stack.enter_context(patch.object(branch, name, getattr(branch, name)))
            reader_routes.extend(branch.effective_candidates())
    for route in reader_routes:
        for method in getattr(route, "methods", ()):
            key = (method, getattr(route, "path", ""))
            if key in route_targets:
                require_sync(route.dependant.call)
                stack.enter_context(patch.object(route.dependant, "call",
                    reader_handler(route.dependant.call, *route_targets[key])))
                found.add(key)
    if found != set(route_targets):
        raise AssertionError("fixture diagnostic reader routes are incomplete")
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


def install_cancellation_spans(app, stack, collector):
    """Fixed lifecycle boundaries for the one-cancellation diagnostic only.

    Reuse the bounded operation ring, clocks and drop counters. No SQL/runtime
    interception: index_return ends after the original best-effort index call,
    not a separately measured SQLite commit. Original exceptions/returns survive.
    """
    from app import storage, main, processor, processor_state, task_queue
    local = ExitStack()
    def wrap(function, label, identity=0, phase=None, predicate=None):
        if any(check(target) for target in (function, inspect.unwrap(function)) for check in
               (inspect.iscoroutinefunction, inspect.isgeneratorfunction, inspect.isasyncgenfunction)):
            raise TypeError("fixture cancellation target must remain synchronous")
        @functools.wraps(function)
        def call(*args, **kwargs):
            if predicate is not None and not predicate(args, kwargs):
                return function(*args, **kwargs)
            target = args[identity] if len(args) > identity else kwargs.get("task_id", "")
            task_id = target.id if hasattr(target, "id") else target
            with collector.operation(label, task_id, phase or ""):
                return function(*args, **kwargs)
        return call
    def aliases(function, label, targets, **options):
        replacement = wrap(function, label, **options)
        for module, name in targets:
            if getattr(module, name) is not function:
                raise AssertionError("fixture cancellation alias mismatch")
            local.enter_context(patch.object(module, name, replacement))
    try:
        aliases(storage.request_task_cancel, "cancel_request",
                [(storage, "request_task_cancel"), (main, "request_task_cancel")])
        aliases(processor_state.check_cancel, "worker_check",
                [(processor_state, "check_cancel"), (processor, "_check_cancel")])
        aliases(storage.mark_task_cancelled, "cancel_acknowledge",
                [(storage, "mark_task_cancelled"), (processor_state, "mark_task_cancelled"),
                 (processor, "mark_task_cancelled")])
        for name, label in (("save_task", "manifest_save"), ("index_task", "index_return")):
            local.enter_context(patch.object(storage, name, wrap(getattr(storage, name), label)))
        local.enter_context(patch.object(task_queue.LocalTaskQueue, "set_state",
            wrap(task_queue.LocalTaskQueue.set_state, "callback_finish", identity=1,
                 predicate=lambda args, kwargs: kwargs.get("callback_finished") is True)))
        found = False
        for route in app.routes:
            if getattr(route, "path", None) == "/api/tasks/{task_id}/cancel" and "POST" in getattr(route, "methods", ()):
                local.enter_context(patch.object(route.dependant, "call",
                    wrap(route.dependant.call, "cancel_handler")))
                found = True
        if not found:
            raise AssertionError("fixture cancellation handler missing")
    except BaseException:
        local.close()
        raise
    stack.enter_context(local)
