"""Exercise the actual process-boundary harness on short synthetic media."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InterruptedTaskReliabilityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'native FFmpeg required')
    def test_abrupt_process_exit_and_fresh_worker_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'acceptance'
            result = subprocess.run([
                sys.executable, str(ROOT / 'scripts/interrupted-task-reliability.py'),
                '--duration-seconds', '12', '--output-dir', str(output),
            ], capture_output=True, text=True, encoding='utf-8', timeout=120)
            logs = '\n'.join(path.read_text(encoding='utf-8') for path in output.glob('*.log'))
            self.assertEqual(result.returncode, 0, result.stderr + logs)
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'pass')
            self.assertEqual(report['interrupted_checkpoint'], 'visual_ready')
            self.assertEqual(report['recovery'], {'recovered': 1, 'waiting_for_context': 1})
            self.assertTrue(report['same_media_and_transcript_hashes'])
            self.assertTrue(report['same_intent_sequence_and_generation'])
            self.assertEqual(report['startup_order'], ['cleanup_completed', 'recovery_dispatched'])
            self.assertNotEqual(report['terminated_worker']['pid'], report['fresh_worker_pid'])
            self.assertNotEqual(report['terminated_worker']['exit_code'], 0)
            self.assertIn('transcript_after', report['artifact_mtimes_ns'])
            self.assertEqual(report['repeat_recovery_dispatched'], 0)
            self.assertFalse(report['network_calls_allowed'])
            self.assertEqual(report['summary_provider'], 'deterministic test fixture')

    def test_ci_requires_long_recovery_separately_from_completion(self):
        workflow = (ROOT / '.github/workflows/reliability.yml').read_text(encoding='utf-8')
        self.assertIn('python scripts/interrupted-task-reliability.py\n          --duration-seconds 3600', workflow)
        self.assertIn('python scripts/full-local-task-reliability.py', workflow)
