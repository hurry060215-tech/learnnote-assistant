"""One original-path update against 80 real synthetic retained caption tasks.

Diagnostic only: no browser timing, release SLO, row-67 attribution or provider
calls. Seed via the existing offline fixture and real queue/processor. Compare
observer-off/profiled/observer-off updates restored from identical owned files.
Order/cache noise remains; the observed delta is not a pure profiler-cost bound.
Native timings include scheduling/GIL reacquisition, not just disk or SQLite CPU.
executescript includes its implicit transaction work; only explicit commit calls
are separately measured. Never retain SQL, arguments, frames or exception text.
"""
import argparse
from contextlib import ExitStack, contextmanager
import functools
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DURATIONS = (5, 30, 60, 180)
REPETITIONS = 20


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeCalls:
    """Current-thread callback; fixed call sites and the existing bounded rings."""
    MAX_SITES, MAX_PENDING = 64, 8
    METHODS = frozenset({"execute", "executemany", "executescript", "fetchone", "fetchall",
                         "commit", "rollback", "close"})

    def __init__(self, collector, callers):
        self.collector, self.callers = collector, callers
        self.pending, self.sites = [], {}
        self.failed = False
        self.on_close = None
        self.active_connections, self.profiler_restored = 0, True
        self.close_failures = self.incomplete_lifetimes = 0
        self.dropped = dict(sites=0, pending=0, unmatched=0)

    def __call__(self, frame, event, arg):
        if self.failed or event not in {"c_call", "c_return", "c_exception"}:
            return
        caller = self.callers.get(frame.f_code)
        if caller is None:
            return
        method = "connect" if arg is sqlite3.connect else getattr(arg, "__name__", "")
        if arg is not sqlite3.connect and (method not in self.METHODS or
                not isinstance(getattr(arg, "__self__", None), (sqlite3.Connection, sqlite3.Cursor))):
            return
        try:
            if event == "c_call":
                if len(self.pending) == self.MAX_PENDING:
                    self.dropped["pending"] += 1
                    self.failed = True
                    return
                owner = self.collector.catalog_lock.owner if self.collector.catalog_lock else None
                task = self.collector.lock.owner if self.collector.lock else None
                self.pending.append((arg, id(frame), (time.perf_counter(), time.thread_time()),
                    (caller, frame.f_lineno, method), owner["hold_id"] if owner else None,
                    task["hold_id"] if task else None))
                return
            # CPython may construct a fresh bound builtin-method object for the
            # return event. Its equality identifies the same native function and
            # receiver; require receiver identity and the same caller frame too.
            if (not self.pending or self.pending[-1][0] != arg or
                    getattr(self.pending[-1][0], "__self__", None) is not getattr(arg, "__self__", None) or
                    self.pending[-1][1] != id(frame)):
                self.dropped["unmatched"] += 1
                self.failed = True
                return
            end = time.perf_counter(), time.thread_time()
            _, _, start, key, catalog_hold, task_hold = self.pending.pop()
            wall, cpu = end[0] - start[0], end[1] - start[1]
            row = self.sites.get(key)
            if row is None and len(self.sites) < self.MAX_SITES:
                row = self.sites[key] = dict(caller=key[0], line=key[1], method=key[2],
                    count=0, raised=0, wall_s=0., thread_cpu_s=0., max_wall_s=0.)
            if row is None:
                self.dropped["sites"] += 1
            else:
                row["count"] += 1
                row["raised"] += event == "c_exception"
                row["wall_s"] += wall
                row["thread_cpu_s"] += cpu
                row["max_wall_s"] = max(row["max_wall_s"], wall)
            self.collector.metric("catalog_native", wall, cpu)
            self.collector.event("boundary", "catalog_native", start, end,
                caller=key[0], line=key[1], method=key[2], raised=event == "c_exception",
                catalog_hold_id=catalog_hold, task_hold_id=task_hold)
            if caller == "catalog_guard.close" and method == "close":
                succeeded = event == "c_return"
                if not succeeded:
                    self.failed = True
                    self.close_failures += 1
                if self.on_close:
                    self.on_close(arg.__self__, succeeded)
        except Exception:
            # Diagnostic failure must not replace the original SQL return/error.
            self.failed = True

    @contextmanager
    def installed(self):
        previous = sys.getprofile()
        thread = threading.get_ident()
        try:
            sys.setprofile(self)
            yield
        finally:
            sys.setprofile(previous)
            self.profiler_restored = sys.getprofile() is previous
            if threading.get_ident() != thread or self.pending:
                self.failed = True
            self.pending.clear()  # Release bound method references on every exit.

    def snapshot(self):
        return dict(valid=not self.failed and not any(self.dropped.values()) and not self.active_connections
                    and not self.pending and self.profiler_restored,
            active_connections=self.active_connections, pending=len(self.pending), profiler_restored=self.profiler_restored,
            close_failures=self.close_failures, incomplete_lifetimes=self.incomplete_lifetimes,
            bounds=dict(sites=self.MAX_SITES, pending=self.MAX_PENDING), dropped=dict(self.dropped),
            sites=[dict(row) for _, row in sorted(self.sites.items())])


def source_callers():
    from app import library, knowledge, catalog_guard
    groups = ((library, ("index_task", "_connect", "_ensure_schema")),
              (knowledge, ("replace_task_evidence", "replace_task_evidence_in_transaction", "_connect", "ensure_evidence_schema",
                           "_write_evidence", "_fts_available")),
              (catalog_guard, ("connect_catalog", "validate_catalog_version")))
    result = {inspect.unwrap(getattr(module, name)).__code__: module.__name__.split(".")[-1] + "." + name
              for module, names in groups for name in names}
    result[catalog_guard._GuardedConnection.close.__code__] = "catalog_guard.close"
    return result


@contextmanager
def catalog_profiles(native):
    """Only catalog lifetimes; original connections and close methods survive."""
    from app import library, catalog_guard
    original = catalog_guard.connect_catalog
    if library.connect_catalog is not original:
        raise AssertionError("diagnostic_catalog_alias_mismatch")
    owner, opening, lifetime = threading.get_ident(), 0, None
    active = {}

    def finish():
        nonlocal lifetime
        if lifetime is not None and not active and not opening:
            current, lifetime = lifetime, None
            current.__exit__(None, None, None)

    def closed(connection, succeeded):
        if not succeeded:
            return  # A close exception is not evidence that its lifetime ended.
        if active.get(id(connection)) is connection:
            del active[id(connection)]
        native.active_connections = len(active)
        finish()

    @functools.wraps(original)
    def connect(*args, **kwargs):
        nonlocal opening, lifetime
        if threading.get_ident() != owner:
            return original(*args, **kwargs)
        if lifetime is None:
            lifetime = native.installed()
            lifetime.__enter__()
        opening += 1
        try:
            connection = original(*args, **kwargs)
            if len(active) == native.MAX_PENDING:
                native.failed = True
            else:
                active[id(connection)] = connection
                native.active_connections = len(active)
            return connection
        finally:
            opening -= 1
            finish()  # A failing connect must restore the previous profiler too.

    native.on_close = closed
    with patch.object(catalog_guard, "connect_catalog", connect), patch.object(library, "connect_catalog", connect):
        try:
            yield
        finally:
            if lifetime is not None:
                native.failed = True  # Unclosed/failed observation, never close product handles here.
                native.incomplete_lifetimes += len(active)
                active.clear()
                native.active_connections = 0
                lifetime.__exit__(None, None, None)
            native.on_close = None


def digest_tree(root):
    digest = hashlib.sha256()
    files = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("diagnostic_dataset_symlink")
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            files += 1
    return dict(sha256=digest.hexdigest(), files=files)


def restore_dataset(seed, data, marker):
    # Both paths were exclusively created by this invocation. Refuse any altered
    # identity before recursively removing only this one diagnostic data tree.
    if data.is_symlink() or seed.is_symlink() or data.parent != seed.parent or data.name != "data":
        raise ValueError("diagnostic_dataset_identity")
    for root in (seed, data):
        path = root / "progressive-slo-fixture.json"
        if path.is_symlink() or json.loads(path.read_text()) != marker:
            raise ValueError("diagnostic_dataset_marker")
    digest_tree(seed)
    digest_tree(data)
    shutil.rmtree(data)
    shutil.copytree(seed, data)


def seed_tasks(data, request_builder):
    from app import processor, storage
    from app.models import CurrentPageTaskRequest
    from app.task_queue import queue_for
    # Same deterministic final-summary return shape as progressive-slo-fixture;
    # no held browser-visibility gate is needed when only seeding retained data.
    def summary(title, transcript, *args, **kwargs):
        return "# " + title + "\n\n## Source evidence\n\n" + transcript.segments[0].text, "offline-fixture", "", []
    queue = queue_for(data)
    rows = []
    started = time.perf_counter()
    try:
        with patch.object(processor, "summarize_with_diagnostics", summary):
            for minutes in DURATIONS:
                for repetition in range(REPETITIONS):
                    request = CurrentPageTaskRequest.model_validate(request_builder(minutes, f"catalog-{repetition}"))
                    task = storage.create_task("current_page", request.title, request.page_url, options=request.options)
                    queue.enqueue(task.id, "page_light", lambda task=task, request=request:
                        processor.process_current_page_task(task.id, request)).result(30)
                    record = storage.get_task(task.id)
                    if record.status != "success":
                        raise RuntimeError("diagnostic_seed_failed")
                    transcript = storage.read_json(task.id, "transcript.json", {})
                    expected = [dict(start=cue.start, end=cue.end, text=cue.text) for cue in request.browser_subtitles]
                    if transcript.get("segments") != expected or len(expected) != minutes * 2:
                        raise RuntimeError("diagnostic_caption_count")
                    rows.append(dict(task_id=task.id, minutes=minutes, cues=minutes * 2))
    finally:
        queue.stop()
    if any(worker.is_alive() for worker in queue.workers.values()):
        raise RuntimeError("diagnostic_seed_workers_active")
    return rows, time.perf_counter() - started


def projection_state(data):
    connection = sqlite3.connect((data / "library.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        counts, digest = {}, hashlib.sha256()
        for name in ("library_tasks", "library_tasks_fts", "source_evidence", "source_evidence_fts"):
            cursor = connection.execute("SELECT * FROM " + name + " ORDER BY 1")
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchall()
            counts[name] = len(rows)
            volatile = {"updated_at"} if name == "library_tasks" else {"created_at"} if name == "source_evidence" else set()
            values = [[value for column, value in zip(columns, row) if column not in volatile] for row in rows]
            digest.update(name.encode() + json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode())
        return dict(counts=counts, semantic_sha256=digest.hexdigest())
    finally:
        connection.close()


def measure(app, diagnostics, task_id, enabled, result):
    from app import storage
    callers = source_callers()
    result.update(observer_enabled=enabled)
    collector = native = None
    primary_failure = False
    try:
        with ExitStack() as stack:
            collector = diagnostics.install(app, stack) if enabled else None
            native = NativeCalls(collector, callers) if enabled else None
            if native:
                stack.enter_context(catalog_profiles(native))
            start = time.perf_counter(), time.thread_time()
            try:
                record = storage.update_task(task_id, status="success", phase="completed", progress=100)
            finally:
                result.update(wall_s=time.perf_counter() - start[0], thread_cpu_s=time.thread_time() - start[1])
    except BaseException:
        primary_failure = True
        raise
    finally:
        if native:
            try:
                result.update(native=native.snapshot(), contention=collector.snapshot())
            except Exception:
                if not primary_failure:
                    raise
                result["diagnostic_snapshot_failed"] = True
    if native:
        if not result["native"]["valid"]:
            raise RuntimeError("diagnostic_profile_incomplete")
    if (record.status, record.phase, record.progress) != ("success", "completed", 100):
        raise RuntimeError("diagnostic_update_failed")
    result["task_semantic_sha256"] = hashlib.sha256(json.dumps(record.model_dump(mode="json", exclude={"updated_at"}),
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def run(output):
    fixture = load("catalog_fixture", "scripts/progressive-slo-fixture.py")
    diagnostics = load("catalog_contention", "scripts/progressive-slo-contention.py")
    helpers = load("catalog_reference_helpers", "scripts/tests/test_progressive_slo_fixture.py")
    report = dict(schema_version=1, diagnostic_only=True, acceptance=False, completed=False, arms=[],
        scope="80 synthetic retained tasks; one original-path completion update per restored arm",
        caveats=["No browser timing or 80-row SLO acceptance", "No attribution to historical row 67",
                 "Wall time includes scheduling and GIL reacquisition; CPU clock may be coarse",
                 "Observer-off/profiled/off order and OS cache effects confound overhead delta",
                 "Native call spans and outer observer spans are inclusive; do not sum them",
                 "executescript includes implicit transaction work"],
        host=dict(platform=platform.system(), python=platform.python_version(), sqlite=sqlite3.sqlite_version),
        source=dict(commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
        clocks={name: vars(time.get_clock_info(name)) for name in ("perf_counter", "thread_time")})
    data, seed = output / "data", output / "seed"
    data.mkdir()
    def save():
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    save()
    primary_failure = False
    try:
        with ExitStack() as stack:
            app, _ = fixture.configure_fixture(ROOT, data, stack)
            from app import storage
            rows, elapsed = seed_tasks(data, helpers.reference_request)
            target = rows[-1]["task_id"]
            storage.update_task(target, status="running", phase="summarizing", progress=78)
            counts = projection_state(data)["counts"]
            if len(rows) != 80 or sum(row["cues"] for row in rows) != 11000 or counts != dict(
                    library_tasks=80, library_tasks_fts=80, source_evidence=11080, source_evidence_fts=11080):
                raise RuntimeError("diagnostic_dataset_count")
            shutil.copytree(data, seed)
            report["seed"] = dict(tasks=rows, seconds=elapsed, counts=counts, files=digest_tree(seed), target=target)
            save()
            print(json.dumps(dict(seeded_tasks=80, seed_seconds=elapsed)), flush=True)
            for label, enabled in (("control_before", False), ("profiled", True), ("control_after", False)):
                restore_dataset(seed, data, fixture.MARKER)
                input_files = digest_tree(data)
                if input_files != report["seed"]["files"]:
                    raise RuntimeError("diagnostic_restore_mismatch")
                arm = dict(label=label, input_files=input_files)
                report["arms"].append(arm)
                measure(app, diagnostics, target, enabled, arm)
                arm["output"] = projection_state(data)
                first = report["arms"][0]
                if (arm["output"]["counts"] != counts or arm["output"] != first["output"]
                        or arm["task_semantic_sha256"] != first["task_semantic_sha256"]):
                    raise RuntimeError("diagnostic_projection_changed")
                save()
            baseline = sum(report["arms"][index]["wall_s"] for index in (0, 2)) / 2
            report["observed_wall_delta_s"] = report["arms"][1]["wall_s"] - baseline
            report["completed"] = True
    except BaseException as error:
        primary_failure = True
        try:
            report["failure"] = fixture.callback_exception_chain(error)
        except Exception:
            report["failure_formatting_failed"] = True
        raise
    finally:
        try:
            save()
        except Exception:
            if not primary_failure:
                raise
            print("Diagnostic report persistence failed during primary failure cleanup.", file=sys.stderr)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    output = parser.parse_args().output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never reuse arbitrary task data.
    try:
        run(output)
    except Exception:
        print("Synthetic catalog diagnostic failed; see the redacted owned report.", file=sys.stderr)
        return 1
    print("Synthetic catalog diagnostic complete; this is not release acceptance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
