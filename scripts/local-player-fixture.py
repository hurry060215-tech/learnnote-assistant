"""Fresh loopback-only local player fixture. Real media, clipping and task APIs.

Only summary generation is deterministic. All timed subtitles are synthetic;
ASR/models, real sites, accounts and extension permissions are not exercised.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_player_media(path: Path):
    """30fps represents fractional positions; the reliability fixture is 1fps."""
    from app.runtime import ffmpeg_bin, hidden_subprocess_kwargs
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError('FFmpeg is required for the local player fixture')
    subprocess.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000',
        '-t', '20', '-map', '0:v:0', '-map', '1:a:0',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '35',
        '-pix_fmt', 'yuv420p', '-g', '60', '-c:a', 'aac', '-b:a', '32k',
        '-movflags', '+faststart', '-shortest', str(path)],
        capture_output=True, text=True, check=True, **hidden_subprocess_kwargs())


def verify_fixture_timing(media: Path):
    from app.media import extract_video_clip, probe_media_integrity
    clip = extract_video_clip(media, media.with_name('timing-range.mp4'), 5.25, 15.75)
    nested = extract_video_clip(clip, media.with_name('timing-nested.mp4'), 0, 5.25)
    durations = {name: probe_media_integrity(file).duration for name, file in
                 (('source', media), ('clip', clip), ('nested', nested))}
    for name, expected in (('source', 20), ('clip', 10.5), ('nested', 5.25)):
        assert abs(durations[name] - expected) < .15, durations
    return durations


def verify_low_frame_rate_range(media: Path, subtitle: Path, options):
    """Requested evidence bounds differ from quantized encoded container length."""
    from fastapi.testclient import TestClient
    from app import processor
    from app.main import app
    from app.storage import create_task, get_task, list_tasks
    low_rate_media = media.with_name('one-fps.mp4')
    script('long-video-reliability').generate_synthetic_media(low_rate_media, 20)
    source = create_task('local', 'Synthetic 1fps timing limit', options=options, mode='local')
    processor.process_local_video_task(source.id, low_rate_media, source.title, options,
        subtitle_path=subtitle, subtitle_source='synthetic-fixture')
    assert get_task(source.id).status == 'success'
    with TestClient(app) as client:
        response = client.post(f'/api/tasks/{source.id}/learn-range', json={
            'start': 5.25, 'end': 15.75, 'options': options.model_dump(mode='json')})
        assert response.status_code == 200, response.text
        task_id = response.json()['task_id']
        deadline = time.monotonic() + 60
        while True:
            payload = client.get(f'/api/tasks/{task_id}').json()['task']
            if payload['status'] in {'success', 'failed', 'cancelled'}:
                break
            assert time.monotonic() < deadline, payload['status']
            time.sleep(.05)
        assert payload['status'] == 'success', payload
        requested = {'start': 5.25, 'end': 15.75, 'original_start': 5.25, 'original_end': 15.75}
        assert payload['learning_range'] == requested
        encoded = payload['media_integrity']['duration']
        assert abs(encoded - 10.5) > .15, encoded
        cues = client.get(f'/api/tasks/{task_id}/transcript').json()['segments']
        assert [(cue['start'], cue['end'], cue['text']) for cue in cues] == [
            (0, 5.25, 'SYNTHETIC_SECOND: This synthetic lesson keeps the selected segment within its requested time bounds.'), (5.25, 10.5, 'SYNTHETIC_THIRD: This synthetic lesson explains why encoded padding is not additional source evidence.')]
        before = {task.id for task in list_tasks()}
        rejected = []
        for start, end in ((10.5, 11), (0, 10.500000001), (0, 10.505)):
            response = client.post(f'/api/tasks/{task_id}/learn-range', json={
                'start': start, 'end': end, 'options': options.model_dump(mode='json')})
            assert response.status_code == 422, response.text
            assert response.json()['detail']['code'] == 'invalid_learning_range', response.text
            rejected.append({'start': start, 'end': end, 'status': response.status_code})
        assert {task.id for task in list_tasks()} == before, 'Rejected padding must not create tasks'
        return {'frame_rate': 1, 'requested_seconds': 10.5, 'actual_encoded_seconds': encoded,
                'learning_range': payload['learning_range'], 'relative_cues': cues,
                'nested_padding_rejections': rejected,
                'api_distinguishes_requested_and_encoded': True,
                'limit': '1fps cannot represent quarter-second boundaries; encoded length is not an exact frame cut.'}


def verify_range_preview_lifecycle(source, options):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.media import extract_video_clip, probe_media_integrity
    from app.range_learning import process_range_task
    from app.storage import task_dir, update_task, list_tasks
    with TestClient(app) as client, patch('app.range_learning.schedule_processing'):
        response = client.post(f'/api/tasks/{source.id}/learn-range', json={
            'start':5.25, 'end':15.75, 'options':options.model_dump(mode='json')})
        assert response.status_code == 200, response.text
        task_id = response.json()['task_id']
        assert client.get(f'/api/tasks/{task_id}').json()['task']['range_media_ready'] is False
        pending = client.get(f'/api/tasks/{task_id}/media')
        assert pending.status_code == 409, pending.text
        before = {task.id for task in list_tasks()}
        with patch('app.main.schedule_processing') as rerun_schedule:
            rerun = client.post(f'/api/tasks/{task_id}/rerun-from-media', json={'options':options.model_dump(mode='json')})
            assert rerun.status_code == 409, rerun.text
            rerun_schedule.assert_not_called()
        nested = client.post(f'/api/tasks/{task_id}/learn-range', json={'start':0,'end':5,'options':options.model_dump(mode='json')})
        assert nested.status_code == 409, nested.text
        assert {task.id for task in list_tasks()} == before, 'Pending range admission must not create a task'
        root = task_dir(task_id)
        (root / 'selected-range.partial.mp4').write_bytes(b'incomplete synthetic clip')
        assert client.get(f'/api/tasks/{task_id}/media').status_code == 409
        clip = extract_video_clip(Path(source.media_path), root / 'selected-range.mp4', 5.25, 15.75)
        update_task(task_id, status='running', phase='summarizing')
        ready = client.get(f'/api/tasks/{task_id}').json()['task']
        assert ready['range_media_ready'] is True and ready['status'] == 'running'
        served = client.get(f'/api/tasks/{task_id}/media?v=synthetic-ready')
        assert served.status_code == 200 and served.headers['cache-control'] == 'no-store', (served.status_code,dict(served.headers),served.text[:150] if served.status_code != 200 else '')
        assert served.content == clip.read_bytes()
        assert served.content != Path(source.media_path).read_bytes()
        received = root / 'received-preview.mp4'; received.write_bytes(served.content)
        duration = probe_media_integrity(received).duration
        assert abs(duration - 10.5) < .15, duration
        process_range_task(task_id, Path(source.media_path), ready['title'], options)
        assert client.get(f'/api/tasks/{task_id}').json()['task']['status'] == 'success'
        assert client.get(f'/api/tasks/{task_id}/media').content == served.content
        nested = client.post(f'/api/tasks/{task_id}/learn-range', json={
            'start':0, 'end':5.25, 'options':options.model_dump(mode='json')})
        assert nested.status_code == 200, nested.text
        nested_id = nested.json()['task_id']
        process_range_task(nested_id, clip, nested.json()['task']['title'], options)
        nested_task = client.get(f'/api/tasks/{nested_id}').json()['task']
        assert nested_task['status'] == 'success', nested_task
        assert nested_task['source_task_id'] == task_id
        assert nested_task['learning_range'] == {
            'start':0, 'end':5.25, 'original_start':5.25, 'original_end':10.5}
        assert abs(nested_task['media_integrity']['duration'] - 5.25) < .15, nested_task
        nested_cues = client.get(f'/api/tasks/{nested_id}/transcript').json()['segments']
        assert [(cue['start'], cue['end'], cue['text']) for cue in nested_cues] == [
            (0, 5.25, 'SYNTHETIC_SECOND: This synthetic lesson keeps the selected segment within its requested time bounds.')]
        with patch('app.main.schedule_processing'):
            rerun = client.post(f'/api/tasks/{task_id}/rerun-from-media', json={'options':options.model_dump(mode='json')})
            assert rerun.status_code == 200, rerun.text
            assert client.get(f"/api/tasks/{rerun.json()['task_id']}/media").content == served.content
            whole = client.post(f'/api/tasks/{source.id}/rerun-from-media', json={'options':options.model_dump(mode='json')})
            assert whole.status_code == 200, whole.text
            assert client.get(f"/api/tasks/{whole.json()['task_id']}/media").content == Path(source.media_path).read_bytes()
        return {'pending_status':409, 'partial_status':409, 'pending_rerun_status':409, 'pending_nested_status':409, 'ready_during_summary':True,
                'served_duration':duration, 'served_sha256':hashlib.sha256(served.content).hexdigest(),
                'equals_selected_clip':True, 'differs_from_parent':True, 'cache_control':'no-store',
                'same_range_rerun_reused_clip':True, 'full_source_rerun_unchanged':True,
                'nested_pipeline':{'status':nested_task['status'], 'learning_range':nested_task['learning_range'],
                    'duration':nested_task['media_integrity']['duration'], 'relative_cues':nested_cues,
                    'evidence_can_summarize':nested_task['evidence_coverage']['can_summarize']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--seed-only', action='store_true')
    args = parser.parse_args()
    data = args.data_dir.resolve()
    if not data.is_dir() or any(data.iterdir()):
        raise ValueError('Acceptance directory must exist and be empty')
    for name in list(os.environ):
        if name.startswith(('LEARNNOTE_', 'OPENAI_', 'AZURE_', 'ANTHROPIC_')) or name.upper().endswith('_PROXY'):
            del os.environ[name]
    os.environ.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE='local',
                      LEARNNOTE_LLM_API_KEY='', PYTHONUTF8='1',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', ORT_DISABLE_TELEMETRY='1')
    sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
    with script('test-backend-offline').offline_network():
        from app import processor
        from app.models import TaskOptions
        from app.storage import create_task, get_task
        options = TaskOptions(content_mode='auto', visual_understanding=False, llm_api_key='')
        def summary(title, transcript, grids, settings, *args, **kwargs):
            return '# ' + title + '\n\n' + '\n\n'.join(s.text for s in transcript.segments) + '\n\n[00:05] [00:10]', 'offline-fixture', '', []
        processor.summarize_with_diagnostics = summary
        media = data / 'synthetic.mp4'
        generate_player_media(media)
        subtitle = data / 'synthetic.srt'
        subtitle.write_text('''1
00:00:00,000 --> 00:00:05,250
SYNTHETIC_FIRST: This synthetic lesson introduces local playback and precise source-bound timestamps.

2
00:00:05,250 --> 00:00:10,500
SYNTHETIC_SECOND: This synthetic lesson keeps the selected segment within its requested time bounds.

3
00:00:10,500 --> 00:00:15,750
SYNTHETIC_THIRD: This synthetic lesson explains why encoded padding is not additional source evidence.

4
00:00:15,750 --> 00:00:20,000
SYNTHETIC_FOURTH: This synthetic lesson returns to the complete original media without changing its source.
''', encoding='utf-8')
        tasks = []
        for suffix in ('A', 'B'):
            task = create_task('local', f'Synthetic local player {suffix}', options=options, mode='local')
            processor.process_local_video_task(task.id, media, task.title, options,
                subtitle_path=subtitle, subtitle_source='synthetic-fixture')
            task = get_task(task.id)
            assert task.status == 'success', task.model_dump_json()
            tasks.append(task)
        def originals():
            return {task.id: {key: hashlib.sha256(Path(getattr(task, key)).read_bytes()).hexdigest()
                    for key in ('media_path', 'transcript_path', 'note_path')} for task in tasks}
        fixture = {'offline_network': True, 'source_id': tasks[0].id, 'other_id': tasks[1].id,
                   'source_artifacts': originals(), 'summary_provider': 'deterministic fixture', 'media_frame_rate': 30}
        if args.seed_only:
            fixture['timing_seconds'] = verify_fixture_timing(media)
            fixture['one_fps_quantization'] = verify_low_frame_rate_range(media, subtitle, options)
            fixture['preview_lifecycle'] = verify_range_preview_lifecycle(tasks[0], options)
            print(json.dumps(fixture), flush=True)
            return
        from app.main import app
        from app import range_learning
        import uvicorn
        range_gate = threading.Event(); range_gate.set()
        process_range = range_learning.process_range_task
        def gated_range(*args, **kwargs):
            if not range_gate.wait(30): raise RuntimeError('Synthetic range gate was not released')
            return process_range(*args, **kwargs)
        range_learning.process_range_task = gated_range
        @app.post('/_fixture/range-gate/{action}')
        def range_gate_control(action: str):
            if action == 'hold': range_gate.clear()
            elif action == 'release': range_gate.set()
            else: raise ValueError('Unknown synthetic gate action')
            return {'released':range_gate.is_set()}
        @app.get('/_fixture/originals')
        def read_originals(): return originals()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(128)
            origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
            os.environ['LEARNNOTE_BACKEND_ORIGIN'] = origin
            print(json.dumps({'fixture_origin': origin, **fixture}), flush=True)
            uvicorn.Server(uvicorn.Config(app, log_level='warning')).run(sockets=[listener])


if __name__ == '__main__':
    main()
