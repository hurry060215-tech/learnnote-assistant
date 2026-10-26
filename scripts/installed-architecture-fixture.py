"""Current installed API seed, separate from retained previous-version fixtures."""
from __future__ import annotations
import hashlib
import json
import time
import uuid


def seed_architecture(api, cues, model_endpoint, *, retry_title='Synthetic installed reading'):
    prefix = 'Synthetic architecture ' + uuid.uuid4().hex[:12]
    materials = []
    for index in range(105):
        title = f'{prefix} {index:03}'
        body = f'# {title}\n\nSynthetic installed catalog evidence {index}.\n'.encode()
        result = api.call('POST', '/api/library/materials/import', files={
            'file': (title + '.md', body, 'text/markdown')}).json()['material']
        materials.append(result)
    first = api.call('GET', '/api/library/materials?standalone=true&limit=100').json()
    assert first['has_more'] and len(first['materials']) == 100
    outside = set(row['material_id'] for row in materials) - set(row['material_id'] for row in first['materials'])
    assert outside, 'The fixture must prove a synthetic source is outside the first page'
    target = next(row for row in materials if row['material_id'] in outside)
    source = api.call('GET', f'/api/library/materials/{target["material_id"]}/source').content
    course = api.call('POST', '/api/courses', json={'title': prefix + ' course', 'sources': [
        {'kind': 'material', 'id': target['material_id'], 'title': target['title']}]}).json()['course']
    # The deterministic loopback model uses features.NOTE as its response. Give
    # this task the same title as that grounded note so the real summary gate
    # tests evidence handling rather than rejecting unrelated synthetic names.
    title = str(retry_title)
    task_id = api.call('POST', '/api/tasks/from-current-page', json={
        'page_url': 'https://example.com/synthetic-architecture', 'title': title,
        'handoff_id': 'installed-architecture-' + uuid.uuid4().hex, 'mode': 'subtitle_only',
        'browser_subtitles': cues, 'active_video': {'duration': max(row['end'] for row in cues)},
        'options': {'content_mode': 'subtitles', 'visual_understanding': False}}).json()['task_id']
    deadline = time.monotonic() + 90
    while True:
        task = api.call('GET', f'/api/tasks/{task_id}').json()['task']
        if task['status'] in ('success', 'failed', 'cancelled'):
            assert task['status'] == 'success' and task['summary_source'] == 'subtitle-extract'
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('Synthetic architecture subtitle task did not finish')
        time.sleep(.1)
    transcript = api.call('GET', f'/api/tasks/{task_id}/transcript').content
    return {'schema_version': 1, 'prefix': prefix, 'material_count': 105, 'material_ids': [row['material_id'] for row in materials],
            'target': {'id': target['material_id'], 'title': target['title'], 'source_sha256': hashlib.sha256(source).hexdigest()},
            'course_id': course['id'], 'retry': {'task_id': task_id, 'title': title,
            'transcript_sha256': hashlib.sha256(transcript).hexdigest()}, 'model_endpoint': model_endpoint}
