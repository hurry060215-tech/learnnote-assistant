from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import observability, storage
from app.routers import events


def _complete_between_manifest_and_event(root, task_id, ready, release):
    task_dir = Path(root) / "tasks"
    storage.TASK_DIR = observability.TASK_DIR = task_dir
    original_event = observability.record_task_event
    def delayed_event(*args, **kwargs):
        ready.set()
        if not release.wait(10):
            raise TimeoutError("Synthetic completion barrier was not released")
        return original_event(*args, **kwargs)
    with patch.object(storage, "index_task"), patch.object(storage, "record_status"), \
            patch.object(observability, "ensure_dirs"), \
            patch.object(storage, "record_task_event", side_effect=delayed_event):
        storage.update_task(task_id, status="success", phase="completed", progress=100)


class EventStreamTransactionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in (storage, observability):
            self.stack.enter_context(patch.object(module, "TASK_DIR", self.root / "tasks"))
            self.stack.enter_context(patch.object(module, "ensure_dirs"))
        self.stack.enter_context(patch.object(storage, "index_task"))
        self.stack.enter_context(patch.object(storage, "record_status"))

    def test_cross_process_terminal_waits_for_event_without_blocking_http_loop(self):
        task = storage.create_task("local", "Synthetic completion")
        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        child = context.Process(target=_complete_between_manifest_and_event,
                                args=(str(self.root), task.id, ready, release))
        app = FastAPI(); app.include_router(events.events_router)
        @app.get("/health")
        async def health():
            return {"ok": True}
        entered = threading.Event()
        snapshot = events._terminal_event_snapshot
        def observe_snapshot(*args):
            entered.set()
            return snapshot(*args)
        child.start()
        try:
            self.assertTrue(ready.wait(5))
            # The manifest is visible, but the writer still owns its transaction.
            self.assertEqual(storage.get_task(task.id).status, "success")
            self.assertEqual(len(observability.read_task_events_after(task.id)), 1)
            with patch.object(events, "_terminal_event_snapshot", side_effect=observe_snapshot), \
                    TestClient(app) as client, ThreadPoolExecutor(2) as pool:
                streamed = pool.submit(client.get, f"/api/tasks/{task.id}/events/stream")
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertFalse(streamed.done())
                    health_reply = pool.submit(client.get, "/health").result(3)
                    self.assertEqual(health_reply.json(), {"ok": True})
                finally:
                    release.set()
                response = streamed.result(5)
            child.join(5)
            self.assertEqual(child.exitcode, 0)
            payloads = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            self.assertEqual([item["event_id"] for item in payloads if "event" in item], [1, 2])
            self.assertEqual(payloads[-1]["event_id"], 2)
            self.assertEqual(payloads[-1]["status"], "success")
        finally:
            release.set()
            if child.is_alive():
                child.terminate()
            child.join(5)

    def test_other_stream_status_read_does_not_block_loop_behind_terminal_lock(self):
        task = storage.create_task("local", "Synthetic second stream")
        acquired, release, timed_out = threading.Event(), threading.Event(), threading.Event()
        def hold_local_transaction():
            with storage.task_state_transaction():
                acquired.set()
                if not release.wait(5):
                    timed_out.set()
        async def consume():
            stream = events.task_event_stream(task.id)
            pending = None
            try:
                self.assertIn("event: task_created", await anext(stream))
                with ThreadPoolExecutor(1) as pool:
                    held = pool.submit(hold_local_transaction)
                    self.assertTrue(await asyncio.to_thread(acquired.wait, 3))
                    try:
                        pending = asyncio.create_task(anext(stream))
                        # This coroutine must run while another stream's snapshot
                        # thread owns the local lock and waits on a writer lease.
                        await asyncio.sleep(.02)
                        self.assertFalse(timed_out.is_set(), "Status read blocked the async event loop")
                        self.assertFalse(pending.done())
                    finally:
                        release.set()
                    await asyncio.to_thread(held.result, 3)
                await asyncio.to_thread(storage.update_task, task.id, status="cancelled", phase="cancelled")
                await asyncio.wait_for(pending, 3)
            finally:
                release.set()
                if pending and not pending.done():
                    pending.cancel()
                    try:
                        await pending
                    except asyncio.CancelledError:
                        pass
                await stream.aclose()
        asyncio.run(consume())

    def test_retry_while_terminal_snapshot_is_waiting_prevents_stale_terminal(self):
        task = storage.create_task("local", "Synthetic retry")
        storage.update_task(task.id, status="failed", phase="failed")
        snapshot = events._terminal_event_snapshot
        called = False
        def retry_before_snapshot(*args):
            nonlocal called
            if not called:
                called = True
                storage.update_task(task.id, status="queued", phase="queued", retry_count=1)
            return snapshot(*args)
        async def consume():
            stream = events.task_event_stream(task.id)
            seen = []
            try:
                while True:
                    frame = await asyncio.wait_for(anext(stream), 3)
                    seen.append(frame)
                    if 'event: task_updated' in frame and '"status":"queued"' in frame:
                        storage.update_task(task.id, status="cancelled", phase="cancelled")
                    if "event: task_terminal" in frame:
                        return seen
            finally:
                await stream.aclose()
        with patch.object(events, "_terminal_event_snapshot", side_effect=retry_before_snapshot):
            frames = asyncio.run(consume())
        terminal = [frame for frame in frames if "event: task_terminal" in frame]
        self.assertEqual(len(terminal), 1)
        self.assertIn('"status":"cancelled"', terminal[0])
        self.assertFalse(any('"status":"failed"' in frame for frame in terminal))

    def test_transaction_is_released_before_yield_and_terminal_state_is_refreshed(self):
        task = storage.create_task("local", "Synthetic yielded snapshot")
        storage.update_task(task.id, status="success", phase="completed")
        first = True
        read = observability.read_task_events_after
        def append_after_page(*args, **kwargs):
            nonlocal first
            rows = read(*args, **kwargs)
            if first:
                first = False
                observability.record_task_event(task.id, "late_committed", details={"synthetic": True})
            return rows
        async def consume():
            stream = events.task_event_stream(task.id)
            frames = []
            try:
                while True:
                    frame = await asyncio.wait_for(anext(stream), 3)
                    frames.append(frame)
                    if "event: late_committed" in frame:
                        # A different thread must acquire the transaction while
                        # this generator is suspended at its event yield.
                        await asyncio.wait_for(asyncio.to_thread(storage.update_task, task.id,
                            status="failed", phase="failed"), 3)
                    if "event: task_terminal" in frame:
                        return frames
            finally:
                await stream.aclose()
        with patch.object(events, "read_task_events_after", side_effect=append_after_page):
            frames = asyncio.run(consume())
        self.assertIn('"status":"failed"', frames[-1])
        self.assertEqual(sum("event: task_terminal" in frame for frame in frames), 1)

    def test_task_removed_during_terminal_synchronization_reports_missing(self):
        task = storage.create_task("local", "Synthetic deleted task")
        storage.update_task(task.id, status="success", phase="completed")
        def removed(*args):
            raise FileNotFoundError(task.id)
        app = FastAPI(); app.include_router(events.events_router)
        with patch.object(events, "_terminal_event_snapshot", side_effect=removed):
            response = TestClient(app).get(f"/api/tasks/{task.id}/events/stream")
        self.assertIn("event: task_missing", response.text)
        self.assertNotIn("event: task_terminal", response.text)


if __name__ == "__main__":
    unittest.main()
