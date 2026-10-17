"""Offline fixed-cap catalog ownership contracts for the synthetic observer."""
import importlib.util
from pathlib import Path
import queue
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('catalog_contention_helpers', ROOT / 'scripts/tests/test_progressive_slo_contention.py')
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)


class CatalogLockAccountingTests(unittest.TestCase):
    def setUp(self):
        self.module = _helpers.load_collector()
        self.collector = self.module.Collector()
        self.task = self.module.MeasuredTaskLock(threading.RLock(), self.collector)
        self.catalog = self.module.MeasuredTaskLock(threading.RLock(), self.collector, 'catalog_lock')

    def test_fixed_names_separate_depth_and_snapshot_namespaces(self):
        with self.assertRaises(ValueError):
            self.module.MeasuredTaskLock(threading.RLock(), self.collector, 'private-name')
        self.assertIs(self.collector.lock, self.task)
        self.assertIs(self.collector.catalog_lock, self.catalog)
        with patch.object(self.module, 'SLOW_SECONDS', 0):
            with self.task:
                task_owner = self.collector.snapshot()['lock_owner']
                with self.catalog:
                    owner = self.collector.snapshot()['catalog_lock_owner']
                    self.assertEqual(owner['hold_id'], task_owner['hold_id'])
                    self.assertNotEqual(owner['lock_name'], task_owner['lock_name'])
                    self.assertEqual(owner['task_owner']['hold_id'], task_owner['hold_id'])
                    with self.catalog:
                        self.assertEqual(self.collector.snapshot()['catalog_lock_owner'], owner)
                    self.assertEqual(self.collector.snapshot()['catalog_lock_owner'], owner)
                self.assertIsNone(self.collector.snapshot()['catalog_lock_owner'])
                self.assertEqual(self.collector.snapshot()['lock_owner'], task_owner)
        snapshot = self.collector.snapshot()
        self.assertIsNone(snapshot['lock_owner'])
        self.assertEqual(snapshot['totals']['task_lock_hold']['count'], 1)
        self.assertEqual(snapshot['totals']['catalog_lock_hold']['count'], 1)
        snapshot['slow_events'][0]['name'] = 'changed'
        self.assertNotIn('changed', str(self.collector.snapshot()))

    def test_catalog_native_timeout_nonblocking_and_errors_remain_transparent(self):
        lock = self.catalog
        with lock:
            outcomes = queue.Queue()
            def waiter():
                outcomes.put((lock.acquire(False), lock.acquire(timeout=.001)))
                try:
                    lock.release()
                except RuntimeError:
                    outcomes.put('wrong owner')
            thread = threading.Thread(target=waiter)
            thread.start(); thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes.get_nowait(), (False, False))
            self.assertEqual(outcomes.get_nowait(), 'wrong owner')
            self.assertTrue(lock.acquire(blocking=False)); lock.release()
        with self.assertRaises(RuntimeError):
            lock.release()
        for args, kwargs in (((False, .01), {}), ((), {'timeout': -2}), ((), {'unknown': True})):
            with self.assertRaises((TypeError, ValueError)):
                lock.acquire(*args, **kwargs)
        with self.assertRaisesRegex(LookupError, 'body'):
            with lock:
                raise LookupError('body')
        self.assertIsNone(self.collector.snapshot()['catalog_lock_owner'])

    def test_catalog_owner_task_waiter_reader_chain_has_distinct_provenance(self):
        catalog_ready = threading.Event(); catalog_waiting = threading.Event()
        task_waiting = threading.Event(); release_catalog = threading.Event()
        errors = queue.Queue()
        class ObservedRealLock:
            def __init__(self, waiter_name, signal):
                self.real = threading.RLock(); self.waiter_name = waiter_name; self.signal = signal
            def acquire(self, *args, **kwargs):
                if threading.current_thread().name == self.waiter_name:
                    self.signal.set()
                return self.real.acquire(*args, **kwargs)
            def release(self):
                return self.real.release()
        task = self.module.MeasuredTaskLock(ObservedRealLock('reader', task_waiting), self.collector)
        catalog = self.module.MeasuredTaskLock(ObservedRealLock('task-holder', catalog_waiting), self.collector, 'catalog_lock')
        def run(body):
            try:
                body()
            except BaseException as error:
                errors.put(error)
        def owner():
            with self.collector.operation('catalog_reader'):
                token = self.module._catalog_origin.set('library.list_materials')
                try:
                    with catalog:
                        catalog_ready.set()
                        if not release_catalog.wait(3):
                            raise AssertionError('catalog release not signalled')
                finally:
                    self.module._catalog_origin.reset(token)
        def writer():
            with self.collector.operation('update_task', 'a' * 12):
                with task:
                    with catalog:
                        pass
        def reader():
            with self.collector.operation('selected_handler', 'a' * 12):
                with task:
                    pass
        threads = [threading.Thread(target=lambda:run(owner), name='catalog-owner'),
                   threading.Thread(target=lambda:run(writer), name='task-holder'),
                   threading.Thread(target=lambda:run(reader), name='reader')]
        with patch.object(self.module, 'SLOW_SECONDS', 0):
            try:
                threads[0].start(); self.assertTrue(catalog_ready.wait(2))
                threads[1].start(); self.assertTrue(catalog_waiting.wait(2))
                threads[2].start(); self.assertTrue(task_waiting.wait(2))
                snapshot = self.collector.snapshot()
                self.assertEqual(snapshot['catalog_lock_owner']['operation']['name'], 'catalog_reader')
                self.assertEqual(snapshot['catalog_lock_owner']['catalog_origin'], 'library.list_materials')
                self.assertIsNone(snapshot['catalog_lock_owner']['task_owner'])
                self.assertEqual(snapshot['lock_owner']['operation']['name'], 'update_task')
            finally:
                release_catalog.set()
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(3); self.assertFalse(thread.is_alive())
        self.assertTrue(errors.empty(), list(errors.queue))
        events = self.collector.snapshot()['slow_events']
        catalog_wait = next(e for e in events if e['kind']=='lock_wait' and e['name']=='catalog_lock' and e['operation']['name']=='update_task')
        task_wait = next(e for e in events if e['kind']=='lock_wait' and e['name']=='task_lock' and e['operation']['name']=='selected_handler')
        self.assertEqual(catalog_wait['owner_at_entry']['operation']['name'], 'catalog_reader')
        self.assertEqual(task_wait['owner_at_entry']['operation']['name'], 'update_task')
        self.assertEqual(catalog_wait['task_owner_at_entry']['hold_id'], task_wait['owner_at_entry']['hold_id'])
        self.assertNotEqual(catalog_wait['owner_at_entry']['thread_id'], task_wait['owner_at_entry']['thread_id'])
        self.assertIsNone(self.collector.snapshot()['catalog_lock_owner'])
        self.assertIsNone(self.collector.snapshot()['lock_owner'])

    def test_both_locks_share_existing_kind_caps_and_transparent_drops(self):
        c = self.module.Collector(max_operations=3, max_events=4, max_slow_events=8)
        task = self.module.MeasuredTaskLock(threading.RLock(), c)
        catalog = self.module.MeasuredTaskLock(threading.RLock(), c, 'catalog_lock')
        with patch.object(self.module, 'SLOW_SECONDS', 0):
            for _ in range(20):
                with task:
                    with catalog:
                        pass
        snapshot = c.snapshot()
        self.assertEqual(snapshot['bounds']['slow_events'], 8)
        self.assertEqual(snapshot['bounds']['slow_events_by_kind'], {'lock_wait':2,'lock_hold':2,'lease_wait':1,'boundary':3})
        self.assertEqual(len(snapshot['recent_events']), 4)
        self.assertEqual(len(snapshot['slow_events']), 4)
        self.assertEqual(snapshot['dropped']['slow_events'], 76)
        self.assertEqual(snapshot['dropped']['slow_events_by_kind']['lock_wait'], 38)
        self.assertEqual(snapshot['dropped']['slow_events_by_kind']['lock_hold'], 38)
        self.assertEqual(snapshot['totals']['catalog_lock_hold']['count'], 20)
        self.assertEqual(snapshot['totals']['task_lock_hold']['count'], 20)
        self.assertEqual(snapshot['dropped']['metrics'], 0)


class CatalogFixtureTests(unittest.TestCase):
    BOOTSTRAP = _helpers.ProgressiveSloContentionFixtureTests.BOOTSTRAP.replace(
        '    modules = (storage,', '    from app import library, knowledge, catalog_guard\n    modules = (library, knowledge, storage,')
    run_isolated = _helpers.ProgressiveSloContentionFixtureTests.run_isolated

    def test_real_connections_outside_index_keep_identity_close_and_caller_labels(self):
        self.run_isolated(r'''
real_catalog_lock = catalog_guard._mutex
with ExitStack() as profile_stack:
    collector = diagnostics.install(app, profile_stack)
    assert catalog_guard._mutex.real is real_catalog_lock
    with patch.object(diagnostics, 'SLOW_SECONDS', 0):
        assert library.list_materials() == []
        assert knowledge.evidence_for_task('a' * 12) == []
        rows = [row for row in collector.snapshot()['slow_events'] if row['kind']=='lock_hold' and row['name']=='catalog_lock']
        assert {'library.list_materials','knowledge.evidence_for_task'} <= {row['owner']['catalog_origin'] for row in rows}
        assert all(row['owner']['operation']['id'] == 0 for row in rows)
        assert all(row['owner']['task_owner'] is None for row in rows)
        # The original guarded connection is returned, with no wrapper/proxy.
        outer, _ = library._connect()
        assert type(outer) is catalog_guard._GuardedConnection
        first = collector.snapshot()['catalog_lock_owner']
        assert first['catalog_origin'] is None  # Test body is not a known product caller.
        inner = knowledge._connect()
        assert type(inner) is catalog_guard._GuardedConnection
        assert collector.snapshot()['catalog_lock_owner'] == first
        inner.close()
        assert collector.snapshot()['catalog_lock_owner'] == first
        outer.close()
        assert collector.snapshot()['catalog_lock_owner'] is None
        assert diagnostics._catalog_origin.get() is None
    assert_runtime_unchanged()
assert catalog_guard._mutex is real_catalog_lock
assert_restored()
''')

    def test_direct_outer_guard_and_imported_alias_keep_outer_owner_and_reset_on_failure(self):
        self.run_isolated(r'''
real_catalog_lock = catalog_guard._mutex
with ExitStack() as profile_stack:
    collector = diagnostics.install(app, profile_stack)
    for guard in (catalog_guard.catalog_guard, library.catalog_guard):
        with guard(library.DATA_DIR):
            first = collector.snapshot()['catalog_lock_owner']
            assert first['critical'] == 'catalog_guard'
            assert first['catalog_origin'] is None
            assert first['operation']['id'] == 0
            assert knowledge.evidence_for_task('a' * 12) == []
            assert collector.snapshot()['catalog_lock_owner'] == first
        assert collector.snapshot()['catalog_lock_owner'] is None
    failure = RuntimeError('synthetic probe failure')
    with patch.object(catalog_guard, 'validate_catalog_version', side_effect=failure):
        try:
            knowledge.evidence_for_task('a' * 12)
        except RuntimeError as error:
            assert error is failure
        else:
            raise AssertionError('Catalog probe failure swallowed')
    assert diagnostics._catalog_origin.get() is None
    assert collector.snapshot()['catalog_lock_owner'] is None
    assert knowledge.evidence_for_task('a' * 12) == []
assert catalog_guard._mutex is real_catalog_lock
assert_restored()
''')

    def test_index_owner_preserves_index_section_and_fixed_knowledge_origin(self):
        self.run_isolated(r'''
record = storage.create_task('page_text', 'Synthetic ownership contract', mode='page_text')
real_catalog_lock = catalog_guard._mutex
owners = []
original = knowledge._fts_available
def inspect_owner(connection):
    owners.append(collector.snapshot()['catalog_lock_owner'])
    return original(connection)
with ExitStack() as profile_stack:
    collector = diagnostics.install(app, profile_stack)
    with patch.object(knowledge, '_fts_available', side_effect=inspect_owner):
        storage.update_task(record.id, phase='summarizing')
    owner = owners[-1]
    assert owner['catalog_origin'] == 'knowledge.replace_task_evidence'
    assert owner['section'] == 'index_replace_evidence'
    assert owner['operation']['name'] == 'update_task'
    assert owner['operation']['task_id'] == record.id
    assert owner['task_owner']['lock_name'] == 'task_lock'
    assert diagnostics._catalog_origin.get() is None
    assert collector.snapshot()['catalog_lock_owner'] is None
    assert collector.snapshot()['lock_owner'] is None
assert catalog_guard._mutex is real_catalog_lock
assert_restored()
''')

    def test_failed_evidence_write_rolls_back_and_closes_original_connection(self):
        self.run_isolated(r'''
from app.models import SourceEvidence
failure = sqlite3.OperationalError('synthetic evidence write failure')
connections = []
def fail_write(connection, *args, **kwargs):
    connections.append(connection)
    assert collector.snapshot()['catalog_lock_owner']['catalog_origin'] == 'knowledge.add_evidence'
    raise failure
with ExitStack() as profile_stack:
    collector = diagnostics.install(app, profile_stack)
    with patch.object(knowledge, '_write_evidence', side_effect=fail_write):
        try:
            knowledge.add_evidence(SourceEvidence(evidence_id='fixture', text='Synthetic text'))
        except sqlite3.OperationalError as error:
            assert error is failure
        else:
            raise AssertionError('Write failure swallowed')
    assert len(connections) == 1
    assert type(connections[0]) is catalog_guard._GuardedConnection
    try:
        connections[0].execute('SELECT 1')
    except sqlite3.ProgrammingError:
        pass
    else:
        raise AssertionError('Original connection not closed after failure')
    assert collector.snapshot()['catalog_lock_owner'] is None
    assert diagnostics._catalog_origin.get() is None
assert_restored()
''')

    def test_setup_and_runtime_failure_restore_mutex_connectors_and_scoped_labels(self):
        self.run_isolated(r'''
real_catalog_lock = catalog_guard._mutex
original_library, original_knowledge = library._connect, knowledge._connect
failure = RuntimeError('synthetic setup failure')
with ExitStack() as profile_stack:
    with patch.object(app, 'add_middleware', side_effect=failure):
        try:
            diagnostics.install(app, profile_stack)
        except RuntimeError as error:
            assert error is failure
        else:
            raise AssertionError('Setup failure swallowed')
    assert catalog_guard._mutex is real_catalog_lock
    assert library._connect is original_library and knowledge._connect is original_knowledge
    assert diagnostics._catalog_origin.get() is None
    assert_restored()
try:
    with ExitStack() as profile_stack:
        collector = diagnostics.install(app, profile_stack)
        with catalog_guard.catalog_guard(library.DATA_DIR):
            raise failure
except RuntimeError as error:
    assert error is failure
else:
    raise AssertionError('Runtime failure swallowed')
assert catalog_guard._mutex is real_catalog_lock
assert library._connect is original_library and knowledge._connect is original_knowledge
assert diagnostics._catalog_origin.get() is None
assert_restored()
''')
