"""Exercise the actual process-boundary harness on short synthetic media."""
import json
import os
import contextlib
import importlib.util
import io
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

    def test_failure_report_echoes_bounded_worker_logs(self):
        spec = importlib.util.spec_from_file_location('interrupted_reliability', ROOT / 'scripts/interrupted-task-reliability.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / 'start.log').write_text('synthetic checkpoint ready', encoding='utf-8')
            (output / 'recover.log').write_text('DO_NOT_PRINT_OLD_PREFIX' + 'x' * 70000 + '\n真实回溯 synthetic failure', encoding='utf-8')
            capture = io.StringIO()
            with contextlib.redirect_stderr(capture):
                try:
                    raise RuntimeError('synthetic worker failure')
                except RuntimeError as error:
                    module.record_failure(output, 'parent', error)
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'fail')
            self.assertEqual(report['error_type'], 'RuntimeError')
            self.assertIn('synthetic worker failure', report['traceback'])
            self.assertIn('真实回溯 synthetic failure', capture.getvalue())
            self.assertIn('synthetic checkpoint ready', capture.getvalue())
            self.assertNotIn('DO_NOT_PRINT_OLD_PREFIX', capture.getvalue())

    def test_failed_worker_preserves_its_traceback_before_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/interrupted-task-reliability.py'),
                                     '--output-dir', str(output), '--worker', 'recover'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30,
                                    env={**os.environ, 'LEARNNOTE_DATA_DIR': str(output / 'data')})
            self.assertNotEqual(result.returncode, 0)
            report = json.loads((output / 'worker-recover-failure.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'fail')
            self.assertEqual(report['error_type'], 'FileNotFoundError')
            self.assertIn('interrupted.json', report['traceback'])

    def test_workflow_preserves_only_small_top_level_recovery_evidence(self):
        workflow = (ROOT / '.github/workflows/reliability.yml').read_text(encoding='utf-8')
        paths = [line.strip() for line in workflow.splitlines() if line.strip().startswith('build/reliability/interrupted-local-task/')]
        self.assertEqual(paths, ['build/reliability/interrupted-local-task/*.json',
                                 'build/reliability/interrupted-local-task/*.log'])
