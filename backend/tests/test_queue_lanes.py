import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.task_queue import LocalTaskQueue, QueueFull
from app.worker_lease import worker_lease


class QueueLaneTests(unittest.TestCase):
    def test_full_heavy_budget_does_not_consume_caption_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = LocalTaskQueue(Path(directory))
            release = threading.Event()
            try:
                with patch('app.task_queue.LANE_PENDING_LIMIT', 1):
                    heavy = queue.enqueue('heavy', 'local', lambda: release.wait(5))
                    with self.assertRaises(QueueFull):
                        queue.enqueue('overflow', 'local', lambda: None)
                    queue.enqueue('captions', 'local_light', lambda: None).result(2)
            finally:
                release.set()
                heavy.result(5)
                queue.stop()

    def test_duplicate_journal_intent_is_observed_without_executing_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = LocalTaskQueue(Path(directory)), LocalTaskQueue(Path(directory))
            release = threading.Event()
            first = a.enqueue('same', 'local', lambda: release.wait(5))
            duplicate = b.enqueue('same', 'local', lambda: self.fail('duplicate execution'))
            release.set()
            first.result(5)
            duplicate.result(5)
            a.stop()
            b.stop()
            self.assertEqual(len(b.entries()), 1)
            self.assertEqual(b.entries()[0]['state'], 'done')

    def test_process_exit_releases_both_lane_leases(self):
        code = '''
import sys, time
from pathlib import Path
from app.worker_lease import worker_lease
with worker_lease(Path(sys.argv[1]), lane=sys.argv[2]):
    print('locked', flush=True)
    time.sleep(60)
'''
        with tempfile.TemporaryDirectory() as directory:
            for lane in ('heavy', 'light'):
                child = subprocess.Popen([sys._base_executable, '-u', '-c', code, directory, lane], stdout=subprocess.PIPE, text=True)
                try:
                    self.assertEqual(child.stdout.readline().strip(), 'locked')
                    with worker_lease(Path(directory), blocking=False, lane=lane) as acquired:
                        self.assertFalse(acquired)
                finally:
                    child.kill()
                    child.wait(timeout=5)
                    child.stdout.close()
                with worker_lease(Path(directory), blocking=False, lane=lane) as acquired:
                    self.assertTrue(acquired, 'OS must release orphaned lease on process exit')
