"""Offline contracts for the opt-in fixture contention collector.

These tests measure no product SLO and never use a user data directory.
"""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_collector():
    spec = importlib.util.spec_from_file_location(
        "progressive_slo_contention_test", ROOT / "scripts/progressive-slo-contention.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProgressiveSloContentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_collector()

    def setUp(self):
        self.collector = self.module.Collector()
        self.real = threading.RLock()
        self.lock = self.module.MeasuredTaskLock(self.real, self.collector)

    def test_reentrant_acquire_release_and_nonblocking_are_transparent(self):
        self.assertIs(self.lock.acquire(), True)
        self.assertIs(self.lock.acquire(False), True)
        self.assertIs(self.lock.acquire(blocking=False), True)
        self.assertIs(self.lock.release(), None)
        self.assertIs(self.lock.release(), None)
        self.assertIs(self.lock.release(), None)
        with self.assertRaises(RuntimeError):
            self.lock.release()
        # A different thread can acquire after the final release; bookkeeping
        # must not retain ownership after a balanced nested acquisition.
        result = queue.Queue()
        def acquire_from_another_thread():
            acquired = self.lock.acquire(False)
            result.put(acquired)
            if acquired:
                self.lock.release()
        thread = threading.Thread(target=acquire_from_another_thread)
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIs(result.get_nowait(), True)

    def test_failed_nonblocking_and_timed_acquire_do_not_release_owner(self):
        outcomes = queue.Queue()
        self.lock.acquire()
        def waiter():
            try:
                outcomes.put((self.lock.acquire(False), self.lock.acquire(timeout=.01)))
                try:
                    self.lock.release()
                except RuntimeError:
                    outcomes.put("non_owner_release_rejected")
            except BaseException as error:
                outcomes.put(error)
        thread = threading.Thread(target=waiter)
        try:
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes.get_nowait(), (False, False))
            self.assertEqual(outcomes.get_nowait(), "non_owner_release_rejected")
            # The owner's depth remains intact even after the failed attempts.
            self.assertIs(self.lock.acquire(False), True)
            self.lock.release()
        finally:
            self.lock.release()
            thread.join(2)

    def test_invalid_acquire_arguments_preserve_native_exception_types(self):
        for args, kwargs in (((False, .01), {}), ((), {"timeout": -2}), ((), {"unexpected": True})):
            with self.subTest(args=args, kwargs=kwargs):
                try:
                    self.real.acquire(*args, **kwargs)
                except Exception as expected:
                    with self.assertRaises(type(expected)):
                        self.lock.acquire(*args, **kwargs)
                else:
                    self.real.release()
                    self.fail("The native lock unexpectedly accepted invalid arguments")
        # Failed attempts must not poison a later legitimate acquisition.
        with self.lock:
            with self.lock:
                pass

    def test_context_manager_preserves_exception_and_releases(self):
        failure = ValueError("synthetic body failure")
        with self.assertRaises(ValueError) as raised:
            with self.collector.operation("get_task", task_id="a" * 12, phase="reading"):
                with self.lock:
                    raise failure
        self.assertIs(raised.exception, failure)
        self.assertIs(self.lock.acquire(False), True)
        self.lock.release()
        with self.assertRaises(RuntimeError):
            self.lock.release()

    def test_underlying_lock_exceptions_are_not_replaced(self):
        class BrokenLock:
            def __init__(self):
                self.acquire_error = OSError("synthetic acquire failure")
                self.release_error = RuntimeError("synthetic release failure")
            def acquire(self, *args, **kwargs):
                raise self.acquire_error
            def release(self):
                raise self.release_error
        real = BrokenLock()
        measured = self.module.MeasuredTaskLock(real, self.collector)
        with self.assertRaises(OSError) as acquired:
            measured.acquire()
        self.assertIs(acquired.exception, real.acquire_error)
        with self.assertRaises(RuntimeError) as released:
            measured.release()
        self.assertIs(released.exception, real.release_error)

    def test_operation_and_span_body_exceptions_propagate_unchanged(self):
        failure = LookupError("private exception contents must not be collected")
        with self.assertRaises(LookupError) as raised:
            with self.collector.operation("get_task", task_id="b" * 12, phase="reading"):
                with self.collector.span("manifest_read"):
                    raise failure
        self.assertIs(raised.exception, failure)
        self.assertNotIn(str(failure), json.dumps(self.collector.snapshot()))

    def test_real_waiter_identifies_owner_task_and_critical_section(self):
        waiting = threading.Event()
        outcome = queue.Queue()

        def waiter():
            try:
                with self.collector.operation("selected_handler", task_id="b" * 12):
                    waiting.set()
                    with self.lock:
                        outcome.put("acquired")
            except BaseException as error:
                outcome.put(error)

        def owner_critical():
            with self.collector.operation("update_task", task_id="a" * 12, phase="summarizing"):
                with self.collector.span("atomic_file_write"):
                    with self.lock:
                        owner_snapshot = self.collector.snapshot()
                        thread.start()
                        self.assertTrue(waiting.wait(2))
                        # Keep a real RLock contended while the other thread waits.
                        thread.join(.03)
                        self.assertTrue(thread.is_alive())
                        return owner_snapshot["lock_owner"]

        thread = threading.Thread(target=waiter)
        with patch.object(self.module, "SLOW_SECONDS", 0):
            owner = owner_critical()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome.get_nowait(), "acquired")
        report = self.collector.snapshot()
        waits = [event for event in report["recent_events"]
                 if event["kind"] == "lock_wait" and event["operation"]["task_id"] == "b" * 12]
        self.assertEqual(len(waits), 1)
        wait = waits[0]
        self.assertTrue(wait["acquired"])
        self.assertGreater(wait["wall_s"], 0)
        self.assertEqual(wait["operation"]["name"], "selected_handler")
        self.assertEqual(wait["owner_at_entry"], owner)
        self.assertEqual(owner["operation"]["task_id"], "a" * 12)
        self.assertEqual(owner["operation"]["phase"], "summarizing")
        self.assertEqual(owner["section"], "atomic_file_write")
        self.assertEqual(owner["critical"], "owner_critical")
        holds = [event for event in report["recent_events"]
                 if event["kind"] == "lock_hold" and event["owner"]["hold_id"] == owner["hold_id"]]
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]["owner"], owner)
        self.assertIsNone(report["lock_owner"])
        self.assertEqual(report["active"], [])

    def test_nested_operations_and_inclusive_spans_restore_identity(self):
        with patch.object(self.module, "SLOW_SECONDS", 0):
            with self.collector.operation("list_handler") as outer:
                with self.collector.span("list_reconcile"):
                    with self.collector.operation("update_task", task_id="c" * 12) as inner:
                        with self.collector.span("manifest_read_validate"):
                            with self.lock:
                                pass
                    self.assertEqual(self.collector.identity()["id"], outer["id"])
                    with self.lock:
                        self.assertEqual(self.collector.snapshot()["lock_owner"]["section"], "list_reconcile")
            with self.lock:
                self.assertEqual(self.collector.snapshot()["lock_owner"]["section"], "unlabelled")
        report = self.collector.snapshot()
        by_name = {row["name"]: row for row in report["operations"]}
        self.assertEqual(by_name["update_task"]["parent_id"], outer["id"])
        self.assertIsNone(by_name["list_handler"]["parent_id"])
        self.assertEqual(inner["id"], by_name["update_task"]["id"])
        self.assertEqual(self.collector.identity()["id"], 0)
        self.assertEqual(by_name["update_task"]["metrics"]["manifest_read_validate"]["count"], 1)
        outer_span = by_name["list_handler"]["metrics"]["list_reconcile"]
        inner_span = by_name["update_task"]["metrics"]["manifest_read_validate"]
        self.assertGreaterEqual(outer_span["wall_s"], inner_span["wall_s"])
        self.assertIn("inclusive", report["scope"])

    def test_reentrant_lock_records_one_outermost_hold(self):
        with patch.object(self.module, "SLOW_SECONDS", 0):
            with self.collector.operation("update_task", task_id="d" * 12):
                with self.lock:
                    first = self.collector.snapshot()["lock_owner"]
                    with self.lock:
                        self.assertEqual(self.collector.snapshot()["lock_owner"], first)
                    self.assertEqual(self.collector.snapshot()["lock_owner"], first)
        report = self.collector.snapshot()
        self.assertEqual(report["totals"]["task_lock_wait"]["count"], 2)
        self.assertEqual(report["totals"]["task_lock_hold"]["count"], 1)
        holds = [row for row in report["recent_events"] if row["kind"] == "lock_hold"]
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]["owner"]["hold_id"], first["hold_id"])

    def test_repeated_record_overflow_keeps_all_retained_collections_bounded(self):
        collector = self.module.Collector(max_operations=3, max_events=4, max_slow_events=2, max_active=2)
        with patch.object(self.module, "SLOW_SECONDS", 0):
            for batch in range(2):
                for index in range(100):
                    with collector.operation("update_task", task_id=f"{index:012x}"):
                        with collector.span("manifest_read_validate"):
                            pass
                report = collector.snapshot()
                count = (batch + 1) * 100
                self.assertEqual(len(report["operations"]), 3)
                self.assertEqual(len(report["recent_events"]), 4)
                self.assertEqual(len(report["slow_events"]), 2)
                self.assertEqual(report["dropped"]["operations"], count - 3)
                self.assertEqual(report["dropped"]["recent_events"], count - 4)
                self.assertEqual(report["dropped"]["slow_events"], count - 2)
                self.assertEqual(report["totals"]["manifest_read_validate"]["count"], count)
                self.assertEqual(len(collector.operations), 3)
                self.assertEqual(len(collector.events), 4)
                self.assertEqual(len(collector.slow), 2)
                self.assertEqual(collector.active, {})
        self.assertEqual(report["bounds"]["operations"], 3)
        self.assertEqual(report["bounds"]["recent_events"], 4)
        self.assertEqual(report["bounds"]["slow_events"], 2)
        self.assertEqual(report["schema_version"], 1)
        self.assertIn("platform", report["host"])
        self.assertIn("monotonic_seconds", report["clock"])

    def test_active_and_metric_overflow_are_bounded_and_recover(self):
        collector = self.module.Collector(max_operations=3, max_events=4, max_slow_events=2, max_active=2)
        for _ in range(2):
            with collector.operation("list_handler") as outer:
                with collector.operation("selected_handler"):
                    with collector.operation("update_task"):
                        self.assertEqual(len(collector.snapshot()["active"]), 2)
                    self.assertEqual(len(collector.snapshot()["active"]), 2)
                self.assertEqual(collector.identity()["id"], outer["id"])
                for number in range(100):
                    # Valid static-shaped labels exercise metric cardinality, not input retention.
                    label = "span_" + chr(97 + number // 26) + chr(97 + number % 26)
                    with collector.span(label):
                        pass
                self.assertLessEqual(len(outer["metrics"]), collector.limits["metrics"])
            self.assertEqual(collector.snapshot()["active"], [])
        report = collector.snapshot()
        self.assertEqual(report["dropped"]["active"], 2)
        self.assertGreater(report["dropped"]["metrics"], 0)
        self.assertLessEqual(len(report["totals"]), report["bounds"]["metrics"])
        self.assertTrue(all(len(row["metrics"]) <= report["bounds"]["metrics"]
                            for row in report["operations"]))

    def test_snapshot_and_operation_finalization_are_one_consistent_transition(self):
        collector = self.module.Collector()
        real_mutex = collector.mutex
        finish_body, body_finished = threading.Event(), threading.Event()
        copying_active, resume_copy = threading.Event(), threading.Event()
        finalization_waiting = threading.Event()
        rows, snapshots, failures = queue.Queue(), queue.Queue(), queue.Queue()
        worker_id = []

        class ObservedMutex:
            def __enter__(self):
                if worker_id and threading.get_ident() == worker_id[0] and body_finished.is_set():
                    # On the old implementation, the active row has already
                    # resized before this acquisition. The fixed transition
                    # cannot change it until snapshot releases this mutex.
                    finalization_waiting.set()
                return real_mutex.__enter__()

            def __exit__(self, *args):
                return real_mutex.__exit__(*args)

        def operate():
            try:
                worker_id.append(threading.get_ident())
                with collector.operation("selected_handler", task_id="e" * 12) as row:
                    rows.put(row)
                    if not finish_body.wait(5):
                        raise AssertionError("Operation body was not released")
                    body_finished.set()
            except BaseException as error:
                failures.put(error)

        def take_snapshot():
            try:
                snapshots.put(collector.snapshot())
            except BaseException as error:
                failures.put(error)

        worker = threading.Thread(target=operate, daemon=True)
        reader = threading.Thread(target=take_snapshot, daemon=True)
        original_dict_copy = copy._deepcopy_dispatch[dict]
        with patch.object(collector, "mutex", ObservedMutex()):
            worker.start()
            try:
                row = rows.get(timeout=2)

                def paused_dict_copy(value, memo, *args):
                    if value is row["metrics"]:
                        # deepcopy is iterating the active row's actual dict
                        # when it reaches this nested value. Resizing the row
                        # before that iterator resumes reproduces the race.
                        copying_active.set()
                        if not resume_copy.wait(5):
                            raise AssertionError("Snapshot copy was not released")
                    return original_dict_copy(value, memo, *args)

                with patch.dict(copy._deepcopy_dispatch, {dict: paused_dict_copy}):
                    reader.start()
                    try:
                        self.assertTrue(copying_active.wait(2), "Snapshot did not begin copying the active row")
                        finish_body.set()
                        self.assertTrue(finalization_waiting.wait(2), "Worker did not reach finalization")
                    finally:
                        resume_copy.set()
                        reader.join(2)
                        worker.join(2)
            finally:
                finish_body.set()
                resume_copy.set()
                worker.join(2)
                if reader.ident is not None:
                    reader.join(2)
        self.assertFalse(worker.is_alive(), "Operation finalization deadlocked")
        self.assertFalse(reader.is_alive(), "Snapshot deadlocked")
        if not failures.empty():
            raise failures.get_nowait()
        during = snapshots.get_nowait()
        self.assertEqual(during["operations"], [])
        self.assertEqual(len(during["active"]), 1)
        self.assertEqual(during["active"][0]["id"], row["id"])
        completion_fields = {"end_s", "wall_s", "thread_cpu_s", "raised"}
        self.assertFalse(completion_fields & during["active"][0].keys())
        after = collector.snapshot()
        self.assertEqual(after["active"], [])
        self.assertEqual(len(after["operations"]), 1)
        self.assertEqual(after["operations"][0]["id"], row["id"])
        self.assertTrue(completion_fields <= after["operations"][0].keys())
        self.assertFalse(after["operations"][0]["raised"])
        self.assertEqual(after["dropped"]["operations"], 0)

    def test_slowest_events_keep_largest_intervals_while_recent_events_roll(self):
        collector = self.module.Collector(max_operations=2, max_events=2, max_slow_events=2, max_active=2)
        with patch.object(self.module, "SLOW_SECONDS", 0):
            for duration in (1, 5, 3, 2, 4, 1):
                collector.event("boundary", "manifest_read_validate", (0., 0.), (float(duration), 0.))
        report = collector.snapshot()
        self.assertEqual([row["wall_s"] for row in report["recent_events"]], [4, 1])
        self.assertEqual([row["wall_s"] for row in report["slow_events"]], [5, 4])
        self.assertEqual(report["dropped"]["recent_events"], 4)
        self.assertEqual(report["dropped"]["slow_events"], 4)

    def test_invalid_limits_cannot_disable_collection_bounds(self):
        for field in ("max_operations", "max_events", "max_slow_events", "max_active"):
            for invalid in (0, -1, 513, float("inf"), True, "256"):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        self.module.Collector(**{field: invalid})

    def test_snapshot_is_detached_and_private_inputs_are_not_retained(self):
        private = "https://private.invalid/lesson?token=fixture-secret"
        with self.collector.operation("get_task", task_id=private, phase=private):
            with self.collector.span("manifest_read_validate"):
                pass
        for method in (self.collector.operation, self.collector.span):
            with self.assertRaises(ValueError):
                with method(private):
                    pass
        first = self.collector.snapshot()
        self.assertNotIn(private, json.dumps(first))
        self.assertEqual(first["operations"][0]["task_id"], "")
        self.assertEqual(first["operations"][0]["phase"], "")
        first["operations"][0]["name"] = "changed"
        first["operations"][0]["metrics"].clear()
        first["bounds"]["operations"] = 10000
        first["dropped"]["operations"] = 10000
        second = self.collector.snapshot()
        self.assertEqual(second["operations"][0]["name"], "get_task")
        self.assertIn("manifest_read_validate", second["operations"][0]["metrics"])
        self.assertEqual(second["bounds"]["operations"], 256)
        self.assertEqual(second["dropped"]["operations"], 0)


class ProgressiveSloContentionFixtureTests(unittest.TestCase):
    """Actual imports/configuration live in an offline, disposable subprocess."""

    BOOTSTRAP = r"""
from contextlib import ExitStack
import builtins
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
from unittest.mock import patch
root = Path.cwd()
data = Path(os.environ['LEARNNOTE_DATA_DIR'])

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, root / 'scripts' / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

fixture = load('isolated_contention_fixture', 'progressive-slo-fixture.py')
diagnostics = load('isolated_contention_diagnostics', 'progressive-slo-contention.py')
with ExitStack() as fixture_stack:
    app, metadata = fixture.configure_fixture(root, data, fixture_stack)
    from app import (storage, main, processor, processor_state, subtitle_notes,
                     pipeline_progress, progressive_sections, screen_subtitle_tasks,
                     duration_estimates, whole_duration_estimates)
    assert '/_fixture/contention' not in {getattr(route, 'path', '') for route in app.routes}
    assert not metadata.get('contention_diagnostics', False)
    modules = (storage, main, processor, processor_state, subtitle_notes,
               pipeline_progress, progressive_sections, screen_subtitle_tasks,
               duration_estimates, whole_duration_estimates)
    before = {module: {name: value for name, value in vars(module).items()
                      if callable(value) or value is storage._lock} for module in modules}
    real_lock = storage._lock
    lock_aliases = [(module, name) for module in tuple(sys.modules.values())
                    if getattr(module, '__name__', '').startswith('app.')
                    for name, value in tuple(vars(module).items()) if value is real_lock]
    assert len(lock_aliases) >= 4
    routes = [(route.dependant, route.dependant.call) for route in app.routes if hasattr(route, 'dependant')]
    middleware, middleware_stack = list(app.user_middleware), app.middleware_stack
    runtime = [(target, name, getattr(target, name)) for target, name in (
        (builtins, 'open'), (Path, 'open'), (Path, 'read_text'), (Path, 'read_bytes'),
        (Path, 'write_text'), (json, 'loads'), (json, 'dumps'),
        (sqlite3, 'connect'), (threading, 'RLock'))]

    def assert_runtime_unchanged():
        for target, name, value in runtime:
            assert getattr(target, name) is value, 'Shared runtime patched: ' + name

    def assert_restored():
        for module, values in before.items():
            for name, value in values.items():
                assert getattr(module, name) is value, module.__name__ + '.' + name
        for target, call in routes:
            assert target.call is call
        assert app.user_middleware == middleware
        assert app.middleware_stack is middleware_stack
        for module, name in lock_aliases:
            assert getattr(module, name) is real_lock
        assert_runtime_unchanged()

    # TEST_BODY
"""

    def run_isolated(self, body):
        code = self.BOOTSTRAP.replace('    # TEST_BODY', '\n'.join('    ' + line for line in body.splitlines()))
        with tempfile.TemporaryDirectory(prefix="learnnote-contention-contract-") as name:
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("LEARNNOTE_", "OPENAI_", "AZURE_", "ANTHROPIC_"))
                   and not key.upper().endswith("_PROXY")}
            env.update(LEARNNOTE_DATA_DIR=name, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                       PYTHONPATH=str(ROOT / "backend"))
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_aliases_wrappers_and_middleware_restore_without_global_patches(self):
        self.run_isolated(r"""
with ExitStack() as profile_stack:
    collector = diagnostics.install(app, profile_stack)
    assert isinstance(storage._lock, diagnostics.MeasuredTaskLock)
    assert all(getattr(module, name) is storage._lock for module, name in lock_aliases)
    assert all(module.update_task is storage.update_task for module in
               (main, processor, processor_state, subtitle_notes, progressive_sections, screen_subtitle_tasks))
    assert all(module.get_task is storage.get_task for module in
               (main, processor, processor_state, subtitle_notes, progressive_sections, screen_subtitle_tasks))
    assert main.read_json is storage.read_json
    assert pipeline_progress.read_json is storage.read_json
    assert whole_duration_estimates._read_evidence is duration_estimates._read
    assert main.read_transcript is processor.read_transcript
    assert_runtime_unchanged()
    # A real missing-manifest failure must keep the original exception contract.
    for call in (lambda: storage.update_task('a' * 12, phase='reading',
                                         message='private source text must not be retained'),
                 lambda: main.update_task(task_id='b' * 12, phase='summarizing')):
        try:
            call()
        except FileNotFoundError:
            pass
        else:
            raise AssertionError('Missing task failure was swallowed')
    report = collector.snapshot()
    assert 'private source text' not in json.dumps(report)
    rows = [row for row in report['operations'] if row['name'] == 'update_task']
    assert len(rows) == 2
    assert [row['task_id'] for row in rows] == ['a' * 12, 'b' * 12]
    assert [row['phase'] for row in rows] == ['reading', 'summarizing']
    assert all(row['raised'] for row in rows)
    assert all('manifest_read_validate' in row['metrics'] for row in rows)
    assert all('state_lease_enter' in row['metrics'] for row in rows)
assert_restored()
""")

    def test_partial_install_failure_restores_before_outer_stack_closes(self):
        self.run_isolated(r"""
failure = RuntimeError('synthetic middleware setup failure')
with ExitStack() as profile_stack:
    with patch.object(app, 'add_middleware', side_effect=failure):
        try:
            diagnostics.install(app, profile_stack)
        except RuntimeError as error:
            assert error is failure
        else:
            raise AssertionError('Setup failure was swallowed')
    # Check while the caller's stack is still open: partial setup must self-unwind.
    assert_restored()
assert_restored()
""")

    def test_diagnostic_route_is_opt_in_and_scoped_to_owned_fixture(self):
        self.run_isolated(r"""
with ExitStack() as enabled_stack:
    enabled_app, enabled_metadata = fixture.configure_fixture(
        root, data, enabled_stack, resume=True, contention_diagnostics=True)
    assert enabled_app is app
    assert enabled_metadata['contention_diagnostics'] is True
    diagnostic_routes = [route for route in app.routes if getattr(route, 'path', '') == '/_fixture/contention']
    assert len(diagnostic_routes) == 1
    report = diagnostic_routes[0].endpoint()
    assert report['schema_version'] == 1
    assert report['bounds']['operations'] == 256
    assert report['bounds']['recent_events'] == 256
    assert report['bounds']['slow_events'] == 64
    assert_runtime_unchanged()
assert '/_fixture/contention' not in {getattr(route, 'path', '') for route in app.routes}
assert_restored()
# A changed ownership marker must fail before installation or route exposure.
(data / 'progressive-slo-fixture.json').write_text('{}', encoding='utf-8')
with ExitStack() as rejected_stack:
    try:
        fixture.configure_fixture(root, data, rejected_stack, resume=True, contention_diagnostics=True)
    except ValueError as error:
        assert 'owned data marker' in str(error)
    else:
        raise AssertionError('Unowned fixture data was accepted')
assert '/_fixture/contention' not in {getattr(route, 'path', '') for route in app.routes}
assert_restored()
""")

    def test_opt_in_selected_http_response_stays_fresh_without_diagnostic_fields(self):
        self.run_isolated(r"""
import socket
import time
from urllib.request import urlopen
import uvicorn
with ExitStack() as enabled_stack:
    fixture.configure_fixture(root, data, enabled_stack, resume=True, contention_diagnostics=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise AssertionError('Isolated loopback fixture did not start')
                time.sleep(.01)

            def get(path):
                with urlopen(origin + path, timeout=10) as response:
                    assert response.status == 200
                    return json.load(response)

            task = storage.create_task('page_text', 'SLO reference selected freshness', mode='page_text')
            storage.update_task(task.id, status='running', phase='summarizing', progress=17)
            first = get('/api/tasks/' + task.id)
            assert first['task']['phase'] == 'summarizing'
            assert first['task']['progress'] == 17
            storage.update_task(task.id, status='success', phase='completed', progress=100)
            second = get('/api/tasks/' + task.id)
            assert second['task']['phase'] == 'completed'
            assert second['task']['progress'] == 100
            assert second['task']['status'] == 'success'
            assert set(first) == set(second) == {'task', 'audit'}
            assert set(first['task']) == set(second['task'])
            diagnostic_keys = {'recent_events', 'slow_events', 'lock_owner', 'owner_at_entry',
                               'thread_cpu_s', 'contention_diagnostics'}
            def assert_product_only(value):
                if isinstance(value, dict):
                    assert not (set(value) & diagnostic_keys), 'Collector data leaked into product response'
                    for item in value.values():
                        assert_product_only(item)
                elif isinstance(value, list):
                    for item in value:
                        assert_product_only(item)
            assert_product_only(first)
            assert_product_only(second)
            report = get('/_fixture/contention')
            selected = [row for row in report['operations']
                        if row['name'] == 'selected_handler' and row['task_id'] == task.id]
            assert len(selected) == 2
            envelopes = [row for row in report['operations']
                         if row['name'] == 'http_request' and row['task_id'] == task.id]
            assert len(envelopes) == 2
            assert all(row['thread_cpu_s'] is None for row in envelopes)
            assert get('/_fixture/state')['forbidden_attempts'] == []
            assert_runtime_unchanged()
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive(), 'Loopback fixture did not stop'
assert_restored()
""")

    def test_task_lock_is_not_used_with_condition_private_save_restore_hooks(self):
        conditions = []
        for source in (ROOT / "backend/app").rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                    node.func.id if isinstance(node.func, ast.Name) else "")
                self.assertNotIn(name, {"_release_save", "_acquire_restore"}, source.relative_to(ROOT))
                if name == "Condition":
                    conditions.append((source.relative_to(ROOT).as_posix(), ast.unparse(node)))
        self.assertEqual(conditions, [("backend/app/task_queue.py", "threading.Condition(threading.RLock())")])

    def test_production_backend_does_not_import_or_expose_fixture_collector(self):
        for source in (ROOT / "backend/app").rglob("*.py"):
            with self.subTest(source=source.relative_to(ROOT)):
                text = source.read_text(encoding="utf-8")
                self.assertNotIn("progressive-slo-contention", text)
                self.assertNotIn("/_fixture/contention", text)


if __name__ == "__main__":
    unittest.main()
