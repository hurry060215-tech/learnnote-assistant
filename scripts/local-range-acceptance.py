"""Real synthetic local range pipeline and fresh-process recovery acceptance.

FFmpeg, subtitle ingestion, queue/lifespan, clipping and exports are real.
Only summary generation is a deterministic fixture; no ASR/provider is used.
This does not claim browser selector, native player or real-site acceptance.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fingerprint(path):
    path = Path(path)
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'mtime_ns': path.stat().st_mtime_ns}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def wait_for_completed_intent(read_intent, expected, timeout=10):
    """Task success is persisted before the worker commits its journal state."""
    deadline = time.monotonic() + timeout
    while True:
        intent = read_intent()
        assert intent is not None, 'Durable intent disappeared'
        for field in ('sequence', 'generation'):
            assert intent[field] == expected[field], f'Durable intent {field} changed'
        if intent['state'] == 'done':
            return intent
        assert intent['state'] in {'queued', 'running', 'recovering'}, intent
        assert time.monotonic() < deadline, f'Durable intent did not finalize: {intent}'
        time.sleep(.05)


def worker(output, mode):
    sys.path.insert(0, str(ROOT / 'backend'))
    load_script('interrupted-task-reliability').install_network_guard()
    from fastapi.testclient import TestClient
    from app import main, processor
    from app.config import DATA_DIR
    from app.models import TaskOptions
    from app.storage import create_task, get_task, task_dir, read_json, list_tasks_snapshot
    from app.queue_journal import read_queue_job
    from app.task_queue import recover_processing

    options = TaskOptions(visual_understanding=True, max_frame_count=60, frame_interval=5,
                          low_resource_mode=True, llm_api_key='')

    def summary(title, transcript, grids, settings, *args, **kwargs):
        if mode == 'start' and '片段' in title:
            # This is after the actual clip and evidence pipeline, before note commit.
            write(output / 'ready.json', {'pid': os.getpid()})
            while True:
                time.sleep(.1)
        return '# Synthetic range summary\n\n' + '\n'.join(s.text for s in transcript.segments), 'offline-fixture', '', []
    processor.summarize_with_diagnostics = summary

    def wait_task(task_id):
        deadline = time.monotonic() + 90
        while True:
            task = get_task(task_id)
            if task.status in {'success', 'failed', 'cancelled'}:
                assert task.status == 'success', task.model_dump_json()
                return task
            assert time.monotonic() < deadline, task.model_dump_json()
            time.sleep(.05)

    if mode == 'start':
        media = DATA_DIR / 'synthetic.mp4'
        load_script('long-video-reliability').generate_synthetic_media(media, 20)
        subtitle = DATA_DIR / 'synthetic.srt'
        subtitle.write_text('\n'.join(f'{i+1}\n00:00:{i*5:02},000 --> 00:00:{(i+1)*5:02},000\nEVIDENCE_{i+1}\n' for i in range(4)), encoding='utf-8')
        source = create_task('local', 'Synthetic full source', options=options, mode='local')
        processor.process_local_video_task(source.id, media, source.title, options, subtitle_path=subtitle, subtitle_source='synthetic-fixture')
        source = wait_task(source.id)
        original = {key: fingerprint(getattr(source, key)) for key in ('media_path', 'transcript_path', 'note_path')}
        with TestClient(main.app) as client:
            # TestClient waits for response background callbacks; the real HTTP
            # response is already sent before that wait. Submit concurrently so
            # the parent can kill the worker while that callback is in flight.
            import threading
            submission = {}
            def submit():
                try:
                    submission['response'] = client.post(f'/api/tasks/{source.id}/learn-range', json={'start': 5, 'end': 15, 'options': options.model_dump(mode='json')})
                except Exception as error:
                    submission['error'] = repr(error)
            threading.Thread(target=submit, daemon=True).start()
            deadline = time.monotonic() + 90
            while not (output / 'ready.json').exists():
                assert not submission, str(submission)
                assert time.monotonic() < deadline
                time.sleep(.05)
            matches = [task for task in list_tasks_snapshot() if task.source_task_id == source.id]
            assert len(matches) == 1
            selected = matches[0]
            selected_id = selected.id
            assert selected.checkpoint == 'visual_ready', selected.checkpoint
            clip = task_dir(selected_id) / 'selected-range.mp4'
            write(output / 'interrupted.json', {'source_id': source.id, 'range_id': selected_id,
                'source_artifacts': original, 'clip': fingerprint(clip),
                'generation': selected.control_generation, 'intent': read_queue_job(DATA_DIR, selected_id)})
            while True:
                time.sleep(.1)
    marker = json.loads((output / 'interrupted.json').read_text(encoding='utf-8'))
    termination = json.loads((output / 'terminated.json').read_text(encoding='utf-8'))
    ready = json.loads((output / 'ready.json').read_text(encoding='utf-8'))
    assert termination['pid'] == ready['pid'] != os.getpid() and termination['exit_code'] != 0
    source_id, selected_id = marker['source_id'], marker['range_id']
    with TestClient(main.app) as client:
        selected = wait_task(selected_id)
        source = get_task(source_id)
        assert selected.control_generation == marker['generation']
        intent = wait_for_completed_intent(lambda: read_queue_job(DATA_DIR, selected_id), marker['intent'])
        assert selected.source_task_id == source_id
        assert selected.learning_range == {'start': 5, 'end': 15, 'original_start': 5, 'original_end': 15}
        assert fingerprint(task_dir(selected_id) / 'selected-range.mp4') == marker['clip'], 'Recovery must reuse the already complete clip'
        assert abs(selected.media_integrity.duration - 10) < .15
        transcript = read_json(selected_id, 'transcript.json', {})
        assert [s['text'] for s in transcript['segments']] == ['EVIDENCE_2', 'EVIDENCE_3']
        assert [(s['start'], s['end']) for s in transcript['segments']] == [(0, 5), (5, 10)]
        assert [(s['start'] + selected.learning_range['original_start'], s['end'] + selected.learning_range['original_start']) for s in transcript['segments']] == [(5, 10), (10, 15)]
        assert selected.visual_windows and all(0 <= w.start <= w.end <= 10 for w in selected.visual_windows)
        note = client.get(f'/api/tasks/{selected_id}/exports/markdown')
        assert note.status_code == 200
        assert 'EVIDENCE_2' in note.text and 'EVIDENCE_3' in note.text
        assert 'EVIDENCE_1' not in note.text and 'EVIDENCE_4' not in note.text
        assert '5–15' in selected.title
        # Run the actual browser-domain ancestry helper on actual API records.
        records = {id: client.get(f'/api/tasks/{id}').json() for id in (source_id, selected_id)}
        helper = (ROOT / 'web/range-source.js').read_text(encoding='utf-8')
        code = helper + '\nconst records=JSON.parse(process.argv[1]); const source=await fullVideoSource(process.argv[2],async id=>records[id]); console.log(source.id);'
        resolved = subprocess.run(['node', '--input-type=module', '-e', code, json.dumps(records), selected_id], capture_output=True, text=True, encoding='utf-8', check=True).stdout.strip()
        assert resolved == source_id
        # Actual whole-source upgrade route, subtitles mode requires no provider admission.
        upgraded = client.post(f'/api/tasks/{resolved}/rerun-from-media', json={'content_mode': 'subtitles', 'visual_understanding': False})
        assert upgraded.status_code == 200, upgraded.text
        whole = wait_task(upgraded.json()['task_id'])
        whole_intent = read_queue_job(DATA_DIR, whole.id)
        wait_for_completed_intent(lambda: read_queue_job(DATA_DIR, whole.id), whole_intent)
        assert not whole.learning_range and whole.source_task_id == source_id
        assert abs(whole.media_integrity.duration - 20) < .15
        assert len(read_json(whole.id, 'transcript.json', {})['segments']) == 4
        assert whole.source_media_path == source.media_path
        for start, end in [(-1, 10), (5, 21), (15, 5)]:
            assert client.post(f'/api/tasks/{source_id}/learn-range', json={'start': start, 'end': end}).status_code == 422
        assert client.post('/api/tasks/missing/learn-range', json={'start': 5, 'end': 15}).status_code == 404
        assert client.post(f'/api/tasks/{source_id}/learn-range', json={'start': 5, 'end': 15, 'source_task_id': 'forged'}).status_code == 422
        assert {key: fingerprint(getattr(source, key)) for key in marker['source_artifacts']} == marker['source_artifacts']
        assert recover_processing(DATA_DIR) == {'recovered': 0, 'waiting_for_context': 0}
        write(output / 'report.json', {'status': 'pass', 'source_id': source_id, 'range_id': selected_id,
            'whole_upgrade_id': whole.id, 'whole_upgrade_mode': 'subtitles (no model)', 'duration_seconds': 20,
            'terminated_worker': termination, 'fresh_worker_pid': os.getpid(),
            'source_artifacts': marker['source_artifacts'], 'clip_fingerprint': marker['clip'],
            'range_transcript_segments': transcript['segments'],
            'range_note_sha256': hashlib.sha256(note.content).hexdigest(),
            'intent_sequence': intent['sequence'], 'intent_generation': intent['generation'], 'selected_range': selected.learning_range,
            'source_artifacts_unchanged': True, 'completed_clip_reused_hash_and_mtime': True,
            'recovered_same_task_and_intent': True, 'selected_evidence': ['EVIDENCE_2', 'EVIDENCE_3'],
            'relative_cue_ranges': [[0, 5], [5, 10]], 'absolute_cue_ranges': [[5, 10], [10, 15]],
            'rejected_requests': ['negative start', 'end past source', 'reversed bounds', 'missing source', 'extra forged source field'],
            'full_upgrade_evidence_count': 4, 'whole_source_media_reused': True,
            'summary_provider': 'deterministic fixture', 'subtitles': 'synthetic timed SRT; no ASR',
            'not_tested': ['browser range selectors', 'native player seek', 'real websites', 'provider summary', 'ASR']})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--worker', choices=['start', 'recover'])
    args = parser.parse_args()
    output = args.output_dir.resolve()
    diagnostics = load_script('interrupted-task-reliability')
    if args.worker:
        try:
            worker(output, args.worker)
        except Exception as error:
            diagnostics.record_failure(output, args.worker, error)
            raise
        return
    output.mkdir(parents=True, exist_ok=False)
    (output / 'data').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LEARNNOTE_', 'OPENAI_', 'ANTHROPIC_', 'DEEPSEEK_', 'GEMINI_'))}
    env.update(LEARNNOTE_DATA_DIR=str(output / 'data'), LEARNNOTE_DEPLOYMENT_MODE='desktop',
               LEARNNOTE_LLM_API_KEY='', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    command = [sys.executable, str(Path(__file__).resolve()), '--output-dir', str(output), '--worker']
    process = None
    try:
        with (output / 'start.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command + ['start'], env=env, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 120
            while not (output / 'interrupted.json').exists():
                assert process.poll() is None, 'Start worker exited; see start.log'
                assert time.monotonic() < deadline, 'Range checkpoint timeout'
                time.sleep(.05)
            process.kill()
            process.wait(timeout=10)
            assert process.returncode != 0
            write(output / 'terminated.json', {'pid': process.pid, 'exit_code': process.returncode})
        with (output / 'recover.log').open('w', encoding='utf-8') as log:
            subprocess.run(command + ['recover'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        print((output / 'report.json').read_text(encoding='utf-8'))
    except Exception as error:
        diagnostics.record_failure(output, 'parent', error)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)


if __name__ == '__main__':
    main()
