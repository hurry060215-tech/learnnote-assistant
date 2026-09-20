from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.media import _run, media_cancellation


class MediaProcessCancelTests(unittest.TestCase):
    def test_cancellation_kills_an_already_running_child(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'started'
            command = [sys._base_executable, '-c', 'import sys,time;from pathlib import Path;Path(sys.argv[1]).touch();time.sleep(30)', str(marker)]
            children = []
            real_popen = subprocess.Popen
            def launch(*args, **kwargs):
                child = real_popen(*args, **kwargs)
                children.append(child)
                return child
            def cancelled():
                if marker.exists():
                    raise RuntimeError('test cancellation')
            started = time.monotonic()
            with patch('app.media.subprocess.Popen', side_effect=launch):
                with self.assertRaisesRegex(RuntimeError, 'test cancellation'):
                    with media_cancellation(cancelled):
                        _run(command, 'child failed')
            self.assertTrue(marker.exists())
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNotNone(children[0].poll())
