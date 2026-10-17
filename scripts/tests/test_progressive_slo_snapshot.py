"""Coordinated fixture reads of the actual progressive outline publication."""
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
import queue
import tempfile
import threading
from unittest.mock import patch

root = Path.cwd()
spec = importlib.util.spec_from_file_location('reference_fixture', root / 'scripts/progressive-slo-fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
with tempfile.TemporaryDirectory(prefix='learnnote-outline-read-') as temporary, ExitStack() as stack:
    data = Path(temporary)
    app, _ = fixture.configure_fixture(root, data, stack)
    from app import storage, pipeline_progress
    from app.models import ActiveVideoInfo, TranscriptResult, TranscriptSegment
    task = storage.create_task('page_text', 'SLO reference 60m outline-read', mode='subtitle_only')
    snapshot = next(route.endpoint for route in app.routes if getattr(route, 'path', '') == '/_fixture/tasks/{task_id}')
    # TEST_BODY
'''


class ProgressiveSloSnapshotTests(unittest.TestCase):
    def run_isolated(self, body):
        code = BOOTSTRAP.replace('    # TEST_BODY', '\n'.join('    ' + line for line in body.splitlines()))
        env = {key: value for key, value in os.environ.items() if key.upper() in
               {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'LANG', 'LC_ALL'}}
        env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=30, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_outline_read_waits_for_actual_writer_after_prior_task_reads(self):
        self.run_isolated(r'''
segments = [TranscriptSegment(start=start, end=start + 30,
    text=f'Reference lesson source statement at {start} seconds.') for start in range(0, 3600, 30)]
transcript = TranscriptResult(segments=segments, full_text='\n'.join(item.text for item in segments))
source = storage.write_json(task.id, 'transcript.json', transcript.model_dump(mode='json'))
subtitle = storage.task_dir(task.id) / 'subtitle.srt'
subtitle.write_text(transcript.full_text, encoding='utf-8')
storage.update_task(task.id, transcript_path=str(source), subtitle_path=str(subtitle), active_video=ActiveVideoInfo(duration=3600))
short = TranscriptResult(segments=segments[:10], full_text='\n'.join(item.text for item in segments[:10]))
pipeline_progress.write_progressive_draft(task.id, task.title, short, expected_attempt_id=None)
source_bytes, subtitle_bytes = source.read_bytes(), subtitle.read_bytes()
outline = storage.task_dir(task.id) / 'draft_sections.json'
reader_paused, writer_entered, release_writer, reader_reached = (threading.Event() for _ in range(4))
outcomes, failures = queue.Queue(), queue.Queue()
real_lock, original_dir, original_atomic, original_open = storage._lock, storage.task_dir, storage.atomic_write_text, Path.open
waiting = []

class ObservedLock:
    def __enter__(self):
        if threading.current_thread().name == 'snapshot-reader' and writer_entered.is_set() and not release_writer.is_set():
            waiting.append('outline lock'); reader_reached.set()
        return real_lock.__enter__()
    def __exit__(self, *args):
        return real_lock.__exit__(*args)

def pause_after_task_reads(task_id):
    path = original_dir(task_id)
    if threading.current_thread().name == 'snapshot-reader' and not reader_paused.is_set():
        reader_paused.set()
        assert writer_entered.wait(5), 'Writer did not enter its actual write_json lock'
    return path

def paused_publication(path, text):
    if path == outline:
        assert real_lock._is_owned(), 'Actual write_json must own the shared storage lock'
        writer_entered.set()
        assert release_writer.wait(5), 'Publication was not released'
    return original_atomic(path, text)

def reject_unserialized_open(path, *args, **kwargs):
    if path == outline and threading.current_thread().name == 'snapshot-reader' and writer_entered.is_set() and not release_writer.is_set():
        # Model the observed Windows sharing failure only at the conflicting
        # open. The real writer, atomic replace, reader and lock remain in use.
        reader_reached.set()
        raise PermissionError('Coordinated outline publication is still active')
    return original_open(path, *args, **kwargs)

def read():
    try:
        outcomes.put(snapshot(task.id))
    except BaseException as error:
        failures.put(error)

def write():
    try:
        pipeline_progress.write_progressive_draft(task.id, task.title, transcript, expected_attempt_id=None)
    except BaseException as error:
        failures.put(error)

reader = threading.Thread(target=read, name='snapshot-reader')
writer = threading.Thread(target=write, name='outline-writer')
with patch.object(storage, '_lock', ObservedLock()), patch.object(storage, 'task_dir', pause_after_task_reads), \
     patch.object(storage, 'atomic_write_text', paused_publication), patch.object(Path, 'open', reject_unserialized_open):
    try:
        reader.start(); assert reader_paused.wait(5), 'Reader did not pass its initial task reads'
        writer.start(); assert writer_entered.wait(5)
        assert reader_reached.wait(5), 'Reader did not reach the publication boundary'
        if not failures.empty():
            raise failures.get_nowait()
        assert waiting == ['outline lock'], 'Outline read bypassed the shared writer lock'
        assert outcomes.empty() and failures.empty(), 'Reader completed while publication was held'
    finally:
        release_writer.set()
        for thread in (reader, writer):
            if thread.ident is not None:
                thread.join(5)
                assert not thread.is_alive(), 'Owned test thread did not drain'
if not failures.empty():
    raise failures.get_nowait()
result = outcomes.get_nowait()
assert result['source_coverage'] == dict(duration=3600, cue_count=120, first_start=0, last_end=3600,
    reference_cues_complete=True, section_count=12, final_section_end=3600)
assert source.read_bytes() == source_bytes and subtitle.read_bytes() == subtitle_bytes
assert len(storage.read_json(task.id, 'draft_sections.json')['sections']) == 12
assert not list(outline.parent.glob('.draft_sections.json.*.tmp'))
''')

    def test_absent_outline_is_optional_but_invalid_data_and_permission_errors_still_fail(self):
        self.run_isolated(r'''
outline = storage.task_dir(task.id) / 'draft_sections.json'
assert 'section_count' not in snapshot(task.id)['source_coverage']
storage.write_json(task.id, 'draft_sections.json', {'sections': [{'end': 3600}]})
assert snapshot(task.id)['source_coverage'] == {'section_count': 1, 'final_section_end': 3600}
for value, exception in [('not JSON', json.JSONDecodeError), ('null', TypeError), ('{}', KeyError)]:
    outline.write_text(value, encoding='utf-8')
    try:
        snapshot(task.id)
    except exception:
        pass
    else:
        raise AssertionError('Malformed outline was treated as absent: ' + value)
failure = PermissionError('Persistent outline access failure')
original_open = Path.open
def deny(path, *args, **kwargs):
    if path == outline:
        raise failure
    return original_open(path, *args, **kwargs)
with patch.object(Path, 'open', deny):
    try:
        snapshot(task.id)
    except PermissionError as error:
        assert error is failure
    else:
        raise AssertionError('Persistent read failure was suppressed')
''')
