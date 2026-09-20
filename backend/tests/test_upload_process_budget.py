from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from app.upload_reservations import ByteReservation, reserved_bytes


class ProcessBudgetTests(unittest.TestCase):
    def test_live_process_reserves_capacity_and_crash_reclaims_it(self):
        code = '''
import sys, time
from app.upload_reservations import ByteReservation
r = ByteReservation(sys.argv[1])
assert r.reserve(8, 10)
print('reserved', flush=True)
time.sleep(60)
'''
        with tempfile.TemporaryDirectory() as directory:
            child = subprocess.Popen([sys._base_executable, '-u', '-c', code, directory], stdout=subprocess.PIPE, text=True)
            current = ByteReservation(directory)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'reserved')
                self.assertEqual(reserved_bytes(Path(directory)), 8)
                self.assertFalse(current.reserve(3, 10))
            finally:
                child.kill()
                child.wait(timeout=5)
                child.stdout.close()
            self.assertTrue(current.reserve(10, 10))
            self.assertEqual(reserved_bytes(Path(directory)), 10)
            current.release()
            current.release()
            self.assertEqual(reserved_bytes(Path(directory)), 0)
