"""Controlled sampling regressions; these are not full-film/OCR quality scores."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.media import (MediaProcessingError, _adaptive_frame_plan, _average_hash,
    _sampling_coverage, _should_keep_sampled_frame, build_frame_grids,
    extract_frames_adaptive, file_sha256, media_cancellation)
from app.models import FrameSample, TaskOptions, TranscriptResult, VisualWindow
from app.runtime import ffmpeg_bin
from app.summarizer import build_visual_windows, select_vision_grid_entries
from app.visual_pipeline import _preserved_visual_evidence, extract_visual_evidence


class SamplingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / 'video.mp4'
        self.video.write_bytes(b'synthetic media')
        self.frame_dir = self.root / 'frames'
        self.calls = []

    def batch(self, _ffmpeg, _video, requests):
        self.calls.append([timestamp for timestamp, _ in requests])
        for timestamp, output in requests:
            Image.new('RGB', (64, 36), (timestamp * 7, 80, 120)).save(output)
        return True

    def patches(self, batch=None, duration=12):
        stack = ExitStack()
        stack.enter_context(patch('app.media.ffmpeg_bin', return_value='ffmpeg'))
        stack.enter_context(patch('app.media.probe_duration', return_value=duration))
        stack.enter_context(patch('app.media.detect_scene_change_timestamps', return_value=[]))
        stack.enter_context(patch('app.media._extract_frame_batch', side_effect=batch or self.batch))
        stack.enter_context(patch('app.media._extract_single_frame', return_value=False))
        return stack

    def metrics(self):
        return json.loads((self.frame_dir / 'frame_extraction_metrics.json').read_text())

    def test_small_graphic_color_and_operator_changes_survive_same_perceptual_hash(self):
        image = Image.new('RGB', (640, 360), 'white')
        ImageDraw.Draw(image).rectangle((40, 40, 180, 180), fill='black')
        original = self.root / 'original.png'
        image.save(original)
        for label, color, shape in [('graphic', 'red', (330, 210, 335, 225)),
                                    ('operator', 'black', (400, 270, 407, 271)),
                                    ('color', 'blue', (480, 210, 485, 225))]:
            with self.subTest(label=label):
                changed = image.copy()
                ImageDraw.Draw(changed).rectangle(shape, fill=color)
                path = self.root / f'{label}.png'
                changed.save(path)
                self.assertEqual(_average_hash(original), _average_hash(path))
                self.assertNotEqual(original.read_bytes(), path.read_bytes())
                self.assertTrue(_should_keep_sampled_frame(current_hash=file_sha256(path),
                    timestamp=2, last_hash=file_sha256(original), last_kept_timestamp=0, coverage_gap=5))

    def test_endpoints_budget_and_full_timeline_distribution(self):
        for budget in (0, 1, 2, 3, 60):
            plan = _adaptive_frame_plan(3600, 1, budget, [], [40, 50, 60])
            times = [point for point, _ in plan]
            self.assertLessEqual(len(times), budget)
            self.assertEqual(times, sorted(set(times)))
            if budget:
                self.assertEqual(times[0], 0)
            if budget >= 2:
                self.assertEqual(times[-1], 3599)
            if budget == 60:
                self.assertTrue(any(1500 < point < 2100 for point in times))
                self.assertTrue(any(2800 < point < 3300 for point in times))
            samples = [FrameSample(path='', timestamp=point) for point in times]
            report = _sampling_coverage(3600, 1, budget, plan, samples, [], [40, 50, 60])
            self.assertTrue(report['budget_limited'])
            self.assertEqual(report['missing_endpoint_timestamps'], [0, 3599] if budget == 0 else [3599] if budget == 1 else [])
        self.assertEqual([point for point, _ in _adaptive_frame_plan(.2, 10, 2, [], None)], [0])
        self.assertEqual([point for point, _ in _adaptive_frame_plan(12, 10, 60, [], None)], [0, 10, 11])
        plan = _adaptive_frame_plan(120, 10, 3, [], [40, 50, 60])
        report = _sampling_coverage(120, 10, 3, plan, [FrameSample(path='', timestamp=t) for t, _ in plan], [], [40, 50, 60])
        self.assertEqual(report['omitted_anchor_timestamps'], [40, 60])

    def test_legacy_cache_and_images_survive_upgrade_and_changed_source(self):
        self.frame_dir.mkdir()
        old = self.frame_dir / 'frame_0000_000000.jpg'
        Image.new('RGB', (64, 36), 'red').save(old)
        cache = self.frame_dir / 'frame_cache.json'
        cache.write_text('{"signature":{"extractor_version":"adaptive-batch-v2"}}')
        before = {path: path.read_bytes() for path in (old, cache)}
        with self.patches():
            first, samples = extract_frames_adaptive(self.video, self.frame_dir, 10)
            first_bytes = {path: path.read_bytes() for path in first}
            second, _ = extract_frames_adaptive(self.video, self.frame_dir, 10)
            self.assertEqual(second, first)
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(self.metrics()['cached_frame_count'], 3)
            self.video.write_bytes(b'changed synthetic media')
            extract_frames_adaptive(self.video, self.frame_dir, 5)
        for path, content in {**before, **first_bytes}.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual([sample.timestamp for sample in samples], [0, 10, 11])
        self.assertFalse(list(self.frame_dir.glob('.extract-*')))

    def test_same_signature_cache_loss_and_encoder_change_do_not_replace_evidence(self):
        with self.patches():
            first, _ = extract_frames_adaptive(self.video, self.frame_dir, 10)
        before = {path: path.read_bytes() for path in first}
        for cache in self.frame_dir.glob('frame_cache_v3_*.json'):
            cache.write_text('truncated')
        def other_encoder(_ffmpeg, _video, requests):
            for _, output in requests:
                Image.new('RGB', (64, 36), 'white').save(output)
            return True
        with self.patches(other_encoder):
            second, _ = extract_frames_adaptive(self.video, self.frame_dir, 10)
        self.assertTrue(set(first).isdisjoint(second))
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_partial_failure_is_retried_not_cached_as_a_duplicate(self):
        def partial(_ffmpeg, _video, requests):
            return self.batch(_ffmpeg, _video, [(t, p) for t, p in requests if t != 11])
        with self.patches(partial):
            extract_frames_adaptive(self.video, self.frame_dir, 10)
        report = self.metrics()
        self.assertEqual(report['failed_timestamps'], [11])
        self.assertEqual(report['sampling_coverage']['status'], 'incomplete')
        self.assertEqual(report['sampling_coverage']['missing_endpoint_timestamps'], [11])
        self.assertFalse(list(self.frame_dir.glob('frame_cache_v3_*.json')))
        with self.patches():
            _, samples = extract_frames_adaptive(self.video, self.frame_dir, 10)
        self.assertEqual([sample.timestamp for sample in samples], [0, 10, 11])
        self.assertEqual(self.metrics()['sampling_coverage']['missing_endpoint_timestamps'], [])

    def test_cancel_keeps_published_files_and_does_not_commit_cache(self):
        self.frame_dir.mkdir()
        old = self.frame_dir / 'legacy.jpg'
        old.write_bytes(b'previous evidence')
        cancelled = False
        def batch(*args):
            nonlocal cancelled
            self.batch(*args)
            cancelled = True
            return True
        def check():
            if cancelled:
                raise RuntimeError('cancelled fixture')
        with self.patches(batch), media_cancellation(check):
            with self.assertRaisesRegex(RuntimeError, 'cancelled fixture'):
                extract_frames_adaptive(self.video, self.frame_dir, 10)
        self.assertEqual(old.read_bytes(), b'previous evidence')
        self.assertFalse(list(self.frame_dir.glob('.extract-*')))
        self.assertFalse(list(self.frame_dir.glob('frame_cache_v3_*.json')))

    def test_grid_regeneration_preserves_original_url_and_timestamp(self):
        with self.patches():
            frames, _ = extract_frames_adaptive(self.video, self.frame_dir, 10)
        first = build_frame_grids('fixture', frames, self.root / 'grids', 3, 3, 10, 12)
        old_path = Path(first[0].path)
        original = old_path.read_bytes()
        second = build_frame_grids('fixture', frames[1:], self.root / 'grids', 3, 3, 10, 12)
        self.assertNotEqual(second[0].path, first[0].path)
        self.assertEqual(old_path.read_bytes(), original)
        self.assertEqual(first[0].frame_timestamps, [0, 10, 11])
        self.assertEqual(second[0].start, 10)
        self.assertIn(old_path.name, first[0].url)
        self.assertFalse(list((self.root / 'grids').glob('.grid-*')))

    def legacy_index(self):
        self.frame_dir.mkdir()
        (self.root / 'grids').mkdir()
        frame = self.frame_dir / 'frame_0000_000000.jpg'
        grid = self.root / 'grids' / 'grid_000.jpg'
        Image.new('RGB', (64, 36), 'red').save(frame)
        Image.new('RGB', (320, 180), 'red').save(grid)
        sample = FrameSample(path=str(frame), timestamp=0, sha256=file_sha256(frame), important=True)
        window = VisualWindow(id='W001', index=1, start=0, end=20, frame_count=1,
            frame_timestamps=[0], grid_url='/original-grid', grid_path=str(grid))
        (self.frame_dir / 'frame_cache.json').write_text(json.dumps({'signature': {
            'extractor_version': 'adaptive-batch-v2', 'source_sha256': file_sha256(self.video)}}))
        index = self.root / 'visual_index.json'
        index.write_text(json.dumps({'frames': [sample.model_dump()], 'windows': [window.model_dump()]}))
        return index, frame, grid

    def test_legacy_windows_remain_pinned_without_extraction_or_grid_repacking(self):
        paths = self.legacy_index()
        original = {path: path.read_bytes() for path in paths}
        with patch('app.visual_pipeline.get_task', return_value=None), patch('app.visual_pipeline.check_cancel'), patch('app.visual_pipeline.update_task'), \
             patch('app.visual_pipeline.extract_frames_adaptive', side_effect=AssertionError('must reuse')), \
             patch('app.visual_pipeline.build_frame_grids', side_effect=AssertionError('must reuse')):
            result = extract_visual_evidence('fixture', self.video, 'title', '', TaskOptions(frame_interval=1), 12)
        windows = build_visual_windows(TranscriptResult(full_text='', segments=[]), result.grids)
        self.assertEqual([(w.id, w.start, w.end, w.grid_url) for w in windows], [('W001', 0, 20, '/original-grid')])
        self.assertTrue(result.metrics['published_sampling_reused'])
        self.assertEqual(result.metrics['frame_extraction']['cached_frame_count'], 1)
        self.assertEqual(result.metrics['frame_extraction']['ffmpeg_batch_process_count'], 0)
        for path, content in original.items():
            self.assertEqual(path.read_bytes(), content)

    def test_changed_source_or_corrupt_legacy_evidence_stops_before_rewrite(self):
        paths = self.legacy_index()
        before = {path: path.read_bytes() for path in paths}
        self.video.write_bytes(b'changed')
        with self.assertRaisesRegex(MediaProcessingError, '旧画面证据'):
            _preserved_visual_evidence(self.root, self.video)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_cache_cannot_skip_a_required_endpoint(self):
        with self.patches():
            extract_frames_adaptive(self.video, self.frame_dir, 10)
        cache = next(self.frame_dir.glob('frame_cache_v3_*.json'))
        content = json.loads(cache.read_text())
        content['entries'][-1].update(kept=False, name='')
        cache.write_text(json.dumps(content))
        with self.patches():
            _, samples = extract_frames_adaptive(self.video, self.frame_dir, 10)
        self.assertEqual([sample.timestamp for sample in samples], [0, 10, 11])
        self.assertEqual(len(self.calls), 2)

    def test_failed_atomic_publish_does_not_leave_a_partial_evidence_file(self):
        with self.patches(), patch('app.media.os.link', side_effect=OSError('fixture disk error')):
            with self.assertRaises(MediaProcessingError):
                extract_frames_adaptive(self.video, self.frame_dir, 10)
        self.assertFalse(list(self.frame_dir.glob('*.jpg')))
        self.assertFalse(list(self.frame_dir.glob('.extract-*')))
        self.assertFalse(list(self.frame_dir.glob('frame_cache_v3_*.json')))
        with self.patches():
            frames, _ = extract_frames_adaptive(self.video, self.frame_dir, 10)
        self.assertEqual(len(frames), 3)

    def test_published_current_policy_is_also_pinned_and_task_mapping_must_match(self):
        from types import SimpleNamespace
        index, _, _ = self.legacy_index()
        payload = json.loads(index.read_text())
        payload['performance'] = {'frame_extraction': {
            'extractor_version': 'adaptive-batch-v3-exact', 'source_sha256': file_sha256(self.video)}}
        index.write_text(json.dumps(payload))
        windows = [VisualWindow.model_validate(value) for value in payload['windows']]
        task = SimpleNamespace(visual_windows=windows, frame_grids=[])
        preserved = _preserved_visual_evidence(self.root, self.video, task)
        self.assertEqual(preserved.grids[0].end, 20)
        task.visual_windows = [windows[0].model_copy(update={'end': 30})]
        with self.assertRaisesRegex(MediaProcessingError, '旧画面证据'):
            _preserved_visual_evidence(self.root, self.video, task)
        self.assertEqual(json.loads(index.read_text())['windows'][0]['end'], 20)

    def test_pipeline_binds_cancellation_before_grid_publication(self):
        cancelled = False
        def check(_task):
            if cancelled:
                raise RuntimeError('cancelled fixture')
        def extract(*_args, **_kwargs):
            nonlocal cancelled
            from app.media import _cancel_check
            self.assertIsNotNone(_cancel_check.get())
            cancelled = True
            _cancel_check.get()()
        with patch('app.visual_pipeline.get_task', return_value=None), \
             patch('app.visual_pipeline.check_cancel', side_effect=check), \
             patch('app.visual_pipeline.update_task'), \
             patch('app.visual_pipeline.build_frame_grids') as build:
            with self.assertRaisesRegex(RuntimeError, 'cancelled fixture'):
                extract_visual_evidence('fixture', self.video, '', '', TaskOptions(), 12, extract_frames_fn=extract)
        build.assert_not_called()
        self.assertFalse((self.root / 'visual_index.json').exists())

    def test_resume_keeps_old_window_bindings_visible(self):
        from app.main import app
        from app.storage import create_task, get_task, task_dir, update_task
        with patch('app.storage.TASK_DIR', self.root / 'tasks'):
            task = create_task('local', 'Synthetic published note')
            media = task_dir(task.id) / 'source.mp4'
            media.write_bytes(b'synthetic source')
            window = VisualWindow(id='W001', index=1, start=4, end=9, frame_count=1,
                frame_timestamps=[4], grid_url='/old-grid', grid_path=str(task_dir(task.id) / 'grids' / 'old.jpg'))
            update_task(task.id, status='failed', phase='failed', media_path=str(media),
                visual_index_path=str(task_dir(task.id) / 'visual_index.json'), visual_windows=[window])
            before = get_task(task.id)
            with patch('app.main.schedule_processing'), patch('app.main.require_ready_note_model'):
                response = TestClient(app).post(f'/api/tasks/{task.id}/resume', json={})
            self.assertEqual(response.status_code, 200, response.text)
            after = get_task(task.id)
            self.assertEqual(after.visual_windows, before.visual_windows)
            self.assertEqual(after.visual_index_path, before.visual_index_path)

    def test_missing_or_empty_index_cannot_remap_published_windows(self):
        from types import SimpleNamespace
        index, _, _ = self.legacy_index()
        window = VisualWindow.model_validate(json.loads(index.read_text())['windows'][0])
        task = SimpleNamespace(visual_windows=[window], frame_grids=[], visual_index_path=str(index))
        index.unlink()
        with self.assertRaisesRegex(MediaProcessingError, '已发布画面索引缺失'):
            _preserved_visual_evidence(self.root, self.video, task)
        index.write_text('{"frames":[],"windows":[]}')
        with self.assertRaisesRegex(MediaProcessingError, '旧画面证据'):
            _preserved_visual_evidence(self.root, self.video, task)

    def test_failed_text_retry_keeps_published_visual_index_and_windows(self):
        from app.models import MediaIntegrity, TranscriptSegment
        from app.processor import _process_video_file
        from app.storage import create_task, get_task, task_dir, update_task
        from app.transcript_pipeline import TranscriptArtifacts
        from app.visual_pipeline import VisualArtifacts
        with patch('app.storage.TASK_DIR', self.root / 'tasks'):
            task = create_task('local', 'Synthetic note', options=TaskOptions(content_mode='text'))
            directory = task_dir(task.id)
            media = directory / 'media.mp4'
            media.write_bytes(b'synthetic source')
            note = directory / 'note.md'
            note.write_text('# Original W001 note')
            index = directory / 'visual_index.json'
            index.write_text('{"original":"visual evidence"}')
            window = VisualWindow(id='W001', index=1, start=4, end=9, frame_count=1,
                frame_timestamps=[4], grid_url='/old-grid', grid_path=str(directory / 'grids' / 'old.jpg'))
            update_task(task.id, status='failed', phase='failed', media_path=str(media), note_path=str(note),
                visual_index_path=str(index), visual_windows=[window])
            transcript = TranscriptResult(source='browser-subtitle', full_text='Synthetic transcript',
                segments=[TranscriptSegment(start=0, end=10, text='Synthetic transcript')])
            with patch('app.processor.probe_media_integrity', return_value=MediaIntegrity(status='ready', duration=10, has_audio=True, has_video=True)), \
                 patch('app.processor.normalize_video'), \
                 patch('app.processor.prepare_transcript', return_value=TranscriptArtifacts(transcript, '', None, '', directory / 'transcript.json')), \
                 patch('app.processor.extract_visual_evidence', return_value=VisualArtifacts([], [], [], '')), \
                 patch('app.processor.finish_note_task', side_effect=RuntimeError('synthetic summary failure')) as finish:
                with self.assertRaisesRegex(RuntimeError, 'synthetic summary failure'):
                    _process_video_file(task.id, media, task.title, '', TaskOptions(content_mode='text'))
            self.assertEqual(finish.call_args.args[5], [])
            self.assertEqual(index.read_text(), '{"original":"visual evidence"}')
            self.assertEqual(get_task(task.id).visual_windows, [window])
            self.assertEqual(note.read_text(), '# Original W001 note')

    def test_no_hardlink_filesystem_copy_is_exclusive_and_cleans_its_own_failure(self):
        import errno
        from app.media import _publish_evidence
        source = self.root / 'stage.jpg'
        target = self.root / 'final.jpg'
        source.write_bytes(b'complete synthetic image')
        unavailable = OSError(errno.ENOTSUP, 'fixture unsupported hardlink')
        with patch('app.media.os.link', side_effect=unavailable):
            _publish_evidence(source, target)
            _publish_evidence(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            source.write_bytes(b'different image')
            with self.assertRaises(MediaProcessingError):
                _publish_evidence(source, target)
            self.assertEqual(target.read_bytes(), b'complete synthetic image')
            other = self.root / 'new.jpg'
            def failed_copy(_source, destination):
                destination.write(b'partial')
                raise OSError('fixture full disk')
            with patch('app.media.shutil.copyfileobj', side_effect=failed_copy):
                with self.assertRaisesRegex(OSError, 'fixture full disk'):
                    _publish_evidence(source, other)
            self.assertFalse(other.exists())

    @unittest.skipUnless(ffmpeg_bin(), 'ffmpeg required for controlled video')
    def test_real_controlled_video_preserves_sampled_change_and_tail_with_bounded_batches(self):
        source = self.root / 'source'
        source.mkdir()
        for timestamp in range(8):
            image = Image.new('RGB', (640, 360), 'white')
            draw = ImageDraw.Draw(image)
            draw.rectangle((40, 40, 180, 180), fill='black')
            if timestamp == 2:
                draw.rectangle((330, 210, 335, 225), fill='red')
            if timestamp == 7:
                draw.rectangle((410, 210, 417, 225), fill='blue')
            image.save(source / f'{timestamp:02d}.png')
        video = self.root / 'controlled.mkv'
        subprocess.run([ffmpeg_bin(), '-hide_banner', '-loglevel', 'error', '-framerate', '1', '-i',
            str(source / '%02d.png'), '-c:v', 'ffv1', str(video)], check=True, capture_output=True)
        frames, samples = extract_frames_adaptive(video, self.frame_dir, 2, max_frames=60, batch_size=8)
        self.assertEqual([sample.timestamp for sample in samples], [0, 2, 4, 7])
        self.assertEqual(self.metrics()['planned_frame_count'], 5)
        self.assertEqual(self.metrics()['ffmpeg_batch_process_count'], 1)
        self.assertEqual(self.metrics()['ffmpeg_fallback_process_count'], 0)
        grids = build_frame_grids('fixture', frames, self.root / 'grids', 3, 3, 2, 8)
        self.assertEqual(len(grids), 1)
        self.assertEqual(len(select_vision_grid_entries(grids)), 1)
        self.assertEqual(len(select_vision_grid_entries(grids * 100)), 80)
        with patch('app.media._extract_frame_batch', side_effect=AssertionError('warm cache')):
            warm, _ = extract_frames_adaptive(video, self.frame_dir, 2, max_frames=60, batch_size=8)
        self.assertEqual(frames, warm)
