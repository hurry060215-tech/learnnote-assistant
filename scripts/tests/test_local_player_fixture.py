"""Fractional player acceptance must not use the 1fps reliability fixture."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LocalPlayerFixtureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') or importlib.util.find_spec('imageio_ffmpeg'), 'FFmpeg required')
    def test_actual_30fps_source_and_fractional_clips_keep_timing_tolerance(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/local-player-fixture.py'),
                                     '--data-dir', directory, '--seed-only'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(report['offline_network'])
            self.assertEqual(report['media_frame_rate'], 30)
            for name, expected in (('source', 20), ('clip', 10.5), ('nested', 5.25)):
                self.assertLess(abs(report['timing_seconds'][name] - expected), .15, report)
            quantized = report['one_fps_quantization']
            self.assertEqual(quantized['frame_rate'], 1)
            self.assertEqual(quantized['requested_seconds'], 10.5)
            self.assertTrue(quantized['api_distinguishes_requested_and_encoded'])
            self.assertGreater(abs(quantized['actual_encoded_seconds'] - 10.5), .15)
            self.assertEqual(quantized['learning_range'], {
                'start': 5.25, 'end': 15.75, 'original_start': 5.25, 'original_end': 15.75})
            self.assertEqual([(cue['start'], cue['end'], cue['text']) for cue in quantized['relative_cues']],
                             [(0, 5.25, 'SYNTHETIC_SECOND: This synthetic lesson keeps the selected segment within its requested time bounds.'), (5.25, 10.5, 'SYNTHETIC_THIRD: This synthetic lesson explains why encoded padding is not additional source evidence.')])
            self.assertEqual(quantized['nested_padding_rejections'], [
                {'start':10.5,'end':11,'status':422}, {'start':0,'end':10.500000001,'status':422},
                {'start':0,'end':10.505,'status':422}])
            preview = report['preview_lifecycle']
            self.assertEqual((preview['pending_status'],preview['partial_status']), (409,409))
            for key in ('ready_during_summary','equals_selected_clip','differs_from_parent','same_range_rerun_reused_clip','full_source_rerun_unchanged'):
                self.assertTrue(preview[key], preview)
            self.assertLess(abs(preview['served_duration'] - 10.5), .15)
            self.assertEqual(preview['cache_control'], 'no-store')
            nested = preview['nested_pipeline']
            self.assertEqual(nested['status'], 'success')
            self.assertTrue(nested['evidence_can_summarize'])
            self.assertEqual(nested['learning_range'], {
                'start':0, 'end':5.25, 'original_start':5.25, 'original_end':10.5})
            self.assertLess(abs(nested['duration'] - 5.25), .15)
            self.assertEqual([(cue['start'],cue['end'],cue['text']) for cue in nested['relative_cues']], [
                (0,5.25,'SYNTHETIC_SECOND: This synthetic lesson keeps the selected segment within its requested time bounds.')])
            self.assertNotEqual(report['source_id'], report['other_id'])
            self.assertEqual(len(report['source_artifacts']), 2)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_delayed_http_route_settlement_is_owned_and_teardown_safe(self):
        result = subprocess.run(['node', str(ROOT / 'scripts/tests/local-player-route-gate.test.cjs')],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nonempty_fixture_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / 'keep.txt'
            sentinel.write_text('retain', encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/local-player-fixture.py'),
                                     '--data-dir', directory, '--seed-only'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'retain')


if __name__ == '__main__':
    unittest.main()
