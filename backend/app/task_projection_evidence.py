"""Explicit, per-payload evidence reuse; never retained between HTTP requests.

Media readers remain adapters owned by the API. Ownership and media validation
run on first access; repeated projections use the same task/generation facts.
"""
from .task_control_state import task_generation
from .task_media_guard import _OWNED_FIELDS

_UNREAD = object()


class TaskProjectionEvidence:
    def __init__(self, task, *, media_path, media_signature, non_video):
        self.task = task
        self.identity = self._identity(task)
        self.read_media_path = media_path
        self.read_media_signature = media_signature
        self.non_video = non_video
        self._media_path = _UNREAD
        self._media_validation = _UNREAD

    @staticmethod
    def _identity(task):
        return (task.id, task_generation(task), task.updated_at, task.media_path, task.source_media_path,
                tuple(getattr(task, field) for field in _OWNED_FIELDS), tuple(sorted(task.learning_range.items())))

    def require(self, task):
        if task is not self.task or self._identity(task) != self.identity:
            raise ValueError("task_projection_evidence_mismatch")

    def media_path(self, task):
        self.require(task)
        if self._media_path is _UNREAD:
            self._media_path = self.read_media_path(task)
        return self._media_path

    def media_validation(self, task):
        self.require(task)
        if self._media_validation is _UNREAD:
            path = self.media_path(task)
            if path is None:
                self._media_validation = ("missing", "")
            else:
                signature = self.read_media_signature(path)
                state = "invalid" if not signature or self.non_video(task) else "verified"
                self._media_validation = (state, signature)
        return self._media_validation
