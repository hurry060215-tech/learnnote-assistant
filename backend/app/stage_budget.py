"""Cancellable stage admission reuses a task's existing lane slot when present."""
from contextlib import contextmanager
from pathlib import Path
import time

from .queue_policy import lane_budgets
from .worker_lease import has_worker_lease, worker_lease


@contextmanager
def stage_budget(root: Path, lane: str, cancel_check=lambda: None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cancel_check()
    if has_worker_lease(root, lane):
        yield
        return
    count = lane_budgets()[lane]
    while True:
        cancel_check()
        for slot in range(count):
            with worker_lease(root, blocking=False, lane=lane, slot=slot) as acquired:
                if acquired:
                    cancel_check()
                    yield
                    return
        time.sleep(.05)
