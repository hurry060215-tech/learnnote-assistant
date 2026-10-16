"""Kill a real queued local-media pipeline, then recover in a fresh process.

Only the remote summary is replaced with an explicit deterministic fixture.
Media probing/normalization, subtitle ingestion, frames, durable task/queue,
worker leases, restart dispatch and final note are real.
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
import traceback

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def worker(output: Path, mode: str, duration: int):
    sys.path.insert(0, str(ROOT / 'backend'))
    # Fail closed if an unexpected provider/network route is reached.
    import socket
    def denied(*args, **kwargs):
        raise AssertionError('Network is forbidden in interrupted-task reliability')
    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    from fastapi import BackgroundTasks
    from app import processor
    from app.config import DATA_DIR
    from app.models import TaskOptions
    from app.storage import create_task, get_task, update_task
    from app.task_queue import schedule_processing, queue_for, recover_processing
    from app.queue_journal import read_queue_job
    queue = queue_for(DATA_DIR)

    def offline_summary(title, transcript, grids, options, page_url="", page_context="", **kwargs):
        if mode == 'start':
            current = get_task(task.id)
            assert current.checkpoint == 'visual_ready', current.checkpoint
            marker = {'task_id': task.id, 'worker_pid': os.getpid(), 'checkpoint': current.checkpoint,
                      'transcript_sha256': digest(current.transcript_path),
                      'transcript_mtime_ns': Path(current.transcript_path).stat().st_mtime_ns,
                      'media_mtime_ns': Path(current.media_path).stat().st_mtime_ns,
                      'generation': current.control_generation,
                      'intent': read_queue_job(DATA_DIR, task.id),
                      'media_sha256': digest(current.media_path)}
            (output / 'interrupted.json').write_text(json.dumps(marker), encoding='utf-8')
            while True:
                time.sleep(.1)  # Parent kills the whole process; no graceful cleanup.
        return '# Recovered synthetic lesson\n\n' + '\n'.join(s.text for s in transcript.segments), 'offline-fixture', '', []
    processor.summarize_with_diagnostics = offline_summary
    if mode == 'start':
        options = TaskOptions(visual_understanding=True, max_frame_count=60,
                              frame_interval=max(5, duration // 60), low_resource_mode=True, llm_api_key='')
        task = create_task(source_type='local', title='Interrupted synthetic lesson', options=options, mode='local')
        media = DATA_DIR / 'synthetic.mp4'
        subtitle = DATA_DIR / 'synthetic.srt'
        update_task(task.id, source_media_path=str(media), subtitle_path=str(subtitle))
        schedule_processing(BackgroundTasks(), processor.process_local_video_task,
                            task.id, media, task.title, options, subtitle_path=subtitle,
                            subtitle_source='page-subtitle')
        while not (output / 'interrupted.json').exists():
            if get_task(task.id).status == 'failed':
                raise AssertionError(get_task(task.id).model_dump_json())
            time.sleep(.1)
        # A second durable intent needs ephemeral context and must not auto-run.
        gated = create_task(source_type='current_page', title='Synthetic context boundary', options=options)
        queue.enqueue(gated.id, 'local', lambda: None, requires_context=True)
        (output / 'ready.json').write_text(json.dumps({'gated_id': gated.id}), encoding='utf-8')
        while True:
            time.sleep(.1)
    interrupted = json.loads((output / 'interrupted.json').read_text(encoding='utf-8'))
    termination = json.loads((output / 'terminated.json').read_text(encoding='utf-8'))
    assert termination['pid'] == interrupted['worker_pid'] != os.getpid()
    assert termination['exit_code'] != 0
    gated_id = json.loads((output / 'ready.json').read_text(encoding='utf-8'))['gated_id']
    # Observe the actual FastAPI startup sequence without replacing its work.
    from fastapi.testclient import TestClient
    from app import main as application
    startup = {'events': []}
    original_cleanup = application.cleanup_expired_staged_uploads
    original_recover = application.recover_processing
    def cleanup(*args, **kwargs):
        result = original_cleanup(*args, **kwargs)
        startup['events'].append('cleanup_completed')
        return result
    def recover(*args, **kwargs):
        assert startup['events'] == ['cleanup_completed']
        result = original_recover(*args, **kwargs)
        startup['events'].append('recovery_dispatched')
        startup['recovery'] = result
        return result
    application.cleanup_expired_staged_uploads = cleanup
    application.recover_processing = recover
    with TestClient(application.app) as client:
        recovery = startup["recovery"]
        assert recovery == {'recovered': 1, 'waiting_for_context': 1}, recovery
        task_id = interrupted['task_id']
        scheduled = queue.jobs.get(task_id)
        if scheduled is not None:
            scheduled[1].result(timeout=600)
        final = get_task(task_id)
        assert final.status == 'success', final.model_dump_json()
        assert final.id == task_id and final.control_generation == interrupted['generation']
        intent = read_queue_job(DATA_DIR, task_id)
        assert intent['sequence'] == interrupted['intent']['sequence']
        assert intent['generation'] == interrupted['intent']['generation']
        assert intent['state'] == 'done'
        assert startup['events'] == ['cleanup_completed', 'recovery_dispatched']
        assert client.get(f'/api/tasks/{task_id}').json()['task']['id'] == task_id
        assert client.get(f'/api/tasks/{task_id}/exports/markdown').status_code == 200
        assert final.summary_source == 'offline-fixture'
        assert digest(final.media_path) == interrupted['media_sha256']
        assert digest(final.transcript_path) == interrupted['transcript_sha256']
        assert Path(final.note_path).is_file() and Path(final.visual_index_path).is_file()
        assert 'Synthetic lesson checkpoint 4' in Path(final.note_path).read_text(encoding='utf-8')
        assert get_task(gated_id).error_code == 'resume_context_required'
        assert recover_processing(DATA_DIR) == {'recovered': 0, 'waiting_for_context': 0}
        report = {'status': 'pass', 'task_id': task_id, 'duration_seconds': duration,
                  'interrupted_checkpoint': interrupted['checkpoint'], 'recovery': recovery,
                  'final_status': final.status, 'final_checkpoint': final.checkpoint,
                  'terminated_worker': termination, 'fresh_worker_pid': os.getpid(),
                  'same_intent_sequence_and_generation': True, 'startup_order': startup['events'],
                  'artifact_mtimes_ns': {
                      'media_before': interrupted['media_mtime_ns'],
                      'media_after': Path(final.media_path).stat().st_mtime_ns,
                      'transcript_before': interrupted['transcript_mtime_ns'],
                      'transcript_after': Path(final.transcript_path).stat().st_mtime_ns},
                  'recovery_strategy': 'same task restarted through local pipeline; checkpoint artifacts may be recomputed',
                  'same_media_and_transcript_hashes': True, 'repeat_recovery_dispatched': 0,
                  'summary_source': final.summary_source, 'network_calls_allowed': False,
                  'asr_attempted': False, 'summary_provider': 'deterministic test fixture',
                  'not_tested': ['remote model', 'ASR', 'authenticated website', 'OS power loss']}
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')



def record_failure(output: Path, phase: str, error: Exception) -> None:
    """Preserve bounded synthetic-only diagnostics even when a worker exits."""
    report = {"status": "fail", "phase": phase, "error_type": type(error).__name__,
              "error": str(error)[-16000:], "traceback": traceback.format_exc()[-32000:]}
    name = f"worker-{phase}-failure.json" if phase in {"start", "recover"} else "report.json"
    (output / name).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), file=sys.stderr, flush=True)
    if phase == "parent":
        for name in ("start.log", "recover.log"):
            path = output / name
            if path.is_file():
                with path.open("rb") as handle:
                    handle.seek(max(0, path.stat().st_size - 64000))
                    tail = handle.read().decode("utf-8", errors="replace")
                print(f"--- {name} (last 64000 bytes) ---\n{tail}", file=sys.stderr, flush=True)


def run_parent(args, output: Path):
    data = output / 'data'
    data.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('LEARNNOTE_', 'OPENAI_', 'ANTHROPIC_', 'DEEPSEEK_', 'GEMINI_'))}
    env.update(PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE='desktop', LEARNNOTE_LLM_API_KEY='')
    os.environ.update(env)
    sys.path.insert(0, str(ROOT / 'backend'))
    spec = importlib.util.spec_from_file_location('long_video', ROOT / 'scripts/long-video-reliability.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.generate_synthetic_media(data / 'synthetic.mp4', args.duration_seconds)
    def stamp(seconds):
        return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02},000'
    (data / 'synthetic.srt').write_text('\n\n'.join(
        f'{i + 1}\n{stamp(i * args.duration_seconds // 4)} --> {stamp((i + 1) * args.duration_seconds // 4)}\n'
        f'Synthetic lesson checkpoint {i + 1}: durable local evidence remains traceable.' for i in range(4)), encoding='utf-8')
    command = [sys.executable, str(Path(__file__).resolve()), '--output-dir', str(output),
               '--duration-seconds', str(args.duration_seconds), '--worker']
    with (output / 'start.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command + ['start'], env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 600
            while not (output / 'ready.json').is_file():
                if process.poll() is not None:
                    raise RuntimeError('Initial pipeline exited before interruption; see start.log')
                if time.monotonic() > deadline:
                    raise TimeoutError('Timed out waiting for durable interruption checkpoint')
                time.sleep(.1)
        finally:
            process.kill()
            process.wait(timeout=30)
            if process.returncode == 0:
                raise AssertionError("Initial worker must terminate abnormally")
            (output / "terminated.json").write_text(json.dumps({"pid": process.pid, "exit_code": process.returncode}), encoding="utf-8")
    with (output / 'recover.log').open('w', encoding='utf-8') as log:
        subprocess.run(command + ['recover'], env=env, stdout=log, stderr=subprocess.STDOUT,
                       timeout=660, check=True)
    print((output / 'report.json').read_text(encoding='utf-8'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--duration-seconds', type=int, default=3600)
    parser.add_argument('--worker', choices=['start', 'recover'])
    args = parser.parse_args()
    if args.duration_seconds < 5:
        parser.error('duration must be at least 5 seconds')
    output = args.output_dir.resolve()
    if args.worker:
        try:
            worker(output, args.worker, args.duration_seconds)
        except Exception as error:
            record_failure(output, args.worker, error)
            raise
        return
    # A fresh directory avoids stale readiness markers from an earlier run.
    output.mkdir(parents=True, exist_ok=False)
    try:
        run_parent(args, output)
    except Exception as error:
        record_failure(output, "parent", error)
        raise


if __name__ == '__main__':
    main()
