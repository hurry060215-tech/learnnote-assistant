"""Monotonic timing boundaries without storage, model, or queue dependencies."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from threading import Lock


_queue_wait = ContextVar("pipeline_queue_wait", default=None)


def queued_callback(task_id, callback, *, recovery=False):
    """Capture only this accepted in-process enqueue, never persisted timestamps."""
    queued_at = monotonic()
    dispatched = False
    dispatch_lock = Lock()

    def run():
        nonlocal dispatched
        with dispatch_lock:
            interval = None if dispatched else (task_id, queued_at, monotonic(), "recovery" if recovery else "queued")
            dispatched = True
        token = _queue_wait.set(interval)
        try:
            return callback()
        finally:
            _queue_wait.reset(token)

    return run


def take_attempt_timing(task_id):
    """Consume this dispatch boundary and origin only once."""
    interval = _queue_wait.get()
    if interval is None or interval[0] != task_id:
        return None
    _queue_wait.set(None)
    return interval[1:]


def take_queue_wait(task_id):
    """Compatibility projection of the single-use queue interval."""
    interval = take_attempt_timing(task_id)
    return interval[:2] if interval is not None else None


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
