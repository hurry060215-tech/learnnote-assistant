"""Deterministic one-cancellation diagnostic contracts, not latency acceptance."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CancelDiagnosticClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("cancel_diagnostic_tests", "scripts/progressive-slo-cancel-diagnostic.py")

    def test_poll_latency_is_distinct_from_callback_record_return(self):
        now = [100.]
        states = iter([{}, {"status": "cancelled", "waiting": False, "queue": {"callback_finished": 0}},
                       {"status": "cancelled", "waiting": False, "queue": {"callback_finished": 1}}])
        def api(route, **kwargs):
            now[0] += .4 if kwargs["method"] == "POST" else .1
            return next(states)
        result = {}
        value = self.module.cancel_and_drain(api, "a" * 12, result,
            clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertEqual(value["queue"]["callback_finished"], 1)
        self.assertAlmostEqual(result["cancel_and_drain_s"], .625)
        self.assertEqual([row["name"] for row in result["client"]], ["cancel_http", "drain_poll", "drain_poll"])
        self.assertEqual([row.get("callback_finished") for row in result["client"]], [None, 0, 1])
        report = {"clock": {"monotonic_seconds": 90}, "operations": [
            {"name": "callback_finish", "task_id": "a" * 12, "raised": False, "end_s": 10.45}]}
        gap = self.module.callback_observation_gap(report, "a" * 12, result["observed_drained_s"])
        self.assertAlmostEqual(gap["observed_after_callback_s"], .175)
        self.assertNotEqual(gap["observed_after_callback_s"], result["cancel_and_drain_s"])

    def test_missing_ambiguous_or_failed_callback_is_not_inferred_from_poll(self):
        row = {"name": "callback_finish", "task_id": "a" * 12, "raised": False, "end_s": 1}
        for rows in ([], [row, row], [{**row, "raised": True}]):
            self.assertFalse(self.module.callback_observation_gap(
                {"clock": {"monotonic_seconds": 0}, "operations": rows}, "a" * 12, 2)["available"])

    def test_poll_ring_is_bounded_and_timeout_keeps_evidence(self):
        now = [0.]
        def api(route, **kwargs):
            now[0] += .1
            return {"status": "cancelled", "waiting": False, "queue": {"callback_finished": 0}}
        result = {}
        with self.assertRaises(TimeoutError):
            self.module.cancel_and_drain(api, "a" * 12, result, timeout=10,
                clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertEqual(len(result["client"]), self.module.CLIENT_LIMIT)
        self.assertGreater(result["client_dropped"], 0)
        self.assertNotIn("observed_drained_s", result)

    def test_client_exception_survives_without_retaining_message(self):
        error = RuntimeError("private canary")
        def api(*args, **kwargs):
            raise error
        result = {}
        with self.assertRaises(RuntimeError) as raised:
            self.module.cancel_and_drain(api, "a" * 12, result)
        self.assertIs(raised.exception, error)
        self.assertTrue(result["client"][0]["raised"])
        self.assertNotIn("private canary", str(result))


class CancelDiagnosticLifecycleTests(unittest.TestCase):
    def run_isolated(self, body):
        existing = load("cancel_existing_fixture_tests", "scripts/tests/test_progressive_slo_contention.py")
        existing.ProgressiveSloContentionFixtureTests().run_isolated(body)

    def test_lifecycle_boundaries_and_every_alias_restore_on_callback_error(self):
        self.run_isolated(r'''
from app import task_queue
original_set_state = task_queue.LocalTaskQueue.set_state
try:
    with ExitStack() as profile_stack:
        collector = diagnostics.install(app, profile_stack)
        diagnostics.install_cancellation_spans(app, profile_stack, collector)
        task = storage.create_task('current_page', 'SLO reference cancellation')
        storage.update_task(task.id, status='running', phase='summarizing')
        assert main.request_task_cancel is storage.request_task_cancel
        assert processor._check_cancel is processor_state.check_cancel
        assert processor.mark_task_cancelled is processor_state.mark_task_cancelled is storage.mark_task_cancelled
        storage.request_task_cancel(task.id)
        try:
            processor._check_cancel(task.id)
        except processor_state.TaskCancelled:
            pass
        else:
            raise AssertionError('Cancellation exception swallowed')
        processor.mark_task_cancelled(task.id)
        snapshot = collector.snapshot()
        labels = {row['name'] for row in snapshot['operations']}
        assert {'cancel_request', 'worker_check', 'cancel_acknowledge', 'manifest_save', 'index_return'} <= labels
        assert len([row for row in snapshot['operations'] if row['name'] == 'cancel_acknowledge']) == 2
        assert any(row['name'] == 'worker_check' and row['raised'] for row in snapshot['operations'])
        assert_runtime_unchanged()
        raise RuntimeError('intentional exit')
except RuntimeError as error:
    assert str(error) == 'intentional exit'
assert task_queue.LocalTaskQueue.set_state is original_set_state
assert_restored()
''')

    def test_partial_lifecycle_install_restores_before_stack_exit(self):
        self.run_isolated(r'''
from app import task_queue
original_set_state = task_queue.LocalTaskQueue.set_state
with ExitStack() as profile_stack:
    collector = diagnostics.Collector()
    with patch.object(processor, '_check_cancel', lambda value: None):
        expected = processor._check_cancel
        try:
            diagnostics.install_cancellation_spans(app, profile_stack, collector)
        except AssertionError:
            pass
        else:
            raise AssertionError('Alias disagreement accepted')
        assert processor._check_cancel is expected
        assert main.request_task_cancel is before[main]['request_task_cancel']
        assert storage.request_task_cancel is before[storage]['request_task_cancel']
    assert task_queue.LocalTaskQueue.set_state is original_set_state
    assert_restored()
''')

    def test_queue_boundary_preserves_original_values_errors_and_cleanup(self):
        self.run_isolated(r'''
from app import task_queue
original_set_state = task_queue.LocalTaskQueue.set_state
failure = RuntimeError('queue failure canary')
def set_state(self, task_id, state, *, callback_finished=None):
    if state == 'failed':
        raise failure
    return ('sentinel', callback_finished)
with patch.object(task_queue.LocalTaskQueue, 'set_state', set_state):
    with ExitStack() as profile_stack:
        collector = diagnostics.Collector()
        diagnostics.install_cancellation_spans(app, profile_stack, collector)
        queue = object.__new__(task_queue.LocalTaskQueue)
        assert queue.set_state('a' * 12, 'running', callback_finished=False) == ('sentinel', False)
        assert queue.set_state('a' * 12, 'done', callback_finished=True) == ('sentinel', True)
        try:
            queue.set_state('a' * 12, 'failed', callback_finished=True)
        except RuntimeError as error:
            assert error is failure
        else:
            raise AssertionError('Queue failure swallowed')
        rows = [row for row in collector.snapshot()['operations'] if row['name'] == 'callback_finish']
        assert len(rows) == 2 and [row['raised'] for row in rows] == [False, True]
        assert 'queue failure canary' not in json.dumps(rows)
    assert task_queue.LocalTaskQueue.set_state is set_state
assert task_queue.LocalTaskQueue.set_state is original_set_state
assert_restored()
''')


class CancelDiagnosticRunCleanupTests(unittest.TestCase):
    """Inject run-level faults without seeding data, starting threads or HTTP."""
    @classmethod
    def setUpClass(cls):
        cls.module = load("cancel_diagnostic_run_tests", "scripts/progressive-slo-cancel-diagnostic.py")

    def exercise(self, *, primary=None, failures=(), queue_alive=False, http_alive=False):
        events = []
        errors = {name: OSError("private cleanup canary " + name) for name in failures}
        def action(name, value=None):
            def call(*args, **kwargs):
                events.append(name)
                if name in errors:
                    raise errors[name]
                return value
            return call
        def configure(root, data, stack):
            stack.callback(action("fixture_restored"))
            return object(), {}
        def install(app, stack):
            stack.callback(action("observer_restored"))
            return collector
        def spans(app, stack, collector):
            stack.callback(action("aliases_restored"))
        def format_failure(error):
            action("format")()
            return [{"category": type(error).__name__}]
        fixture = SimpleNamespace(configure_fixture=configure, callback_exception_chain=format_failure)
        seed = SimpleNamespace(
            seed_tasks=lambda *args: ([{"cues": 137}] * 79 + [{"cues": 177}], 0),
            projection_state=lambda *args: {"counts": dict(library_tasks=80, library_tasks_fts=80,
                source_evidence=11080, source_evidence_fts=11080)})
        helpers = SimpleNamespace(reference_request=lambda *args: {}, OPTIONS={})
        collector = SimpleNamespace(snapshot=action("snapshot", {}))
        diagnostics = SimpleNamespace(install=install, install_cancellation_spans=spans)
        dependencies = dict(cancel_fixture=fixture, cancel_seed=seed,
                            cancel_helpers=helpers, cancel_contention=diagnostics)
        listener = Mock()
        listener.bind.side_effect = action("bind")
        listener.listen.side_effect = action("listen")
        listener.getsockname.return_value = ("127.0.0.1", 12345)
        listener.close.side_effect = action("close")
        class Server:
            started = True
            @property
            def should_exit(self):
                return False
            @should_exit.setter
            def should_exit(self, value):
                action("shutdown")()
        server = Server()
        worker = Mock()
        worker.start.side_effect = action("start")
        worker.join.side_effect = action("join")
        worker.is_alive.side_effect = action("http_state", http_alive)
        queue_worker = Mock()
        queue_worker.is_alive.return_value = queue_alive
        queue = SimpleNamespace(stop=action("queue_stop"), workers={"owned": queue_worker})
        uvicorn = SimpleNamespace(Config=Mock(), Server=action("server", server))
        fake_app = SimpleNamespace()
        modules = {"uvicorn": uvicorn, "app": fake_app,
            "app.task_queue": SimpleNamespace(queue_for=action("queue_for", queue)),
            "app.storage": SimpleNamespace(request_task_cancel=action("cancel"))}
        state = dict(waiting=True, status="running", hashes={}, generation=1, continuation_calls=0,
                     callback=dict(completed=True, failed=False))
        responses = iter([{"task_id": "a" * 12}, {}, state, {"forbidden_attempts": []}])
        def urlopen(*args, **kwargs):
            return io.StringIO(json.dumps(next(responses)))
        def cancel_and_drain(*args):
            events.append("execution")
            if primary is not None:
                raise primary
            return state
        original_write = Path.write_text
        writes = []
        def write(path, *args, **kwargs):
            writes.append(path)
            if len(writes) == 3 and "save" in errors:
                raise errors["save"]
            return original_write(path, *args, **kwargs)
        caught = None
        with tempfile.TemporaryDirectory() as name, \
                patch.object(self.module, "load", side_effect=lambda name, relative: dependencies[name]), \
                patch.object(self.module.socket, "socket", side_effect=action("socket", listener)), \
                patch.object(self.module.threading, "Thread", side_effect=action("thread", worker)), \
                patch.object(self.module, "urlopen", side_effect=urlopen), \
                patch.object(self.module, "cancel_and_drain", side_effect=cancel_and_drain), \
                patch.object(Path, "write_text", new=write), \
                patch.dict(sys.modules, modules):
            try:
                self.module.run(Path(name))
            except BaseException as error:
                caught = error
            report = json.loads((Path(name) / "report.json").read_text())
        self.assertNotIn("private cleanup canary", json.dumps(report))
        for restored in ("aliases_restored", "observer_restored", "fixture_restored"):
            self.assertEqual(events.count(restored), 1)
        self.assertLess(events.index("aliases_restored"), events.index("observer_restored"))
        self.assertLess(events.index("observer_restored"), events.index("fixture_restored"))
        return caught, report, events, errors

    def test_each_cleanup_failure_preserves_primary_and_attempts_later_cleanup(self):
        flags = dict(cancel="cancel_cleanup_failed", queue_for="queue_cleanup_failed",
            queue_stop="queue_cleanup_failed", shutdown="http_shutdown_failed",
            join="http_join_failed", http_state="http_state_failed", close="listener_close_failed",
            snapshot="diagnostic_snapshot_failed", format="failure_format_failed")
        for failure, flag in flags.items():
            with self.subTest(failure=failure):
                primary = LookupError("private primary canary")
                caught, report, events, _ = self.exercise(primary=primary, failures=[failure])
                self.assertIs(caught, primary)
                self.assertFalse(report["completed"])
                self.assertTrue(report[flag])
                self.assertNotIn("private primary canary", json.dumps(report))
                for attempted in ("cancel", "queue_for", "shutdown", "join", "http_state", "close"):
                    self.assertIn(attempted, events)
                if failure != "queue_for":
                    self.assertIn("queue_stop", events)
                self.assertLess(events.index("close"), events.index("aliases_restored"))

    def test_combined_cleanup_failures_never_skip_queue_stop_or_replace_primary(self):
        primary = LookupError("primary")
        caught, report, events, _ = self.exercise(primary=primary,
            failures=["cancel", "queue_stop", "shutdown", "join", "http_state", "close", "snapshot", "format"])
        self.assertIs(caught, primary)
        self.assertIn("queue_stop", events)
        for flag in ("cancel_cleanup_failed", "queue_cleanup_failed", "http_shutdown_failed",
                     "http_join_failed", "http_state_failed", "listener_close_failed",
                     "diagnostic_snapshot_failed", "failure_format_failed"):
            self.assertTrue(report[flag])

    def test_final_report_failure_cannot_replace_primary(self):
        primary = LookupError("primary")
        caught, report, events, _ = self.exercise(primary=primary, failures=["close", "format", "save"])
        self.assertIs(caught, primary)
        self.assertFalse(report["completed"])
        self.assertIn("queue_stop", events)
        self.assertIn("format", events)

    def test_partial_http_setup_always_closes_acquired_listener(self):
        for failure in ("socket", "bind", "listen", "server", "thread", "start"):
            with self.subTest(failure=failure):
                caught, report, events, errors = self.exercise(failures=[failure])
                self.assertIs(caught, errors[failure])
                self.assertIn("queue_stop", events)
                self.assertEqual("close" in events, failure != "socket")
                self.assertNotIn("join", events)
                self.assertFalse(report["completed"])
        caught, report, events, errors = self.exercise(failures=["bind", "queue_stop", "close", "format"])
        self.assertIs(caught, errors["bind"])
        self.assertTrue(report["queue_cleanup_failed"])
        self.assertTrue(report["listener_close_failed"])
        self.assertTrue(report["failure_format_failed"])

    def test_cleanup_failure_after_success_fails_diagnostic_and_restores_aliases(self):
        for failure in ("queue_stop", "shutdown", "join", "http_state", "close"):
            with self.subTest(failure=failure):
                caught, report, events, _ = self.exercise(failures=[failure])
                self.assertIsInstance(caught, RuntimeError)
                self.assertEqual(str(caught), "diagnostic_worker_cleanup_failed")
                self.assertFalse(report["completed"])
                self.assertIn("close", events)
        for options in ({"queue_alive": True}, {"http_alive": True}):
            caught, report, _, _ = self.exercise(**options)
            self.assertIsInstance(caught, RuntimeError)
            self.assertFalse(report["completed"])
            self.assertTrue(report["queue_workers_alive" if "queue_alive" in options else "http_worker_alive"])
            primary = LookupError("primary")
            caught, report, _, _ = self.exercise(primary=primary, **options)
            self.assertIs(caught, primary)
            self.assertFalse(report["completed"])

    def test_successful_cleanup_needs_no_cancellation_and_closes_before_restore(self):
        caught, report, events, _ = self.exercise()
        self.assertIsNone(caught)
        self.assertTrue(report["completed"])
        self.assertFalse(report["http_cleanup_failed"])
        self.assertNotIn("cancel", events)
        self.assertLess(events.index("close"), events.index("aliases_restored"))


if __name__ == '__main__':
    unittest.main()
