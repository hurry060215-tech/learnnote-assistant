"""Explicit episode retry admission; course identity is checked before dispatch."""
from . import courses, storage
from .course_episodes import course_episodes
from .task_control_state import task_generation
from .course_caption_state import retry_kind


def selected_episode(course_id, episode_id, revision):
    course = courses.get_course(course_id)
    if course['revision'] != revision or course['paused']:
        raise ValueError('course_changed_reload_required')
    episode = next((item for item in course_episodes(course) if item['episode_id'] == episode_id), None)
    if not episode or not episode.get('task_id') or episode['status'] in {'identity_conflict', 'source_unreadable'}:
        raise ValueError('course_episode_identity_conflict')
    return course, episode, storage.get_task(episode['task_id'])


def retry_episode(course_id, episode_id, request, background_tasks, *, retry_summary, resume_task):
    with courses.course_transaction(), storage.task_state_transaction():
        _, episode, task = selected_episode(course_id, episode_id, request.revision)
        if (task.id != request.task_id or task_generation(task) != request.generation
                or not episode['retryable']):
            raise ValueError('course_episode_changed')
        if retry_kind(task) == 'summary':
            if request.options.content_mode != 'text' or request.options.visual_understanding:
                raise ValueError('course_text_retry_required')
            return retry_summary(task.id, background_tasks, request.options)
        return resume_task(task.id, background_tasks, request.options)
