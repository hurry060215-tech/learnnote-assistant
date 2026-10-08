from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.queue_policy import lane_budgets
from app.stage_budget import stage_budget
from app.task_queue import LocalTaskQueue, queue_status
from app.worker_lease import has_worker_lease, worker_lease


class QueueAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.errors = []
        self.stack.enter_context(patch.object(threading, "excepthook", self.errors.append))
        self.stack.enter_context(patch.dict(os.environ, {
            "LEARNNOTE_HEAVY_CONCURRENCY": "1", "LEARNNOTE_LIGHT_CONCURRENCY": "1",
            "LEARNNOTE_DOWNLOAD_CONCURRENCY": "1", "LEARNNOTE_LOW_RESOURCE_MODE": "0"}))
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.queues = []

    def tearDown(self):
        for queue in self.queues:
            queue.stop()
        self.assertEqual(self.errors, [], "A worker thread failed outside its Future")

    def queue(self):
        queue = LocalTaskQueue(self.root)
        self.queues.append(queue)
        return queue

    def test_waiting_for_other_instance_stays_queued_and_cancels_immediately(self):
        first, second = self.queue(), self.queue()
        started, release = threading.Event(), threading.Event()
        active = first.enqueue("active", "local", lambda: (started.set(), release.wait(5)))
        try:
            self.assertTrue(started.wait(2))
            pending = second.enqueue("pending", "local", lambda: self.fail("Cancelled callback ran"))
            time.sleep(.12)
            self.assertEqual(second.entries()[1]["state"], "queued")
            start = time.monotonic()
            self.assertTrue(second.cancel_pending("pending"))
            self.assertIsNone(pending.result(.5))
            self.assertLess(time.monotonic() - start, .5)
        finally:
            release.set()
            active.result(5)

    def test_three_lanes_start_independently(self):
        queue = self.queue()
        barrier = threading.Barrier(3)
        futures = [queue.enqueue(kind, kind, lambda: barrier.wait(3))
                   for kind in ("local", "local_light", "page_download")]
        for future in futures:
            future.result(5)

    def test_two_heavy_slots_are_shared_by_two_instances(self):
        with patch.dict(os.environ, {"LEARNNOTE_HEAVY_CONCURRENCY": "2"}):
            first, second = self.queue(), self.queue()
            lock, two_started, release = threading.Lock(), threading.Event(), threading.Event()
            active = peak = 0
            def work():
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                    if active == 2:
                        two_started.set()
                release.wait(5)
                with lock:
                    active -= 1
            futures = [(first if index % 2 else second).enqueue(str(index), "local", work)
                       for index in range(5)]
            try:
                self.assertTrue(two_started.wait(3))
                self.assertEqual(sum(row["state"] == "running" for row in first.entries()), 2)
            finally:
                release.set()
            for future in futures:
                future.result(5)
            self.assertEqual(peak, 2)
            self.assertEqual(len(first.entries()), 5)

    def test_global_fifo_across_instances(self):
        first, second = self.queue(), self.queue()
        order = []
        with worker_lease(self.root):
            futures = [(first if index % 2 else second).enqueue(str(index), "local", lambda i=index: order.append(i))
                       for index in range(5)]
        for future in futures:
            future.result(5)
        self.assertEqual(order, list(range(5)))

    def test_failed_fifo_claim_releases_os_slot_before_backoff(self):
        queue = self.queue()
        original_claim, original_wait = queue._claim, queue.condition.wait
        claimed = False
        waits = []
        def claim(task_id, lane):
            nonlocal claimed
            if not claimed:
                claimed = True
                return False
            return original_claim(task_id, lane)
        def wait(timeout=None):
            waits.append(timeout)
            self.assertFalse(has_worker_lease(self.root, "heavy"), "FIFO backoff retained an OS slot")
            return original_wait(timeout)
        with patch.object(queue, "_claim", side_effect=claim), patch.object(queue.condition, "wait", side_effect=wait):
            queue.enqueue("after-older-intent", "local", lambda: None).result(3)
        self.assertTrue(waits)

    def test_low_resource_mode_caps_all_lanes_without_losing_work(self):
        with patch.dict(os.environ, {"LEARNNOTE_LOW_RESOURCE_MODE": "1", "LEARNNOTE_HEAVY_CONCURRENCY": "4",
                                     "LEARNNOTE_LIGHT_CONCURRENCY": "3", "LEARNNOTE_DOWNLOAD_CONCURRENCY": "2"}):
            queue = self.queue()
            self.assertEqual(queue.concurrency, {"heavy": 1, "light": 1, "download": 1})
            seen = []
            futures = [queue.enqueue(str(i), "local", lambda i=i: seen.append(i)) for i in range(5)]
            for future in futures:
                future.result(5)
            self.assertEqual(seen, list(range(5)))

    def test_invalid_budgets_fail_at_startup(self):
        for value in ("0", "-1", "5", "not-an-integer"):
            with self.subTest(value=value), patch.dict(os.environ, {"LEARNNOTE_DOWNLOAD_CONCURRENCY": value}):
                with self.assertRaises(ValueError):
                    lane_budgets()

    def test_download_task_reuses_its_existing_stage_slot(self):
        with worker_lease(self.root, lane="download"):
            with stage_budget(self.root, "download"):
                pass

    def test_heavy_download_waits_for_shared_download_slot_and_can_cancel(self):
        waiting, cancel = threading.Event(), threading.Event()
        class Cancelled(Exception):
            pass
        def check():
            waiting.set()
            if cancel.is_set():
                raise Cancelled()
        def work():
            with stage_budget(self.root, "download", check):
                self.fail("Occupied download slot was admitted")
        queue = self.queue()
        with worker_lease(self.root, lane="download"):
            future = queue.enqueue("heavy", "local", work)
            self.assertTrue(waiting.wait(2))
            start = time.monotonic()
            cancel.set()
            with self.assertRaises(Cancelled):
                future.result(2)
            self.assertLess(time.monotonic() - start, 2)
        with stage_budget(self.root, "download"):
            pass

    def test_stage_exception_releases_budget(self):
        with self.assertRaisesRegex(RuntimeError, "fixture"):
            with stage_budget(self.root, "download"):
                raise RuntimeError("fixture")
        with worker_lease(self.root, lane="download", blocking=False) as acquired:
            self.assertTrue(acquired)
