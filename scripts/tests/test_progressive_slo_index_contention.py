"""Offline contracts for fixture-only index subspans and reader diagnostics.

All application imports use the existing disposable, network-blocked fixture
bootstrap. These tests do not collect a product SLO or access user task data.
"""
import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "progressive_slo_contention_contract_helpers",
    ROOT / "scripts/tests/test_progressive_slo_contention.py",
)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)


class ProgressiveSloIndexEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _helpers.load_collector()

    def test_only_exact_methods_paths_and_task_editions_get_envelopes(self):
        collector = self.module.Collector()
        task_id = "a" * 12
        selected = "/api/tasks/" + task_id
        edition = "/api/tasks/editions/task/" + task_id
        fixture = "/_fixture/tasks/" + task_id
        allowed = [
            ("GET", "/api/tasks", ""),
            ("GET", selected, task_id),
            ("POST", selected + "/start", task_id),
            ("POST", selected + "/cancel", task_id),
            ("GET", edition, task_id),
            ("GET", edition + "/personal-review", task_id),
            ("GET", fixture, task_id),
            ("POST", fixture + "/visible", task_id),
        ]
        denied = [
            ("POST", "/api/tasks"), ("HEAD", "/api/tasks"),
            ("POST", selected), ("DELETE", selected), ("get", selected),
            ("GET", selected + "/start"), ("GET", selected + "/cancel"),
            ("GET", selected + "/retry"), ("POST", selected + "/retry"),
            ("GET", selected + "/"), ("GET", selected + "0"),
            ("GET", "/api/tasks/" + "A" * 12),
            ("GET", "/prefix" + selected), ("GET", selected + "/details"),
            ("PUT", edition), ("POST", edition + "/personal-review"),
            ("GET", edition + "/exports/md"),
            ("GET", edition.replace("/task/", "/material/")),
            ("GET", edition.replace("/task/", "/Task/")),
            ("GET", edition + "/personal-review/"),
            ("GET", edition + "/personal-review/extra"),
            ("GET", edition.replace(task_id, "b" * 11)),
            ("POST", fixture), ("GET", fixture + "/visible"),
            ("GET", fixture + "/release"), ("POST", fixture + "/release"),
            ("POST", fixture + "/visible/"), ("GET", "/_fixture/state"),
            ("GET", "/_fixture/contention"),
        ]
        calls = []
        marker = object()

        async def receive():
            return marker

        async def send(message):
            self.assertIs(message, marker)

        async def downstream(scope, incoming, outgoing):
            self.assertIs(incoming, receive)
            self.assertIs(outgoing, send)
            self.assertIs(await incoming(), marker)
            await outgoing(marker)
            calls.append((scope, collector.identity()))

        envelope = self.module.RequestEnvelope(downstream, collector)

        async def exercise():
            for method, path, task in allowed:
                scope = {"type": "http", "method": method, "path": path,
                         "query_string": b"unrecorded=private-query"}
                await envelope(scope, receive, send)
                self.assertIs(calls[-1][0], scope)
                self.assertEqual(calls[-1][1]["name"], "http_request")
                self.assertEqual(calls[-1][1]["task_id"], task)
                self.assertEqual(collector.identity()["id"], 0)
            for method, path in denied:
                scope = {"type": "http", "method": method, "path": path}
                await envelope(scope, receive, send)
                self.assertIs(calls[-1][0], scope)
                self.assertEqual(calls[-1][1]["id"], 0, (method, path))
            for kind in ("websocket", "lifespan"):
                scope = {"type": kind, "method": "GET", "path": selected}
                await envelope(scope, receive, send)
                self.assertIs(calls[-1][0], scope)
                self.assertEqual(calls[-1][1]["id"], 0)

        asyncio.run(exercise())
        report = collector.snapshot()
        self.assertEqual(len(report["operations"]), len(allowed))
        self.assertTrue(all(row["thread_cpu_s"] is None for row in report["operations"]))
        self.assertTrue(all(row["parent_id"] is None for row in report["operations"]))
        self.assertEqual(report["active"], [])
        self.assertNotIn("private-query", str(report))

    def test_envelope_failure_keeps_exception_and_restores_identity(self):
        collector = self.module.Collector()
        failure = RuntimeError("synthetic ASGI failure")

        async def downstream(scope, receive, send):
            raise failure

        envelope = self.module.RequestEnvelope(downstream, collector)
        with self.assertRaises(RuntimeError) as raised:
            asyncio.run(envelope({"type": "http", "method": "GET",
                                  "path": "/_fixture/tasks/" + "a" * 12}, None, None))
        self.assertIs(raised.exception, failure)
        self.assertEqual(collector.identity()["id"], 0)
        report = collector.snapshot()
        self.assertEqual(report["active"], [])
        self.assertTrue(report["operations"][0]["raised"])
        self.assertIsNone(report["operations"][0]["thread_cpu_s"])

    def test_twenty_eight_labels_fit_unchanged_default_budgets(self):
        labels = {
            "task_lock_wait", "task_lock_hold", "state_lease_enter", "update_task",
            "manifest_read_validate", "task_json_read_decode", "atomic_file_write",
            "library_index_sqlite", "list_reconcile", "duration_file_read_decode",
            "remaining_history", "whole_history", "transcript_read_decode",
            "list_tasks", "task_projection", "list_handler", "selected_handler",
            "index_artifact_text", "index_connect_schema", "index_note_evidence",
            "index_transcript_evidence", "index_replace_evidence", "edition_handler",
            "personal_review_handler", "fixture_state_handler", "visible_handler",
            "catalog_lock_wait", "catalog_lock_hold",
        }
        self.assertEqual(len(labels), 28)
        collector = self.module.Collector()
        with collector.operation("update_task", task_id="a" * 12):
            for label in labels:
                with collector.span(label):
                    pass
        report = collector.snapshot()
        self.assertEqual(report["bounds"], {
            "operations": 256, "recent_events": 256, "slow_events": 64,
            "active": 128, "metrics": 32,
            "slow_events_by_kind": {"lock_wait": 16, "lock_hold": 16,
                                    "lease_wait": 8, "boundary": 24},
        })
        self.assertEqual(set(report["totals"]), labels)
        self.assertEqual(set(report["operations"][0]["metrics"]), labels)
        self.assertEqual(report["dropped"]["metrics"], 0)
        self.assertEqual(collector.operations.maxlen, 256)
        self.assertEqual(collector.events.maxlen, 256)
        self.assertEqual(set(collector.slow), {"lock_wait", "lock_hold", "lease_wait", "boundary"})


class ProgressiveSloIndexFixtureTests(unittest.TestCase):
    # Reuse the isolated runner by composition, not inheritance: discovering
    # this file must not silently duplicate the original test class's tests.
    BASE_BOOTSTRAP = _helpers.ProgressiveSloContentionFixtureTests.BOOTSTRAP.replace(
        "    modules = (storage,", "    from app import library\n    modules = (library, storage,")
    BOOTSTRAP = BASE_BOOTSTRAP.replace(
        "    routes = [(route.dependant, route.dependant.call) for route in app.routes if hasattr(route, 'dependant')]",
        r"""
    def fixture_routes():
        result = list(app.routes)
        for branch in app.routes:
            if getattr(branch, 'original_router', None) is main.notes_router:
                result.extend(branch.effective_candidates())
        return result

    # Warm only the notes branch. Effective dependants, rather than the original
    # router's definitions, are the call sites used by current FastAPI dispatch.
    routes = [(route.dependant, route.dependant.call) for route in fixture_routes()
              if hasattr(route, 'dependant')]
    notes_caches = [(branch, name, getattr(branch, name)) for branch in app.routes
                    if getattr(branch, 'original_router', None) is main.notes_router
                    for name in ('_effective_candidates', '_effective_candidates_version',
                                 '_effective_low_priority_routes', '_effective_low_priority_routes_version')]
""").replace(
        "        assert_runtime_unchanged()",
        "        assert_runtime_unchanged()\n        for branch, name, value in notes_caches:\n            assert getattr(branch, name) is value, name")
    run_isolated = _helpers.ProgressiveSloContentionFixtureTests.run_isolated

    def test_index_aliases_preserve_arguments_signatures_results_and_errors(self):
        self.run_isolated(r'''
import inspect
labels = {
    '_read_text': 'index_artifact_text', '_connect': 'index_connect_schema',
    'record_to_evidence': 'index_note_evidence',
    'transcript_evidence': 'index_transcript_evidence',
    'replace_task_evidence': 'index_replace_evidence',
}
connection = sqlite3.connect(':memory:')
results = {name: object() for name in labels}
results['_connect'] = (connection, True)
failures, calls = {}, []
primary, extra, option, task_root = object(), object(), object(), object()

def make_original(name):
    def original(value, *args, option=None, **kwargs):
        calls.append((name, value, args, option, kwargs, diagnostics._index_active.get()))
        if name in failures:
            raise failures[name]
        return results[name]
    return original

originals = {name: make_original(name) for name in labels}
index_calls = []
def original_index(record, *, task_root=None):
    index_calls.append((record, task_root))
    assert diagnostics._index_active.get() is True
    return driver()

try:
    with ExitStack() as doubles:
        for name, original in originals.items():
            doubles.enter_context(patch.object(library, name, original))
        doubles.enter_context(patch.object(storage, 'index_task', original_index))
        with ExitStack() as profile_stack:
            collector = diagnostics.install(app, profile_stack)
            assert inspect.signature(storage.index_task) == inspect.signature(original_index)
            assert storage.index_task.__wrapped__ is original_index
            for name, label in labels.items():
                call = getattr(library, name)
                assert inspect.signature(call) == inspect.signature(originals[name])
                assert inspect.unwrap(call) is originals[name]
                args = (primary, extra)
                kwargs = {'option': option, 'private': 'synthetic-private-source'}
                # An unrelated operation must not activate indexing subspans.
                with collector.operation('update_task', task_id='a' * 12):
                    assert call(*args, **kwargs) is results[name]
                assert label not in collector.snapshot()['totals']
                assert calls[-1][-1] is False
                driver = lambda: call(*args, **kwargs)
                returned = storage.index_task(record=primary, task_root=task_root)
                assert returned is results[name]
                if name == '_connect':
                    assert returned[0] is connection
                    assert connection.execute('SELECT 1').fetchone() == (1,)
                assert index_calls[-1] == (primary, task_root)
                recorded = calls[-1]
                assert recorded[1] is primary and recorded[2][0] is extra
                assert recorded[3] is option
                assert recorded[4] == {'private': 'synthetic-private-source'}
                assert recorded[-1] is True
                assert diagnostics._index_active.get() is False
                assert collector.snapshot()['totals'][label]['count'] == 1
                failure = LookupError('synthetic-private-exception-' + name)
                failures[name] = failure
                for invocation, expected_count in ((driver, 1),
                        (lambda: storage.index_task(primary, task_root=task_root), 2)):
                    try:
                        invocation()
                    except LookupError as error:
                        assert error is failure
                    else:
                        raise AssertionError('Original exception was swallowed')
                    assert collector.snapshot()['totals'][label]['count'] == expected_count
                    assert diagnostics._index_active.get() is False
                    assert diagnostics._section.get() == 'unlabelled'
                del failures[name]
            report = collector.snapshot()
            assert 'synthetic-private' not in json.dumps(report)
            assert report['totals']['library_index_sqlite']['count'] == 10
            assert_runtime_unchanged()
        for name, original in originals.items():
            assert getattr(library, name) is original
        assert storage.index_task is original_index
    assert_restored()
finally:
    connection.close()
''')

    def test_real_index_work_uses_all_five_subspans_and_restores_library_aliases(self):
        self.run_isolated(r'''
import inspect
record = storage.create_task('page_text', 'Synthetic index contract', mode='page_text')
task_root = storage.TASK_DIR / record.id
note = task_root / 'note.md'
transcript = task_root / 'transcript.json'
note.write_text('Synthetic note evidence', encoding='utf-8')
transcript.write_text(json.dumps({'segments': [{'start': 0, 'end': 1, 'text': 'Synthetic transcript'}]}), encoding='utf-8')
record.note_path = str(note)
record.transcript_path = str(transcript)
originals = {name: getattr(library, name) for name in (
    '_read_text', '_connect', 'record_to_evidence', 'transcript_evidence', 'replace_task_evidence')}
original_index = storage.index_task
with ExitStack() as profile_stack:
    collector = diagnostics.install(app, profile_stack)
    for name, original in originals.items():
        assert inspect.signature(getattr(library, name)) == inspect.signature(original)
    assert inspect.signature(storage.index_task) == inspect.signature(original_index)
    with collector.operation('update_task', task_id=record.id):
        assert storage.index_task(record, task_root=task_root) is True
    report = collector.snapshot()
    expected = {'index_artifact_text': 2, 'index_connect_schema': 1,
                'index_note_evidence': 1, 'index_transcript_evidence': 1,
                'index_replace_evidence': 1, 'library_index_sqlite': 1}
    for label, count in expected.items():
        assert report['totals'][label]['count'] == count, (label, report['totals'])
        assert report['operations'][0]['metrics'][label]['count'] == count
    assert diagnostics._index_active.get() is False
    # The unchanged direct library binding is not the storage index boundary.
    assert library.index_task is original_index
    assert library.index_task(record, task_root=task_root) is True
    # Global catalog ownership includes direct library callers outside the
    # storage-only index span. The five index subspans remain scoped as before.
    after = collector.snapshot()['totals']
    for label in expected:
        assert after[label] == report['totals'][label]
    assert after['catalog_lock_hold']['count'] == 2 * report['totals']['catalog_lock_hold']['count']
    assert 'Synthetic note evidence' not in json.dumps(report)
    assert 'Synthetic transcript' not in json.dumps(report)
    assert str(task_root) not in json.dumps(report)
    assert_runtime_unchanged()
assert_restored()
''')

    def test_nested_and_failing_indexes_restore_context_and_thread_isolation(self):
        self.run_isolated(r'''
import queue
failure = ValueError('nested synthetic failure')
result, contexts, child_results = object(), [], queue.Queue()
def read_text(value, limit=1000000):
    contexts.append((value, diagnostics._index_active.get()))
    return value

def original_index(record, *, task_root=None):
    assert diagnostics._index_active.get() is True
    library._read_text(record)
    if record == 'inner':
        raise failure
    if record == 'outer':
        try:
            storage.index_task('inner')
        except ValueError as error:
            assert error is failure
        else:
            raise AssertionError('Nested exception was swallowed')
        assert diagnostics._index_active.get() is True
        assert diagnostics._section.get() == 'library_index_sqlite'
        library._read_text('after-inner')
        def unrelated_thread():
            child_results.put(library._read_text('other-thread'))
        thread = threading.Thread(target=unrelated_thread)
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
        assert child_results.get_nowait() == 'other-thread'
    return result

with patch.object(library, '_read_text', read_text), patch.object(storage, 'index_task', original_index):
    with ExitStack() as profile_stack:
        collector = diagnostics.install(app, profile_stack)
        assert diagnostics._index_active.get() is False
        assert storage.index_task('outer') is result
        assert diagnostics._index_active.get() is False
        assert diagnostics._section.get() == 'unlabelled'
        library._read_text('outside')
        assert collector.snapshot()['totals']['index_artifact_text']['count'] == 3
        try:
            storage.index_task('inner')
        except ValueError as error:
            assert error is failure
        else:
            raise AssertionError('Top-level exception was swallowed')
        assert diagnostics._index_active.get() is False
        token = diagnostics._index_active.set(True)
        try:
            assert storage.index_task('preexisting') is result
            assert diagnostics._index_active.get() is True
        finally:
            diagnostics._index_active.reset(token)
        assert diagnostics._index_active.get() is False
        assert contexts == [('outer', True), ('inner', True), ('after-inner', True),
                            ('other-thread', False), ('outside', False),
                            ('inner', True), ('preexisting', True)]
        assert collector.snapshot()['totals']['index_artifact_text']['count'] == 5
        assert collector.snapshot()['totals']['library_index_sqlite']['count'] == 4
        assert_runtime_unchanged()
assert_restored()
''')

    def test_sync_drift_rejects_every_new_target_and_self_restores_partial_setup(self):
        self.run_isolated(r'''
import functools
async def coroutine(*args, **kwargs):
    return None

def generator(*args, **kwargs):
    yield None

async def async_generator(*args, **kwargs):
    yield None

def decorated(function):
    @functools.wraps(function)
    def call(*args, **kwargs):
        return function(*args, **kwargs)
    return call

route_keys = {
    ('GET', '/api/tasks/editions/{kind}/{source_id}'),
    ('GET', '/api/tasks/editions/{kind}/{source_id}/personal-review'),
    ('GET', '/_fixture/tasks/{task_id}'),
    ('POST', '/_fixture/tasks/{task_id}/visible'),
}
targets = [(library, name) for name in ('_read_text', '_connect', 'record_to_evidence',
                                      'transcript_evidence', 'replace_task_evidence')]
targets.append((storage, 'index_task'))
targets.extend((route.dependant, 'call') for route in fixture_routes()
               if any((method, getattr(route, 'path', '')) in route_keys
                      for method in getattr(route, 'methods', ())))
assert len(targets) == 10
for target, name in targets:
    for shape in (coroutine, generator, async_generator):
        for replacement in (shape, decorated(shape)):
            with ExitStack() as profile_stack:
                with patch.object(target, name, replacement):
                    try:
                        diagnostics.install(app, profile_stack)
                    except TypeError as error:
                        assert 'ordinary synchronous' in str(error)
                    else:
                        raise AssertionError('Non-synchronous target was accepted')
                # The outer caller stack is still open; install must self-unwind.
                assert_restored()
                assert diagnostics._index_active.get() is False
            assert_restored()
''')

    def test_missing_routes_and_late_setup_failure_restore_every_new_alias(self):
        self.run_isolated(r'''
reader_paths = {
    '/api/tasks/editions/{kind}/{source_id}',
    '/api/tasks/editions/{kind}/{source_id}/personal-review',
    '/_fixture/tasks/{task_id}', '/_fixture/tasks/{task_id}/visible',
}
for path in reader_paths:
    method = 'POST' if path.endswith('/visible') else 'GET'
    missing = [route for route in fixture_routes() if getattr(route, 'path', '') == path
               and method in getattr(route, 'methods', ())]
    assert len(missing) == 1
    with ExitStack() as profile_stack:
        with patch.object(missing[0], 'methods', set()):
            try:
                diagnostics.install(app, profile_stack)
            except AssertionError as error:
                assert 'incomplete' in str(error)
            else:
                raise AssertionError('Missing required reader route was accepted')
        assert_restored()
failure = RuntimeError('synthetic late observer setup failure')
with ExitStack() as profile_stack:
    with patch.object(app, 'add_middleware', side_effect=failure):
        try:
            diagnostics.install(app, profile_stack)
        except RuntimeError as error:
            assert error is failure
        else:
            raise AssertionError('Setup failure was swallowed')
    assert_restored()
    assert diagnostics._index_active.get() is False
assert_restored()
''')

    def test_reader_handlers_keep_signatures_results_errors_and_task_extraction(self):
        self.run_isolated(r'''
import inspect
route_labels = {
    ('GET', '/api/tasks/editions/{kind}/{source_id}'): 'edition_handler',
    ('GET', '/api/tasks/editions/{kind}/{source_id}/personal-review'): 'personal_review_handler',
    ('GET', '/_fixture/tasks/{task_id}'): 'fixture_state_handler',
    ('POST', '/_fixture/tasks/{task_id}/visible'): 'visible_handler',
}
reader_routes = [(route, label) for route in fixture_routes() for key, label in route_labels.items()
                 if getattr(route, 'path', '') == key[1] and key[0] in getattr(route, 'methods', ())]
assert len(reader_routes) == 4
result, failures, calls = object(), {}, []
def make_handler(label, edition):
    def invoke(kind, task_id):
        calls.append((label, kind, task_id))
        if label in failures:
            raise failures[label]
        return result
    if edition:
        def handler(kind, source_id):
            return invoke(kind, source_id)
    else:
        def handler(task_id):
            return invoke('task', task_id)
    return handler

with ExitStack() as doubles:
    originals = {}
    for route, label in reader_routes:
        original = make_handler(label, 'editions' in route.path)
        originals[label] = original
        doubles.enter_context(patch.object(route.dependant, 'call', original))
    before_routes = [(route, route.dependant.call, route.endpoint) for route in fixture_routes() if hasattr(route, 'dependant')]
    with ExitStack() as profile_stack:
        collector = diagnostics.install(app, profile_stack)
        changed_keys = set(route_labels) | {('GET', '/api/tasks'), ('GET', '/api/tasks/{task_id}')}
        for route, original, endpoint in before_routes:
            selected = any((method, route.path) in changed_keys for method in route.methods)
            assert (route.dependant.call is not original) is selected, route.path
            assert route.endpoint is endpoint
        for route, label in reader_routes:
            handler = route.dependant.call
            assert inspect.signature(handler) == inspect.signature(originals[label])
            assert handler.__wrapped__ is originals[label]
            if 'editions' in route.path:
                invocations = [lambda: handler('task', 'a' * 12),
                               lambda: handler(kind='task', source_id='b' * 12),
                               lambda: handler('task', source_id='c' * 12)]
                for call in (lambda: handler('material', 'd' * 12),
                             lambda: handler(kind='Task', source_id='e' * 12)):
                    assert call() is result
                assert label not in collector.snapshot()['totals']
                failed = lambda: handler(kind='task', source_id='f' * 12)
            else:
                invocations = [lambda: handler('a' * 12),
                               lambda: handler(task_id='b' * 12),
                               lambda: handler('c' * 12)]
                failed = lambda: handler(task_id='f' * 12)
            for call in invocations:
                assert call() is result
            failure = RuntimeError('private handler failure ' + label)
            failures[label] = failure
            try:
                failed()
            except RuntimeError as error:
                assert error is failure
            else:
                raise AssertionError('Handler failure was swallowed')
            del failures[label]
            rows = [row for row in collector.snapshot()['operations'] if row['name'] == label]
            assert [row['task_id'] for row in rows] == [letter * 12 for letter in 'abcf']
            assert [row['raised'] for row in rows] == [False, False, False, True]
            assert all(row['parent_id'] is None for row in rows)
            assert all(row['metrics'][label]['count'] == 1 for row in rows)
            assert all(row['thread_cpu_s'] is not None for row in rows)
            assert collector.identity()['id'] == 0
        assert 'private handler failure' not in json.dumps(collector.snapshot())
        assert_runtime_unchanged()
    for route, label in reader_routes:
        assert route.dependant.call is originals[label]
assert_restored()
''')

    def test_actual_edition_and_review_handlers_keep_loopback_http_responses(self):
        self.run_isolated(r'''
import socket
import time
from urllib.request import urlopen
import uvicorn
record = storage.create_task('page_text', 'Synthetic loopback reader contract', mode='page_text')
root_path = storage.TASK_DIR / record.id
note = root_path / 'note.md'
note_text = '# Synthetic fixture note\n\nThis evidence stays in the disposable fixture.\n'
note.write_text(note_text, encoding='utf-8')
storage.update_task(record.id, status='success', phase='completed', progress=100, note_path=str(note))
paths = {'edition_handler': '/api/tasks/editions/task/' + record.id,
         'personal_review_handler': '/api/tasks/editions/task/' + record.id + '/personal-review'}

def serve_readers():
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
                    raise AssertionError('Synthetic loopback server did not start')
                time.sleep(.01)
            responses = {}
            for label, path in paths.items():
                with urlopen(origin + path, timeout=10) as response:
                    assert response.status == 200
                    responses[label] = json.load(response)
            return responses
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive(), 'Loopback server did not stop before observer cleanup'

# A stopped disabled server leaves a built middleware stack. Scope that ordinary
# server side effect so the enabled installation still starts from the same state.
with patch.object(app, 'middleware_stack', None):
    baseline = serve_readers()
assert baseline['edition_handler']['text'] == note_text
assert baseline['edition_handler']['edited'] is False
assert baseline['personal_review_handler']['status'] == 'unmarked'
with ExitStack() as profile_stack:
    collector = diagnostics.install(app, profile_stack)
    measured = serve_readers()
    assert measured == baseline
    report = collector.snapshot()
    envelopes = {row['id']: row for row in report['operations'] if row['name'] == 'http_request'}
    handlers = [row for row in report['operations'] if row['name'] in paths]
    assert len(envelopes) == len(handlers) == 2, report['operations']
    assert {row['name'] for row in handlers} == set(paths)
    assert {row['parent_id'] for row in handlers} == set(envelopes)
    for row in handlers:
        parent = envelopes[row['parent_id']]
        assert row['task_id'] == parent['task_id'] == record.id
        assert parent['parent_id'] is None
        assert row['thread_cpu_s'] is not None and parent['thread_cpu_s'] is None
        assert row['metrics'][row['name']]['count'] == 1
        assert parent['start_s'] <= row['start_s'] <= row['end_s'] <= parent['end_s']
    assert note_text not in json.dumps(report)
    assert str(root_path) not in json.dumps(report)
    assert report['active'] == []
    assert_runtime_unchanged()
assert_restored()
''')

    def test_cold_notes_cache_restores_exact_identity_after_cleanup_and_failure(self):
        # Keep this bootstrap cold: the other tests deliberately inspect and
        # prewarm the effective routes before installing the observer.
        with patch.object(self, "BOOTSTRAP", self.BASE_BOOTSTRAP):
            self.run_isolated(r'''
cache_names = ('_effective_candidates', '_effective_candidates_version',
               '_effective_low_priority_routes', '_effective_low_priority_routes_version')
branches = [route for route in app.routes if hasattr(route, 'original_router')]
notes = [branch for branch in branches if branch.original_router is main.notes_router]
if notes:
    assert len(notes) == 1
    branch = notes[0]
    baselines = [(route, name, getattr(route, name)) for route in branches for name in cache_names]
    assert branch._effective_candidates == []
    assert branch._effective_candidates_version is None
    reader_paths = {'/api/tasks/editions/{kind}/{source_id}',
                    '/api/tasks/editions/{kind}/{source_id}/personal-review'}
    with ExitStack() as profile_stack:
        diagnostics.install(app, profile_stack)
        restored_calls = [(route.dependant, route.dependant.call.__wrapped__)
                          for route in branch._effective_candidates
                          if getattr(route, 'path', '') in reader_paths
                          and 'GET' in getattr(route, 'methods', ())]
        assert len(restored_calls) == 2
        for route, name, value in baselines:
            if route is not branch or 'low_priority' in name:
                assert getattr(route, name) is value, name
    for dependant, original in restored_calls:
        assert dependant.call is original
    for route, name, value in baselines:
        assert getattr(route, name) is value, name
    assert_restored()
    failure = RuntimeError('synthetic cold-cache setup failure')
    with ExitStack() as profile_stack:
        with patch.object(app, 'add_middleware', side_effect=failure):
            try:
                diagnostics.install(app, profile_stack)
            except RuntimeError as error:
                assert error is failure
            else:
                raise AssertionError('Cold setup failure was swallowed')
        for route, name, value in baselines:
            assert getattr(route, name) is value, name
        assert_restored()
else:
    # Older FastAPI stores flat routes and has no included-router cache to edit.
    with ExitStack() as profile_stack:
        diagnostics.install(app, profile_stack)
    assert_restored()
''')

    def test_real_asgi_reader_handlers_link_local_ids_without_claiming_cdp_identity(self):
        self.run_isolated(r'''
import asyncio
route_labels = {
    ('GET', '/api/tasks/editions/{kind}/{source_id}'): 'edition_handler',
    ('GET', '/api/tasks/editions/{kind}/{source_id}/personal-review'): 'personal_review_handler',
    ('GET', '/_fixture/tasks/{task_id}'): 'fixture_state_handler',
    ('POST', '/_fixture/tasks/{task_id}/visible'): 'visible_handler',
}
readers = [(route, key, label) for route in fixture_routes() for key, label in route_labels.items()
           if getattr(route, 'path', '') == key[1] and key[0] in getattr(route, 'methods', ())]
def edition(kind: str, source_id: str):
    assert storage.index_task(source_id) == 'synthetic artifact'
    return {'task_id': source_id}
def task(task_id: str, generation: str = ""):
    assert storage.index_task(task_id) == 'synthetic artifact'
    return {'task_id': task_id}
def index(record, *, task_root=None):
    return library._read_text(record)
def read_text(value, limit=1000000):
    return 'synthetic artifact'

with ExitStack() as doubles:
    doubles.enter_context(patch.object(storage, 'index_task', index))
    doubles.enter_context(patch.object(library, '_read_text', read_text))
    for route, key, label in readers:
        doubles.enter_context(patch.object(route.dependant, 'call', edition if 'editions' in route.path else task))
    with ExitStack() as profile_stack:
        collector = diagnostics.install(app, profile_stack)
        async def request(method, path):
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message):
                messages.append(message)
            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                     'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                     'root_path': '', 'query_string': b'',
                     'headers': [(b'x-cdp-request-id', b'private-browser-request-id')],
                     'server': ('127.0.0.1', 80), 'client': ('127.0.0.1', 12345)}
            await app(scope, receive, send)
            assert messages[0]['type'] == 'http.response.start'
            assert messages[0]['status'] == 200, messages
            payload = json.loads(b''.join(row.get('body', b'') for row in messages))
            assert payload == {'task_id': 'a' * 12}
        async def exercise():
            for route, key, label in readers:
                path = key[1].replace('{kind}', 'task').replace('{source_id}', 'a' * 12).replace('{task_id}', 'a' * 12)
                await request(key[0], path)
                assert collector.identity()['id'] == 0
        asyncio.run(exercise())
        report = collector.snapshot()
        assert len(report['operations']) == 8, report['operations']
        envelopes = {row['id']: row for row in report['operations'] if row['name'] == 'http_request'}
        handlers = [row for row in report['operations'] if row['name'] in route_labels.values()]
        assert len(envelopes) == len(handlers) == 4
        assert len({row['id'] for row in report['operations']}) == 8
        assert {row['parent_id'] for row in handlers} == set(envelopes)
        for row in handlers:
            parent = envelopes[row['parent_id']]
            assert row['task_id'] == parent['task_id'] == 'a' * 12
            assert row['thread_id'] != parent['thread_id']
            assert row['thread_cpu_s'] is not None and parent['thread_cpu_s'] is None
            assert parent['parent_id'] is None
            assert parent['start_s'] <= row['start_s'] <= row['end_s'] <= parent['end_s']
            assert row['metrics']['index_artifact_text']['count'] == 1
            assert row['metrics']['library_index_sqlite']['count'] == 1
        # These are collector-local operation IDs propagated through FastAPI's
        # worker context. A CDP ID is not propagated or inferred from task/timing.
        assert all(type(row['id']) is int for row in report['operations'])
        assert 'private-browser-request-id' not in json.dumps(report)
        assert report['active'] == []
        assert_runtime_unchanged()
assert_restored()
''')


if __name__ == "__main__":
    unittest.main()
