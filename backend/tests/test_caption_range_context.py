"""Selected caption provenance cannot expand or apply parent offsets twice."""
import unittest
from app.caption_extraction import selected_caption_context
from app.models import TranscriptResult, TranscriptSegment
from app.processor_state import ContentMismatchError


class CaptionRangeContextTests(unittest.TestCase):
    def transcript(self, **provenance):
        return TranscriptResult(source='browser-subtitle', full_text='Synthetic evidence.',
            segments=[TranscriptSegment(start=0, end=.2, text='Synthetic evidence.')], provenance=provenance)

    def test_decimal_requested_range_and_existing_offset_are_not_shifted_twice(self):
        source = self.transcript(original_time_offset=100.1, timestamp_origin='selected_media_start', retained='fixture')
        before = source.model_dump(mode='json')
        selected = {'start': .1, 'end': .3, 'original_start': 100.1, 'original_end': 100.3}
        actual, notice = selected_caption_context(source, selected)
        self.assertEqual(source.model_dump(mode='json'), before)
        self.assertEqual(actual.segments, source.segments)
        self.assertEqual(actual.provenance['original_time_offset'], 100.1)
        self.assertEqual(actual.provenance['learning_range'], selected)
        self.assertEqual(actual.provenance['retained'], 'fixture')
        self.assertIn('原视频 100.1–100.3 秒', notice)
        self.assertIn('片段时间 + 100.1 秒', notice)
        self.assertIn('SRT 时间从片段 0 秒起', notice)
        self.assertNotIn('100.2', notice)

    def test_production_float_endpoints_allow_only_representation_rounding(self):
        from decimal import Decimal
        start, end, parent = .3333333333333333, .6666666666666666, Decimal('1000.1')
        from pathlib import Path
        from contextlib import nullcontext
        import tempfile
        from unittest.mock import patch
        from app.models import TaskOptions, TaskRecord, MediaIntegrity
        from app.range_learning import create_range_task
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / 'source.mp4'
            media.write_bytes(b'synthetic path fixture; no media processing')
            parent_task = TaskRecord(id='source', source_type='local', title='Nested source', created_at='', updated_at='',
                media_path=str(media), media_integrity=MediaIntegrity(duration=20),
                learning_range={'original_start': float(parent)})
            child = parent_task.model_copy(update={'id': 'child'})
            with patch('app.range_learning.DATA_DIR', Path(directory)), \
                 patch('app.range_learning.task_state_transaction', side_effect=nullcontext), \
                 patch('app.range_learning.get_task', return_value=parent_task), \
                 patch('app.range_learning.create_task', return_value=child), \
                 patch('app.range_learning.update_task', side_effect=lambda key, **fields: child.model_copy(update=fields)), \
                 patch('app.range_learning.schedule_processing'):
                # Actual production range creation, with only persistence/dispatch mocked.
                selected = create_range_task('source', start, end, TaskOptions(), None).learning_range
            self.assertEqual(media.read_bytes(), b'synthetic path fixture; no media processing')
        source = self.transcript()
        actual, notice = selected_caption_context(source, selected)
        self.assertEqual(actual.segments, source.segments)
        self.assertEqual(actual.provenance['original_time_offset'], selected['original_start'])
        self.assertIn('1000.4333333333333–1000.7666666666667', notice)
        with self.assertRaises(ContentMismatchError):
            selected_caption_context(source, {**selected, 'original_end': selected['original_end'] + 1e-9})

    def test_browser_range_uses_request_bounds_without_physical_duration(self):
        actual, notice = selected_caption_context(self.transcript(), {'start': 5.25, 'end': 15.75})
        self.assertEqual(actual.provenance['original_time_offset'], 5.25)
        self.assertIn('原视频 5.25–15.75 秒', notice)
        self.assertIn('不代表文件编码时长', notice)

    def test_no_range_preserves_original_transcript_and_no_notice(self):
        source = self.transcript(retained='ordinary')
        actual, notice = selected_caption_context(source, {})
        self.assertIs(actual, source)
        self.assertEqual(notice, '')

    def test_malformed_nonfinite_negative_or_inconsistent_stored_bounds_fail_closed(self):
        valid = {'start': .1, 'end': .3, 'original_start': 100.1, 'original_end': 100.3}
        cases = [{**valid, key: value} for key in valid for value in (float('nan'), float('inf'), float('-inf'))]
        cases += [{'start': 0}, {'original_start': 10}, {'start': -.1, 'end': .3},
                  {'start': 2, 'end': 1}, {**valid, 'original_start': -100},
                  {**valid, 'original_end': 100.300000001},
                  {'start': 0, 'end': 1e308, 'original_start': 1e308},
                  {'start': 'invalid', 'end': 1}]
        for selected in cases:
            with self.subTest(selected=selected), self.assertRaises(ContentMismatchError):
                selected_caption_context(self.transcript(), selected)
