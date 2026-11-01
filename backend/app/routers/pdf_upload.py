"""Admit PDF uploads before reading bytes or waiting on the catalog lock."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from functools import partial
from pathlib import Path
import threading

import anyio
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

_UPLOAD_SLOTS = threading.BoundedSemaphore(2)
# PDF work must not consume the default pool used by synchronous health routes.
_THREAD_LIMITER = anyio.CapacityLimiter(2)
_TASKS: set[asyncio.Task] = set()


class _Admission:
    def __init__(self):
        self.route_done = False
        self.worker_done = True
        self.released = False

    def release_if_done(self):
        # These state transitions run on the route's event loop, never in a worker.
        if self.route_done and self.worker_done and not self.released:
            self.released = True
            _UPLOAD_SLOTS.release()


@contextmanager
def admit_pdf_upload(filename: str, content_type: str):
    # Library preview/import sanitize before choosing the parser. Reuse that
    # exact normalizer, while retaining raw-name detection for evidence uploads.
    # This deliberately also admits evidence names that only the library would
    # treat as PDF. Import lazily to avoid a router/library import cycle.
    from ..library import _safe_material_filename
    names = (filename or '', _safe_material_filename(filename))
    if not any(Path(name).suffix.lower() == '.pdf' for name in names) and 'pdf' not in content_type.lower():
        yield None
        return
    if not _UPLOAD_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail={'code': 'pdf_import_busy', 'message': 'PDF 正在处理中，请稍后重试。'},
            headers={'Retry-After': '1'},
        )
    admission = _Admission()
    try:
        yield admission
    finally:
        admission.route_done = True
        admission.release_if_done()


async def run_upload_work(admission, function, *args, **kwargs):
    if admission is None:
        return await run_in_threadpool(function, *args, **kwargs)
    admission.worker_done = False

    async def work():
        try:
            return await anyio.to_thread.run_sync(partial(function, *args, **kwargs), limiter=_THREAD_LIMITER)
        finally:
            admission.worker_done = True
            admission.release_if_done()

    # A disconnected/cancelled request must not release its admission while its
    # thread is still parsing or waiting for the catalog. Keep the task alive and
    # observe its exception even when there is no longer a request awaiting it.
    task = asyncio.create_task(work())
    _TASKS.add(task)

    def finished(done):
        _TASKS.discard(done)
        if not done.cancelled():
            done.exception()

    task.add_done_callback(finished)
    return await asyncio.shield(task)
