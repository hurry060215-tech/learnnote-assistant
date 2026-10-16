"""Real course routes on isolated synthetic disk data; all processing stays deferred."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch
from contextlib import ExitStack


def configure_fixture(root, data, stack):
    """Called only in a dedicated fixture process before importing the backend."""
    if not data.is_dir() or any(data.iterdir()):
        raise ValueError('Fixture data directory must exist and be empty')
    for name in list(os.environ):
        if name.startswith(('LEARNNOTE_', 'OPENAI_', 'AZURE_', 'ANTHROPIC_')) or name.upper().endswith('_PROXY'):
            del os.environ[name]
    os.environ.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE='local', PYTHONUTF8='1')
    sys.path[:0] = [str(root), str(root / 'backend')]
    spec = importlib.util.spec_from_file_location('offline_acceptance', root / 'scripts/test-backend-offline.py')
    offline = importlib.util.module_from_spec(spec); spec.loader.exec_module(offline)
    stack.enter_context(offline.offline_network())
    from app import main, courses, course_episodes, storage, course_upgrades, course_upgrade_admission, model_connections
    from app.models import TaskOptions, TranscriptResult, TranscriptSegment
    selected = {'base_url': 'http://127.0.0.1:19877/v1', 'model': 'synthetic-vision', 'key': 'local-no-key', 'fingerprint': 'fixture-v1'}
    state = {'admissions': [], 'processing_executed': False}
    def connection(base_url, model):
        if (base_url, model) != (selected['base_url'], selected['model']):
            raise ValueError('course_model_changed')
        return dict(selected)
    def connection_status():
        return {'configured': True, 'storage': 'none', 'model': {'provider': 'custom', 'base_url': selected['base_url'],
            'model': selected['model'], 'use_saved_connection': True}}
    def schedule(background_tasks, processor, task_id, request, **kwargs):
        # Admission is real. The scheduler boundary records but never starts work.
        state['admissions'].append({'task_id': task_id, 'processor': processor.__name__, 'queue_kind': kwargs.get('_queue_kind'),
            'page_text': getattr(request, 'page_text', ''), 'cookies': len(getattr(request, 'cookies', [])),
            'resources': len(getattr(request, 'resources', [])), 'captions': len(getattr(request, 'browser_subtitles', []))})
    stack.enter_context(patch.object(course_upgrades, 'connection', side_effect=connection))
    stack.enter_context(patch.object(model_connections, 'selected_connection_status', side_effect=connection_status))
    stack.enter_context(patch.object(main, 'selected_connection_status', side_effect=connection_status))
    stack.enter_context(patch.object(course_upgrade_admission, 'validate_model'))
    stack.enter_context(patch.object(main, 'require_ready_note_model'))
    stack.enter_context(patch.object(main, 'resolve_model_options', side_effect=lambda value: value))
    stack.enter_context(patch.object(main, 'recover_processing'))
    stack.enter_context(patch.object(course_upgrade_admission, 'schedule_processing', side_effect=schedule))
    stack.enter_context(patch.object(main, 'schedule_processing', side_effect=schedule))
    sources = [{'kind': 'url', 'url': f'https://www.bilibili.com/video/BV1xx411c7mD?p={part}'} for part in (1, 2)]
    course = courses.save_course('合成课程 · 字幕与画面升级', sources)
    tasks = []
    for index, episode in enumerate(course_episodes.course_episodes(course)):
        course_episodes.prepare_course_episode(course, episode['episode_id'])
        task = storage.create_task('current_page', f'合成字幕分集 {index + 1}', page_url=episode['url'],
            handoff_id=episode['handoff_id'], options=TaskOptions(content_mode='text', visual_understanding=False, resource_budget_mb=512))
        transcript = TranscriptResult(source='browser-subtitle', language='zh', full_text='这是合成字幕，原始字幕与笔记须保持完整。',
            segments=[TranscriptSegment(start=0, end=12, text='这是合成字幕，原始字幕与笔记须保持完整。')])
        caption = storage.write_json(task.id, 'transcript.json', transcript.model_dump(mode='json'))
        note = storage.task_dir(task.id) / 'note.md'; note.write_text('# 原始字幕笔记\n\n这是合成字幕，原始字幕与笔记须保持完整。', encoding='utf-8')
        storage.update_task(task.id, status='success' if index == 0 else 'failed', mode='subtitle_only', checkpoint='transcribed',
            transcript_path=str(caption), note_path=str(note), error_code='' if index == 0 else 'summary_unavailable')
        course_episodes.bind_course_episode(course, episode['episode_id'], task.id)
        tasks.append(task.id)
    episodes = course_episodes.course_episodes(course)
    @main.app.get('/_fixture/state')
    def fixture_state():
        return {**state, 'course_id': course['id'], 'episodes': course_episodes.course_episodes(courses.get_course(course['id']))}
    @main.app.post('/_fixture/selection/{mode}')
    def fixture_selection(mode: str):
        selected['model'] = 'synthetic-vision' if mode == 'normal' else 'synthetic-changed'
        selected['fingerprint'] = 'fixture-v1' if mode == 'normal' else 'fixture-v2'
        return {'ok': True}
    return main.app, {'offline_network': True, 'course_id': course['id'], 'task_id': tasks[0], 'retry_task_id': tasks[1],
        'episode_id': episodes[0]['episode_id'], 'retry_episode_id': episodes[1]['episode_id']}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--data-dir', required=True)
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    with ExitStack() as stack:
        app, fixture = configure_fixture(root, Path(args.data_dir).resolve(), stack)
        import uvicorn
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(128)
            origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
            os.environ['LEARNNOTE_BACKEND_ORIGIN'] = origin
            print(json.dumps({'fixture_origin': origin, **fixture}), flush=True)
            uvicorn.Server(uvicorn.Config(app, log_level='warning')).run(sockets=[listener])


if __name__ == '__main__': main()
