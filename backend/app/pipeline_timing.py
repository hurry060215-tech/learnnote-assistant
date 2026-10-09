"""Monotonic timing boundaries without storage, model, or queue dependencies."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic


_queue_wait = ContextVar("pipeline_queue_wait", default=None)


def queued_callback(task_id, callback):
    """Capture only this accepted in-process enqueue, never persisted timestamps."""
    queued_at = monotonic()

    def run():
        token = _queue_wait.set((task_id, queued_at, monotonic()))
        try:
            return callback()
        finally:
            _queue_wait.reset(token)

    return run


def take_queue_wait(task_id):
    """A dispatched callback can attach its wait to only one pipeline attempt."""
    interval = _queue_wait.get()
    if interval is None or interval[0] != task_id:
        return None
    _queue_wait.set(None)
    return interval[1:]


def emit_timing(callback, stage, started_at, status, *, ended_at=None):
    """Optional observations must not change results, retries or cancellation."""
    if callback is None:
        return
    try:
        if ended_at is None:
            callback(stage, started_at, status)
        else:
            callback(stage, started_at, status, ended_at=ended_at)
    except Exception:
        pass  # Missing timings remain unknown; the original work owns its outcome.


@contextmanager
def measured_stage(stage, callback, *, cancelled=()):
    """Report the exact enclosing wall interval, including unsuccessful exits."""
    started_at = monotonic()
    outcome = {"status": "completed"}
    try:
        yield outcome
    except BaseException as exc:
        outcome["status"] = "cancelled" if isinstance(exc, cancelled) else "failed"
        raise
    finally:
        emit_timing(callback, stage, None if outcome["status"] == "skipped" else started_at, outcome["status"])
