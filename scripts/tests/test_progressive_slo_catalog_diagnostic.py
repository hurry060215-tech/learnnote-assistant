"""Contracts for the isolated original-path native-call diagnostic, not an SLO."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CatalogNativeDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load("catalog_diagnostic_contract", "scripts/progressive-slo-catalog-diagnostic.py")
        cls.diagnostics = load("catalog_collector_contract", "scripts/progressive-slo-contention.py")

    def capture(self, function, **callers):
        collector = self.diagnostics.Collector()
        mapping = {function.__code__: "fixed_operation"}
        mapping.update({value.__code__: key for key, value in callers.items()})
        return self.module.NativeCalls(collector, mapping), collector

    def test_real_calls_returns_errors_native_close_and_no_arguments(self):
        primary = []
        class Guarded(sqlite3.Connection):
            def close(self):
                return super().close()
        def operation():
            connection = sqlite3.connect(":memory:", factory=Guarded)
            try:
                connection.executescript("CREATE TABLE private_table(value)")
                connection.execute("INSERT INTO private_table VALUES(?)", ("credential-canary",))
                connection.commit()
                self.assertEqual(connection.execute("SELECT value FROM private_table").fetchone()[0], "credential-canary")
                try:
                    connection.execute("private invalid SQL credential-canary")
                except sqlite3.OperationalError as error:
                    primary.append(error)
                connection.rollback()
            finally:
                connection.close()
        native, collector = self.capture(operation, guarded_close=Guarded.close)
        previous = sys.getprofile()
        with patch.object(self.diagnostics, "SLOW_SECONDS", 0), native.installed():
            operation()
        self.assertIs(sys.getprofile(), previous)
        report = native.snapshot()
        self.assertTrue(report["valid"], report)
        self.assertEqual(native.pending, [])
        self.assertEqual(sum(row["raised"] for row in report["sites"]), 1)
        self.assertEqual(len(primary), 1)
        self.assertTrue({"connect", "execute", "executescript", "commit", "fetchone", "rollback", "close"}
                        <= {row["method"] for row in report["sites"]})
        close = next(row for row in report["sites"] if row["method"] == "close")
        self.assertEqual(close["caller"], "guarded_close")
        self.assertGreater(close["line"], 0)
        encoded = json.dumps([report, collector.snapshot()])
        for value in ("private_table", "credential-canary", str(ROOT), "private invalid SQL"):
            self.assertNotIn(value, encoded)

    def test_exact_prior_profiler_restore_and_original_exception(self):
        failure = RuntimeError("private primary failure")
        def operation():
            raise failure
        native, _ = self.capture(operation)
        previous = sys.getprofile()
        sentinel = lambda frame, event, arg: None
        try:
            sys.setprofile(sentinel)
            with self.assertRaises(RuntimeError) as raised:
                with native.installed():
                    operation()
            self.assertIs(raised.exception, failure)
            self.assertIs(sys.getprofile(), sentinel)
        finally:
            sys.setprofile(previous)

    def test_real_native_close_exception_is_not_a_completed_lifetime(self):
        class Guarded(sqlite3.Connection):
            def close(self):
                return super().close()
        ready, finish = threading.Event(), threading.Event()
        connections, errors = [], []
        connect = lambda *args, **kwargs: connections[0]
        fake_app = SimpleNamespace(library=SimpleNamespace(connect_catalog=connect),
                                   catalog_guard=SimpleNamespace(connect_catalog=connect))
        def owner():
            connection = sqlite3.connect(":memory:", factory=Guarded)
            connections.append(connection); ready.set()
            finish.wait(5)
            connection.close()
        def operation():
            try:
                fake_app.library.connect_catalog().close()  # Real wrong-thread native close failure.
            except sqlite3.ProgrammingError as error:
                errors.append(error)
                raise
        native, _ = self.capture(operation, **{"catalog_guard.close": Guarded.close})
        previous = sys.getprofile()
        worker = threading.Thread(target=owner); worker.start()
        try:
            self.assertTrue(ready.wait(5))
            with self.assertRaises(sqlite3.ProgrammingError) as raised, patch.dict(sys.modules, {"app": fake_app}), \
                    self.module.catalog_profiles(native):
                operation()
            self.assertIs(raised.exception, errors[0])
        finally:
            finish.set(); worker.join(5)
        self.assertIs(sys.getprofile(), previous)
        self.assertIs(fake_app.library.connect_catalog, connect)
        self.assertEqual(native.snapshot()["close_failures"], 1)
        self.assertEqual(native.snapshot()["incomplete_lifetimes"], 1)
        self.assertFalse(native.snapshot()["valid"])

    def test_current_thread_only_and_unlisted_caller_ignored(self):
        def operation():
            connection = sqlite3.connect(":memory:")
            connection.close()
        native, _ = self.capture(operation)
        with native.installed():
            worker = threading.Thread(target=operation)
            worker.start(); worker.join(5)
            self.assertFalse(worker.is_alive())
            other = sqlite3.connect(":memory:"); other.close()
        self.assertEqual(native.snapshot()["sites"], [])
        self.assertTrue(native.snapshot()["valid"])

    def test_observer_failure_does_not_replace_native_error(self):
        failure = []
        def operation():
            connection = sqlite3.connect(":memory:")
            try:
                connection.execute("invalid SQL")
            except sqlite3.OperationalError as error:
                failure.append(error)
                raise
            finally:
                connection.close()
        native, collector = self.capture(operation)
        with patch.object(collector, "metric", side_effect=RuntimeError("private observer failure")):
            with self.assertRaises(sqlite3.OperationalError) as raised, native.installed():
                operation()
        self.assertIs(raised.exception, failure[0])
        self.assertFalse(native.snapshot()["valid"])
        self.assertEqual(native.pending, [])

    def test_aggregate_and_existing_rings_remain_bounded(self):
        def operation():
            connection = sqlite3.connect(":memory:")
            for _ in range(300):
                connection.execute("SELECT 1").fetchone()
            connection.close()
        native, collector = self.capture(operation)
        with patch.object(self.diagnostics, "SLOW_SECONDS", 0), native.installed():
            operation()
        report = collector.snapshot()
        self.assertTrue(native.snapshot()["valid"])
        self.assertLessEqual(len(native.snapshot()["sites"]), 64)
        self.assertEqual(len(report["recent_events"]), 256)
        self.assertGreater(report["dropped"]["recent_events"], 0)
        self.assertEqual(report["bounds"]["metrics"], 32)
        self.assertEqual(report["totals"]["catalog_native"]["count"], 602)
        with patch.object(native, "MAX_SITES", 0), native.installed():
            native.sites.clear()
            operation()
        self.assertFalse(native.snapshot()["valid"])
        self.assertGreater(native.dropped["sites"], 0)

    def test_restored_bytes_and_bad_marker_cannot_delete_owned_data(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); data = root / "data"; seed = root / "seed"
            data.mkdir(); seed.mkdir()
            marker = {"synthetic": True}
            for directory in (data, seed):
                (directory / "progressive-slo-fixture.json").write_text(json.dumps(marker))
                (directory / "synthetic.txt").write_text("original")
            (data / "synthetic.txt").write_text("changed")
            self.module.restore_dataset(seed, data, marker)
            self.assertEqual(self.module.digest_tree(seed), self.module.digest_tree(data))
            (data / "progressive-slo-fixture.json").write_text("{}")
            with self.assertRaises(ValueError):
                self.module.restore_dataset(seed, data, marker)
            self.assertTrue((data / "synthetic.txt").is_file())

    def test_wrong_receiver_or_pending_overflow_fails_closed(self):
        def operation():
            pass
        frame = SimpleNamespace(f_code=operation.__code__, f_lineno=1)
        first, second = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
        try:
            for overflow in (False, True):
                native, _ = self.capture(operation)
                if overflow:
                    native.MAX_PENDING = 0
                with native.installed():
                    native(frame, "c_call", first.execute)
                    native(frame, "c_return", second.execute)
                self.assertFalse(native.snapshot()["valid"])
                self.assertEqual(native.pending, [])
                self.assertEqual(native.dropped["pending" if overflow else "unmatched"], 1)
        finally:
            first.close(); second.close()

    def test_profiled_primary_failure_retains_arm_and_restores_profiler(self):
        failure = ValueError("private update failure")
        fake_storage = SimpleNamespace(update_task=lambda *args, **kwargs: (_ for _ in ()).throw(failure))
        fake_app = SimpleNamespace(storage=fake_storage)
        collector = self.diagnostics.Collector()
        diagnostics = SimpleNamespace(install=lambda app, stack: collector)
        result = {}; previous = sys.getprofile()
        with patch.dict(sys.modules, {"app": fake_app}), patch.object(self.module, "source_callers", return_value={}), \
                patch.object(self.module, "catalog_profiles", return_value=ExitStack()):
            with self.assertRaises(ValueError) as raised:
                self.module.measure(None, diagnostics, "a" * 12, True, result)
        self.assertIs(raised.exception, failure)
        self.assertIs(sys.getprofile(), previous)
        self.assertIn("wall_s", result)
        self.assertTrue(result["native"]["valid"])
        self.assertNotIn("private update failure", json.dumps(result))
        with patch.dict(sys.modules, {"app": fake_app}), patch.object(self.module, "source_callers", return_value={}), \
                patch.object(self.module, "catalog_profiles", return_value=ExitStack()), \
                patch.object(collector, "snapshot", side_effect=RuntimeError("private snapshot failure")):
            with self.assertRaises(ValueError) as raised:
                self.module.measure(None, diagnostics, "a" * 12, True, result)
        self.assertIs(raised.exception, failure)
        self.assertTrue(result["diagnostic_snapshot_failed"])

    def test_report_preserves_redacted_failure_before_exit(self):
        fixture = load("catalog_failure_fixture", "scripts/progressive-slo-fixture.py")
        failure = PermissionError(13, "secret credential /private/path")
        def configure(*args):
            raise failure
        fixture.configure_fixture = configure
        def dependencies(name, relative):
            return fixture if relative.endswith("progressive-slo-fixture.py") else SimpleNamespace()
        with tempfile.TemporaryDirectory() as name, patch.object(self.module, "load", side_effect=dependencies):
            with self.assertRaises(PermissionError) as raised:
                self.module.run(Path(name))
            self.assertIs(raised.exception, failure)
            report = json.loads((Path(name) / "report.json").read_text())
        self.assertFalse(report["acceptance"])
        self.assertFalse(report["completed"])
        self.assertEqual(report["failure"][0]["category"], "PermissionError")
        self.assertNotIn("secret credential", json.dumps(report))
        self.assertNotIn("/private/path", json.dumps(report))
        original_write = Path.write_text
        writes = []
        def write(path, value, **kwargs):
            writes.append(value)
            if len(writes) > 1:
                raise OSError("private persistence failure")
            return original_write(path, value, **kwargs)
        with tempfile.TemporaryDirectory() as name, patch.object(self.module, "load", side_effect=dependencies), \
                patch.object(fixture, "callback_exception_chain", side_effect=RuntimeError("private formatter failure")), \
                patch.object(Path, "write_text", write):
            with self.assertRaises(PermissionError) as raised:
                self.module.run(Path(name))
        self.assertIs(raised.exception, failure)
        self.assertTrue(json.loads(writes[-1])["failure_formatting_failed"])

    def test_real_lifetimes_restore_aliases_profiler_and_nested_connections(self):
        helpers = load("catalog_lifetime_helpers", "scripts/tests/test_progressive_slo_contention.py")
        helpers.ProgressiveSloContentionFixtureTests().run_isolated(r'''
from app import library, catalog_guard
module = load('catalog_lifetime_diagnostic', 'progressive-slo-catalog-diagnostic.py')
original, close = catalog_guard.connect_catalog, catalog_guard._GuardedConnection.close
sentinel = lambda frame, event, arg: None
previous = sys.getprofile()
try:
    sys.setprofile(sentinel)
    with ExitStack() as observer:
        collector = diagnostics.install(app, observer)
        native = module.NativeCalls(collector, module.source_callers())
        with module.catalog_profiles(native):
            first, _ = library._connect()
            second, _ = library._connect()
            assert type(first) is type(second) is catalog_guard._GuardedConnection
            assert first.close.__func__ is second.close.__func__ is close
            assert sys.getprofile() is native
            first.close()  # Deliberately close out of nesting order.
            assert sys.getprofile() is native
            second.close()
            assert sys.getprofile() is sentinel
            for target, name in ((catalog_guard, 'orphaned_sidecars'), (library, '_ensure_schema')):
                failure = PermissionError('private catalog fault')
                with patch.object(target, name, side_effect=failure):
                    try:
                        library._connect()
                    except PermissionError as raised:
                        assert raised is failure
                    else:
                        raise AssertionError('Injected failure was lost')
                assert sys.getprofile() is sentinel
            assert native.snapshot()['valid'], native.snapshot()
        assert catalog_guard.connect_catalog is library.connect_catalog is original
        assert catalog_guard._GuardedConnection.close is close
        assert sys.getprofile() is sentinel
finally:
    sys.setprofile(previous)
assert_restored()
''')


if __name__ == "__main__":
    unittest.main()
