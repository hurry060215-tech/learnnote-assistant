"""Synthetic installed-API seed. Never imports or writes backend storage directly."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

TITLE = 'Synthetic installed reading'
DEEP_HEADING = 'Synthetic deep heading'
CUES = [
    # Distinct introductory vocabulary keeps the fixed follow times unambiguous
    # through the real lexical candidate mapping, without changing its rules.
    {'start': 0, 'end': 10, 'text': 'Opening context. Reading start. Synthetic deep heading. Follow visibility. Synthetic reading space. Synthetic trailing reading space.'},
    {'start': 10, 'end': 20, 'text': 'Second synthetic source supports the selected claim.'},
    {'start': 25, 'end': 28, 'text': 'Synthetic oversized caption ' + 'readable continuation ' * 170 + '.'},
    {'start': 28, 'end': 31, 'text': 'Readable continuation.'},
]
NOTE = ('# ' + TITLE + '\n\n## Reading start\n\n' + CUES[0]['text'] + '\n\n' +
        '\n\n'.join('> Synthetic reading space.' for _ in range(24)) +
        '\n\n### Reading start\n\n#### ' + DEEP_HEADING + '\n\n' + CUES[1]['text'] +
        '\n\n## Follow visibility\n\n' + CUES[2]['text'] + '\n\n' +
        '\n\n'.join('> Synthetic trailing reading space.' for _ in range(30)) + '\n')


def wait_task(api, task_id):
    deadline = time.monotonic() + 90
    while True:
        task = api.call('GET', f'/api/tasks/{task_id}').json()['task']
        if task['status'] in ('success', 'failed', 'cancelled'):
            assert task['status'] == 'success', f'Synthetic reading task failed: {task.get("error_code")}'
            return task
        if time.monotonic() >= deadline:
            raise TimeoutError('Synthetic installed reading task did not finish')
        time.sleep(.2)


def generate_media(directory, environment):
    directory = Path(directory)
    ffmpeg = shutil.which('ffmpeg', path=environment.get('PATH'))
    assert ffmpeg, 'Existing FFmpeg is required for synthetic installed media; no download is performed'
    subtitle = directory / 'synthetic-reading.srt'
    subtitle.write_text('\n\n'.join(f'{i + 1}\n00:00:{cue["start"]:02d},000 --> 00:00:{cue["end"]:02d},000\n{cue["text"]}'
                                    for i, cue in enumerate(CUES)) + '\n', encoding='utf-8')
    media = directory / 'synthetic-reading.mp4'
    assert not media.exists(), 'Fixture media must be fresh'
    subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'color=c=black:size=320x180:rate=2', '-i', str(subtitle),
                    '-t', '31', '-map', '0:v:0', '-map', '1:s:0', '-c:v', 'libx264',
                    '-preset', 'ultrafast', '-crf', '35', '-pix_fmt', 'yuv420p',
                    '-c:s', 'mov_text', '-movflags', '+faststart', str(media)],
                   check=True, timeout=60, capture_output=True, env=environment)
    assert media.is_file() and 0 < media.stat().st_size <= 1024 * 1024
    return media


def seed_reading(api, media, model_endpoint):
    with Path(media).open('rb') as stream:
        task_id = api.call('POST', '/api/tasks/from-local', files={'file': ('synthetic-reading.mp4', stream, 'video/mp4')},
                           data={'title': TITLE, 'options': json.dumps({'content_mode': 'subtitles', 'visual_understanding': False})}).json()['task_id']
    task = wait_task(api, task_id)
    assert task['summary_source'] == 'subtitle-extract'
    transcript = api.call('GET', f'/api/tasks/{task_id}/transcript').json()
    assert [{key: cue[key] for key in ('start', 'end', 'text')} for cue in transcript['segments']] == CUES
    api.call('POST', f'/api/tasks/{task_id}/retry-summary', json={'content_mode': 'text', 'visual_understanding': False,
             'use_saved_connection': False, 'llm_base_url': model_endpoint, 'llm_model': 'synthetic-local'})
    task = wait_task(api, task_id)
    assert task['summary_source'] == 'text-llm'
    edition = api.call('GET', f'/api/tasks/editions/task/{task_id}').json()
    assert '\n#### ' + DEEP_HEADING + '\n' in edition['text']
    mapping = api.call('GET', f'/api/tasks/{task_id}/claims').json()
    assert mapping['source_revision'] == edition['revision']
    claims = {row['text']: row for row in mapping['claims']}
    selected = [claims[CUES[index]['text']] for index in (1, 2)]
    assert all(row['verification'] == 'direct' and row['evidence_ids'] for row in selected)
    assert len(api.call('GET', f'/api/tasks/{task_id}/media').content) > 0
    api.call('POST', f'/api/personal/task/{task_id}', json={'text': 'Synthetic installed reading annotation'})
    return {'task_id': task_id, 'title': TITLE, 'claim_id': selected[0]['claim_id'], 'oversized_claim_id': selected[1]['claim_id'],
            'deep_heading': DEEP_HEADING, 'edition_revision': edition['revision'],
            'media_sha256': hashlib.sha256(Path(media).read_bytes()).hexdigest()}


def seed_community(api, task_id, model_endpoint):
    """Existing 0.2.16 APIs only: two bounded imports, no paging endpoint needed."""
    route = f'/api/tasks/{task_id}/community-context'
    assert api.call('GET', route + '/export').json()['items'] == []
    api.call('PUT', '/api/study/community/settings', json={'enabled': True})
    for start, count in ((1, 500), (501, 1)):
        api.call('POST', route, json={'items': [
            {'text': f'Synthetic installed opinion {index}.', 'kind': 'danmaku',
             'timestamp_seconds': 12, 'source_uri': 'https://example.com/synthetic-rollback'}
            for index in range(start, start + count)]})
    items = api.call('GET', route + '/export').json()['items']
    assert len(items) == 501 and len({item['item_id'] for item in items}) == 501
    assert {item['text'] for item in items} == {f'Synthetic installed opinion {index}.' for index in range(1, 502)}
    # Loopback-only, keyless metadata for local previews; no connection test or
    # answer request. The server may be stopped before the new app reads it.
    result = api.call('PUT', '/api/model/connection', headers={'Origin': api.origin}, json={
        'provider': 'custom', 'base_url': model_endpoint, 'model': 'synthetic-local'}).json()
    assert result['configured'] and result['model']['base_url'] == model_endpoint
    return {'count': 501, 'batch_sizes': [500, 1], 'model': result['model']}


def retained_features(api, reading, community_task_id):
    """Exact content and annotations, including the real installed media bytes."""
    task_id = reading['task_id']
    result = {}
    for name, route in {
        'transcript': f'/api/tasks/{task_id}/transcript',
        'subtitles': f'/api/tasks/{task_id}/exports/subtitles',
        'note': f'/api/tasks/editions/task/{task_id}',
        'claims': f'/api/tasks/{task_id}/claims',
        'media': f'/api/tasks/{task_id}/media',
        'annotations': f'/api/personal/task/{task_id}',
        'community': f'/api/tasks/{community_task_id}/community-context/export',
        'model': '/api/model/connection',
    }.items():
        result[name] = hashlib.sha256(api.call('GET', route).content).hexdigest()
    assert result['media'] == reading['media_sha256']
    return result
