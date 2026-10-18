"""Offline reset boundaries; retained pre-fix proof establishes susceptibility only."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = r'''
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import threading
from unittest.mock import patch
import sys

root = Path.cwd()
spec = importlib.util.spec_from_file_location('opinion_fixture', root / 'scripts/selected-opinion-qa-fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
with tempfile.TemporaryDirectory(prefix='learnnote-opinion-reset-') as temporary, ExitStack() as stack:
    data = Path(temporary)
    app, metadata = fixture.configure_fixture(root, data, stack)
    from app import storage, main, community, model_connections, selected_opinion_qa
    endpoints = {route.path: route.endpoint for route in app.routes if getattr(route, 'path', '').startswith('/_fixture/')}
    reset, mutate, state = (endpoints['/_fixture/' + name] for name in ('reset', 'mutate', 'state'))
    task_id, ids = metadata['task_id'], metadata['item_ids']
    manifest = storage.task_file(task_id)
    caption = storage.task_dir(task_id) / 'transcript.json'
    before_task = storage.get_task(task_id).model_dump(mode='json')
    before_items = community.selected_community_items(task_id, ids)
    before_caption = caption.read_bytes()
    before_model = model_connections.selected_connection_status()
    def snapshot():
        return {p.relative_to(data).as_posix(): (p.stat().st_dev, p.stat().st_ino, p.read_bytes())
                for p in data.rglob('*') if p.is_file()}
    before_files = snapshot()
    def assert_untouched():
        current = snapshot()
        mutable = {'community.sqlite3', 'model-connection.json', caption.relative_to(data).as_posix()}
        for name, value in before_files.items():
            if name not in mutable:
                assert current[name] == value, name
        assert current['community.sqlite3'][:2] == before_files['community.sqlite3'][:2]
        assert storage.get_task(task_id).model_dump(mode='json') == before_task
    exec(sys.argv[1])
'''

READER_CHECK = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const original = fs.readFileSync('web/desk.js', 'utf8').replace(/\r\n/g, '\n');
async function check(representation) {
  const source = representation.replace(/\r\n/g, '\n');
  function block(start, end) {
    const first = source.indexOf(start), last = source.indexOf(end, first);
    assert(first >= 0 && last > first, 'Actual source boundaries missing');
    return source.slice(first, last);
  }
  const elements = Object.fromEntries(['annotationText', 'reading', 'welcome', 'noteActions', 'breadcrumb'].map(id => [id, {}]));
  elements.reading.hidden = false; elements.welcome.hidden = true;
  const selected = { ...input.before, kind: 'task' }, events = [], hashes = [];
  const context = {
    state: { selected, items: [selected], epoch: 7, selectedRevision: 0, editing: false, reading: {} },
    api: async route => route === '/api/tasks' ? input.tasks : route.startsWith('/api/library/') ? { materials: [] } : {},
    $: id => elements[id], syncStatus: { hidden: true },
    claimMapVersion: () => 'unchanged-current-version', localMediaSource: () => null, editionRequest: 0,
    syncTaskEventStreams() {}, drawList() {}, closeSource() {}, renderStatus() {}, guard: () => true,
    history: { replaceState: (_, __, url) => hashes.push(url) }, location: { pathname: '/' },
    window: { dispatchEvent: event => events.push(event) },
    Event: class { constructor(type) { this.type = type; } },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
    document: { querySelector: () => null },
  };
  vm.runInNewContext([
    block('function showHome(', 'async function navigateBack('),
    block('async function refreshLibrary(', 'function selectedSnapshot('),
    block('function selectedSnapshot(', 'function refreshSelectedTask('),
  ].join('\n'), context);
  assert.equal(context.selectedSnapshotCurrent(context.selectedSnapshot()), true);
  await context.refreshLibrary();
  assert.equal(context.state.selected.id, input.before.id);
  assert.equal(elements.reading.hidden, false);
  assert.equal(elements.welcome.hidden, true);
  assert.deepEqual(hashes, []);
  assert(!events.some(event => event.type === 'learnnote:navigation'));
}
(async () => { await check(original); await check(original.replace(/\n/g, '\r\n')); })()
  .catch(error => { console.error(error); process.exitCode = 1; });
'''


class CommunityQuestionResetTests(unittest.TestCase):
    def run_isolated(self, case):
        env = {key: value for key, value in os.environ.items() if key.upper() in
               {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'LANG', 'LC_ALL'}}
        env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-c', BOOTSTRAP, case], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=30, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_known_mutations_restore_exact_baseline_without_replacing_owned_files(self):
        self.run_isolated(r'''
for action in ('delete_opinion', 'disable', 'source_change', 'model_change'):
    mutate({'action': action, 'item_id': ids[0]})
    generation = community.community_preview_generation()
    selected_opinion_qa._previews['synthetic-expired'] = {}
    reset()
    assert community.selected_community_items(task_id, ids) == before_items
    assert community.community_settings()['enabled'] is True
    assert community.community_preview_generation() == generation
    assert caption.read_bytes() == before_caption
    assert model_connections.selected_connection_status() == before_model
    assert not selected_opinion_qa._previews
    assert state()['calls'] == [] and state()['mutations'] == []
    assert state()['persistence']['original_artifacts_unchanged'] is True
    assert state()['persistence']['no_history_or_run_files'] is True
    assert state()['persistence']['no_mixed_output_persisted'] is True
    assert_untouched()
''')

    def test_atomic_reset_blocks_actual_task_list_without_omission_or_home_navigation(self):
        self.run_isolated(r'''
mutate({'action': 'source_change'})
changed_caption = caption.read_bytes()
replacing, release, reader_entered = threading.Event(), threading.Event(), threading.Event()
original_replace, original_get = Path.replace, storage.get_task
failures, results = [], []
def held_replace(path, target):
    if Path(target) == caption:
        assert path != caption
        assert json.loads(path.read_text(encoding='utf-8')) == json.loads(before_caption)
        replacing.set()
        assert release.wait(10), 'Reset replacement barrier not released'
    return original_replace(path, target)
def tracked_get(task):
    if threading.current_thread().name == 'actual-task-reader':
        reader_entered.set()
    return original_get(task)
def run_reset():
    try: reset()
    except BaseException as error: failures.append(error)
def read_tasks():
    try: results.append(main.api_list_tasks())
    except BaseException as error: failures.append(error)
with patch.object(Path, 'replace', held_replace), patch.object(storage, 'get_task', tracked_get):
    worker = threading.Thread(target=run_reset)
    reader = threading.Thread(target=read_tasks, name='actual-task-reader')
    worker.start()
    try:
        assert replacing.wait(10), 'Reset did not reach atomic replacement'
        assert manifest.read_bytes() == before_files[manifest.relative_to(data).as_posix()][2]
        assert caption.read_bytes() == changed_caption
        reader.start()
        assert reader_entered.wait(10), 'Actual reader did not reach storage lock'
        assert not results, 'Task reader escaped held reset transaction'
    finally:
        release.set()
        worker.join(10)
        if reader.ident is not None: reader.join(10)
assert not worker.is_alive() and not reader.is_alive()
assert not failures, failures
assert [row['id'] for row in results[0]['tasks']] == [task_id]
assert caption.read_bytes() == before_caption
assert_untouched()
''' + "\nresult = subprocess.run(['node', '-e', " + repr(READER_CHECK) + "], input=json.dumps({'before': before_task, 'tasks': results[0]}), text=True, capture_output=True, timeout=10)\nassert result.returncode == 0, result.stdout + result.stderr\n")

    def test_atomic_source_mutation_never_truncates_original_transcript(self):
        self.run_isolated(r'''
original_replace = Path.replace
seen = []
def inspect_replace(path, target):
    if Path(target) == caption:
        assert path != caption and caption.read_bytes() == before_caption
        assert json.loads(path.read_text(encoding='utf-8'))['segments'][0]['text'].endswith(' 已改变')
        seen.append(True)
    return original_replace(path, target)
with patch.object(Path, 'replace', inspect_replace):
    mutate({'action': 'source_change'})
assert seen == [True]
assert_untouched()
''')

    def test_unknown_opinion_rows_source_and_task_scope_are_rejected(self):
        for mutation in ('extra', 'source', 'task'):
            with self.subTest(mutation=mutation):
                self.run_isolated('mutation = ' + repr(mutation) + r'''
with community._lock:
    connection = community._connect()
    try:
        with connection:
            if mutation == 'extra':
                connection.execute("INSERT INTO community_context_items SELECT 'unexpected-id', schema_version, task_id, kind, text, timestamp_seconds, author_label, source_uri, 'unexpected-fingerprint', created_at FROM community_context_items LIMIT 1")
            else:
                column = 'source_uri' if mutation == 'source' else 'task_id'
                connection.execute(f"UPDATE community_context_items SET {column} = ? WHERE item_id = ?", ('unexpected-scope', ids[0]))
    finally: connection.close()
before = snapshot()
try: reset()
except ValueError as error: assert 'row/source/task scope' in str(error)
else: raise AssertionError('Unexpected opinion scope was silently restored')
assert snapshot() == before
''')

    def test_unknown_task_control_transcript_and_note_changes_are_not_erased(self):
        for mutation in ('task', 'transcript', 'note'):
            with self.subTest(mutation=mutation):
                self.run_isolated('mutation = ' + repr(mutation) + r'''
if mutation == 'task':
    payload = json.loads(manifest.read_text(encoding='utf-8'))
    payload['control_generation'] = 'a' * 32 if payload['control_generation'] != 'a' * 32 else 'b' * 32
    storage.atomic_write_text(manifest, json.dumps(payload))
elif mutation == 'transcript':
    payload = json.loads(caption.read_text(encoding='utf-8'))
    payload['source'] = 'unexpected-source'
    storage.write_json(task_id, 'transcript.json', payload)
else:
    (storage.task_dir(task_id) / 'note.md').write_text('Unexpected note', encoding='utf-8')
before = snapshot()
try: reset()
except ValueError as error: assert 'Unexpected fixture' in str(error)
else: raise AssertionError('Unexpected task artifact was silently restored')
assert snapshot() == before
''')

    def test_reset_preserves_new_personal_files_and_does_not_mask_forbidden_output(self):
        self.run_isolated(r'''
personal = storage.task_dir(task_id) / 'annotations.json'
personal.write_text('[{"text":"Synthetic personal note"}]', encoding='utf-8')
history = storage.task_dir(task_id) / 'qa_history.json'
history.write_text('["Mixed answer"]', encoding='utf-8')
extra = {p: (p.stat().st_ino, p.read_bytes()) for p in (personal, history)}
reset()
assert all((p.stat().st_ino, p.read_bytes()) == value for p, value in extra.items())
assert state()['persistence']['no_history_or_run_files'] is False
assert state()['persistence']['no_mixed_output_persisted'] is False
assert_untouched()
''')

    def test_busy_reset_rejects_without_mutating_or_clearing_admitted_request(self):
        self.run_isolated(r'''
from fastapi import HTTPException
selected_opinion_qa._previews['synthetic-admitted'] = {'used': True}
selected_opinion_qa._inflight.add(('synthetic-scope', task_id))
before = snapshot()
try: reset()
except HTTPException as error: assert error.status_code == 409
else: raise AssertionError('Reset accepted an admitted request')
assert snapshot() == before
assert 'synthetic-admitted' in selected_opinion_qa._previews
assert ('synthetic-scope', task_id) in selected_opinion_qa._inflight
''')


if __name__ == '__main__':
    unittest.main()
