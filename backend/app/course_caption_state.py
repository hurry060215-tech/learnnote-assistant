"""Read-only caption availability for episode presentation and admission."""
from pathlib import Path
from urllib.parse import urlsplit
from . import storage


def owned_caption_path(task):
    from .task_paths import resolve_task_artifact, TaskArtifactUnavailable
    try:
        return resolve_task_artifact(storage.TASK_DIR / task.id, task.id, task.transcript_path, field="transcript_path")
    except TaskArtifactUnavailable:
        return None


def retry_kind(task):
    return "summary" if not (task.media_path or task.source_media_path) and owned_caption_path(task) else "media"

PUBLIC_COURSE_HOSTS = {'youtube.com','www.youtube.com','m.youtube.com','youtu.be',
                'bilibili.com','www.bilibili.com','m.bilibili.com'}


def eligible_source(task):
    parsed = urlsplit(task.page_url)
    return (task.source_type == 'current_page' and task.mode == 'subtitle_only'
            and not task.learning_range and not task.media_path and not task.source_media_path
            and task.status in {'success','failed','cancelled','interrupted'}
            and parsed.scheme == 'https' and parsed.hostname in PUBLIC_COURSE_HOSTS
            and not parsed.username and not parsed.password and owned_caption_path(task) is not None)
