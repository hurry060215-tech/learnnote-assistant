"""Derived child membership bound to an original course episode, never URL cache."""
import hashlib
import re
from pathlib import Path
from .source_input import normalize_source_input


def upgrade_prefix(course_id, episode_id, source_id):
    identity = f'{course_id}:{episode_id}:{source_id}'.encode()
    return 'episode-upgrade-' + hashlib.sha256(identity).hexdigest()[:32] + '-'


def episode_upgrades(course_id, episode, source, tasks):
    prefix = upgrade_prefix(course_id, episode['episode_id'], source.id)
    result = []
    for task in tasks:
        if not task.handoff_id.startswith(prefix):
            continue
        if (not re.fullmatch(re.escape(prefix) + r'[a-f0-9]{32}', task.handoff_id) or task.source_task_id != source.id or task.source_type != 'current_page'
                or task.learning_range or task.mode != 'video'
                or normalize_source_input(task.page_url).url != normalize_source_input(source.page_url).url
                or (source.source_identity.page_url and normalize_source_input(task.source_identity.page_url).url != normalize_source_input(source.source_identity.page_url).url)):
            raise ValueError('course_episode_identity_conflict')
        media_available = any(Path(value).is_file() for value in (task.media_path,task.source_media_path) if value)
        result.append({'task_id': task.id, 'status': task.status, 'title': task.title, 'media_available':media_available})
    return sorted(result, key=lambda item: item['task_id'])


def blocks_reacquisition(child):
    return child['status'] in {'queued','running','cancelling','success'} or child.get('media_available',False)
