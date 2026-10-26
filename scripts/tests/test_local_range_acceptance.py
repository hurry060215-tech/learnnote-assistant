"""Actual source/range/full-media and abrupt recovery regression, no providers."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LocalRangeAcceptanceTests(unittest.TestCase):
    @unittest.skipUnless(all(shutil.which(name) for name in ('ffmpeg', 'ffprobe', 'node')), 'FFmpeg and Node required')
    def test_real_range_recovers_and_whole_upgrade_preserves_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'range'
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/local-range-acceptance.py'),
                                     '--output-dir', str(output)], capture_output=True,
                                    text=True, encoding='utf-8', timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'pass')
            self.assertEqual(report['selected_range'], {'start': 5, 'end': 15, 'original_start': 5, 'original_end': 15})
            for field in ('source_artifacts_unchanged', 'completed_clip_reused_hash_and_mtime',
                          'recovered_same_task_and_intent', 'whole_source_media_reused'):
                self.assertTrue(report[field], field)
            self.assertEqual(report['full_upgrade_evidence_count'], 4)
            self.assertEqual(report['selected_evidence'], ['EVIDENCE_2', 'EVIDENCE_3'])
            self.assertEqual([cue['text'] for cue in report['range_transcript_segments']], report['selected_evidence'])
            self.assertNotEqual(report['fresh_worker_pid'], report['terminated_worker']['pid'])
            self.assertNotEqual(report['terminated_worker']['exit_code'], 0)
            self.assertTrue(report['terminated_worker']['process_tree_reaped'])
            self.assertEqual(report['whole_upgrade_mode'], 'subtitles (no model)')
            self.assertIn('native player seek', report['not_tested'])
            self.assertEqual(len(report['source_artifacts']['media_path']['sha256']), 64)
            self.assertEqual(len(report['range_note_sha256']), 64)
            for name in ('interrupted.json', 'ready.json', 'terminated.json', 'start.log', 'recover.log'):
                self.assertTrue((output / name).is_file(), name)

    def test_existing_output_is_not_reused_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            sentinel = output / 'owned.txt'
            sentinel.write_text('preserve', encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/local-range-acceptance.py'),
                                     '--output-dir', str(output)], capture_output=True,
                                    text=True, encoding='utf-8', timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'preserve')


class DurableIntentWaitTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('local_range_gate', ROOT / 'scripts/local-range-acceptance.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.intent = {'sequence': 7, 'generation': 'synthetic-generation', 'state': 'running'}

    def test_successful_task_can_precede_durable_intent_finalization(self):
        from unittest.mock import patch
        rows = iter([self.intent, self.intent, {**self.intent, 'state': 'done'}])
        with patch.object(self.module.time, 'sleep') as sleep:
            result = self.module.wait_for_completed_intent(lambda: next(rows), self.intent)
        self.assertEqual(result['state'], 'done')
        self.assertEqual(sleep.call_count, 2)

    def test_identity_changes_failure_and_timeout_never_pass(self):
        for change in ({'sequence': 8}, {'generation': 'different'}, {'state': 'failed'}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                self.module.wait_for_completed_intent(lambda: {**self.intent, **change}, self.intent)
        with self.assertRaisesRegex(AssertionError, 'did not finalize'):
            self.module.wait_for_completed_intent(lambda: self.intent, self.intent, timeout=0)


class FullSourceTransportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_large_unicode_task_payload_uses_stdin_not_windows_argv(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('range_transport', ROOT / 'scripts/local-range-acceptance.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        records = {'whole': {'task': {'id': 'whole', 'learning_range': {}, 'title': '合成资料' * 20000}},
                   'range': {'task': {'id': 'range', 'learning_range': {'start': 5, 'end': 15}, 'source_task_id': 'whole'}}}
        run = subprocess.run
        with patch.object(module.subprocess, 'run', wraps=run) as observed:
            self.assertEqual(module.resolve_full_source(records, 'range'), 'whole')
        args, kwargs = observed.call_args
        self.assertLess(len(' '.join(args[0])), 4000)
        self.assertGreater(len(kwargs['input']), 32768)
        self.assertEqual(json.loads(kwargs['input']), records)
