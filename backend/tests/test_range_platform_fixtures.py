"""Offline provider-shaped range admission and real caption processor contracts.

The same source/range records drive the rendered Edge sidepanel fixture. Chrome
transport is mocked there; here HTTP admission, disk artifacts and caption
processing are real. No provider, media download, ASR or model is used.
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import main
from app.processor import process_current_page_task
from app.storage import get_task

CASES = json.loads((Path(__file__).resolve().parents[2] / 'scripts' / 'fixtures' / 'range-platform-cases.json').read_text(encoding='utf-8'))


class RangePlatformFixtureTests(unittest.TestCase):
    def setUp(self):
        self.worker = os.environ.get('LEARNNOTE_RANGE_FIXTURE_WORKER') == '1'
        if self.worker:
            self.client = TestClient(main.app)
            self.addCleanup(self.client.close)

    def isolated(self):
        # Set the complete data root BEFORE importing any application modules.
        # All catalog, knowledge, activation, model and task stores are owned by
        # this disposable subprocess; real indexing stays enabled.
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'LEARNNOTE_DATA_DIR': directory,
                   'LEARNNOTE_RANGE_FIXTURE_WORKER': '1', 'PYTHONPATH': 'backend'}
            code = """import runpy, unittest
scope = runpy.run_path('scripts/test-backend-offline.py')
with scope['offline_network']():
    suite = unittest.defaultTestLoader.loadTestsFromName(%r)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
""" % ('backend.tests.test_range_platform_fixtures.RangePlatformFixtureTests.' + self._testMethodName)
            result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
                                    env=env, text=True, encoding='utf-8', capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((Path(directory) / 'library.sqlite3').is_file(), 'Actual indexing must use the owned subprocess root')

    def payload(self, case):
        start, end = case['custom_range']['start'], case['custom_range']['end']
        cues = [{'start': 0, 'end': 10, 'text': 'OUTSIDE_BEFORE must never appear in selected evidence.'}]
        cues += [{'start': start + i * 10, 'end': min(start + (i + 1) * 10, case['duration']),
                  'text': f'SELECTED_{i:02} synthetic source evidence with a complete explanatory sentence.'} for i in range(math.ceil((case['duration'] - start) / 10))]
        cues += [{'start': case['duration'], 'end': case['duration'] + 10, 'text': 'OUTSIDE_AFTER must never appear in selected evidence.'}]
        return dict(page_url=case['page_url'], title=case['title'], mode='subtitle_only',
                    handoff_id='range-fixture-' + case['id'], browser_subtitles=cues,
                    active_video={'duration': case['duration'], 'current_time': case['current_time']},
                    learning_range=case['custom_range'],
                    options={'content_mode': 'subtitles', 'visual_understanding': False})

    def processing_cases(self):
        for case in CASES:
            for selection in ('chapter', 'custom'):
                yield {**case, 'id': case['id'] + '-' + selection}
            for minutes in (5, 15, 30):
                for duration in (600, 2400):
                    yield {**case, 'id': f"{case['id']}-current{minutes}-{duration}",
                           'duration': duration,
                           'custom_range': {'start': case['current_time'],
                                            'end': min(duration, case['current_time'] + minutes * 60)}}

    def test_provider_shaped_ranges_admit_process_and_export_only_selected_cues(self):
        if not self.worker:
            return self.isolated()
        for case in self.processing_cases():
            with self.subTest(platform=case['id']), \
                 patch('app.main.schedule_processing') as schedule, \
                 patch('app.processor.MediaDownloader') as download, \
                 patch('app.processor.maybe_download_page_subtitle') as subtitle_fetch, \
                 patch('app.processor.transcribe_audio') as asr, \
                 patch('app.processor.transcribe_audio_openai_compatible') as remote_asr, \
                 patch('app.processor.summarize_with_diagnostics') as summarize:
                payload = self.payload(case)
                response = self.client.post('/api/tasks/from-current-page', json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                task_id = response.json()['task_id']
                schedule.assert_called_once()
                self.assertIs(schedule.call_args.args[1], process_current_page_task)
                request = schedule.call_args.args[3]
                self.assertEqual(request.learning_range, case['custom_range'])
                self.assertEqual(request.page_url, case['page_url'])
                # Execute the exact admitted callback, replacing only async dispatch.
                process_current_page_task(task_id, request)
                task = get_task(task_id)
                self.assertEqual(task.status, 'success', task.error_detail)
                self.assertEqual(task.page_url, case['page_url'])
                self.assertEqual(task.learning_range, case['custom_range'])
                self.assertEqual(task.summary_source, 'subtitle-extract')
                transcript = json.loads(Path(task.transcript_path).read_text(encoding='utf-8'))
                start, end = case['custom_range']['start'], case['custom_range']['end']
                self.assertEqual(transcript['provenance']['original_time_offset'], start)
                self.assertEqual(transcript['provenance']['learning_range'], task.learning_range)
                self.assertEqual(transcript['provenance']['timestamp_origin'], 'selected_media_start')
                selected = [cue for cue in payload['browser_subtitles'] if start <= cue['start'] < cue['end'] <= end]
                self.assertEqual([(s['start'], s['end'], s['text']) for s in transcript['segments']],
                                 [(cue['start']-start, cue['end']-start, cue['text']) for cue in selected])
                self.assertTrue(all(case['custom_range']['start'] <= s['start'] + case['custom_range']['start'] < s['end'] + case['custom_range']['start'] <= case['custom_range']['end'] for s in transcript['segments']))
                for suffix in ('markdown', 'subtitles'):
                    exported = self.client.get(f'/api/tasks/{task_id}/exports/{suffix}')
                    self.assertEqual(exported.status_code, 200, exported.text)
                    if suffix == 'markdown':
                        from decimal import Decimal
                        self.assertIn(f'原视频 {Decimal(str(start)).normalize():f}–{Decimal(str(end)).normalize():f} 秒', exported.text)
                        self.assertIn(f'原视频时间 = 片段时间 + {Decimal(str(start)).normalize():f} 秒', exported.text)
                        self.assertIn('SRT 时间从片段 0 秒起', exported.text)
                    if suffix == 'subtitles':
                        from app.processor import parse_subtitle_or_none
                        srt = Path(task.subtitle_path)
                        self.assertEqual(exported.content, srt.read_bytes())
                        parsed = parse_subtitle_or_none(srt)
                        self.assertIsNotNone(parsed)
                        self.assertEqual([(cue.start, cue.end) for cue in parsed.segments],
                                         [(cue['start']-start, cue['end']-start) for cue in selected])
                    self.assertIn('SELECTED_00', exported.text)
                    self.assertIn(selected[-1]['text'], exported.text)
                    for cue in payload['browser_subtitles']:
                        if cue not in selected:
                            self.assertNotIn(cue['text'], exported.text)
                    self.assertNotIn('OUTSIDE_BEFORE', exported.text)
                    self.assertNotIn('OUTSIDE_AFTER', exported.text)
                for untouched in (download, subtitle_fetch, asr, remote_asr, summarize):
                    untouched.assert_not_called()

    def test_text_summary_exports_retain_the_same_range_context_without_new_source_calls(self):
        if not self.worker:
            return self.isolated()
        for case in CASES:
            with self.subTest(platform=case['id']), patch('app.main.schedule_processing') as schedule, \
                 patch('app.processor.MediaDownloader') as download, \
                 patch('app.processor.transcribe_audio_openai_compatible') as remote_asr, \
                 patch('app.processor.summarize_with_diagnostics') as summarize:
                payload = self.payload(case)
                payload['options']['content_mode'] = 'auto'
                original = json.dumps(payload, sort_keys=True)
                # Explicit deterministic summary seam; no provider request.
                summarize.side_effect = lambda title, transcript, *args, **kwargs: (
                    '# ' + title + '\n\n' + '\n\n'.join(cue.text for cue in transcript.segments), 'text-llm', '', [])
                response = self.client.post('/api/tasks/from-current-page', json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                task_id = response.json()['task_id']
                process_current_page_task(task_id, schedule.call_args.args[3])
                task = get_task(task_id)
                self.assertEqual(task.status, 'success', task.error_detail)
                self.assertEqual(task.summary_source, 'text-llm')
                summarize.assert_called_once()
                used = summarize.call_args.args[1]
                self.assertEqual(used.provenance['original_time_offset'], 300.25)
                self.assertEqual(used.provenance['learning_range'], case['custom_range'])
                self.assertEqual([(cue.start, cue.end) for cue in used.segments], [(i*10, (i+1)*10) for i in range(12)])
                exported = self.client.get(f'/api/tasks/{task_id}/exports/markdown')
                self.assertEqual(exported.status_code, 200, exported.text)
                self.assertEqual(exported.text.count('选定范围：原视频 300.25–420.75 秒'), 1)
                self.assertIn('原视频时间 = 片段时间 + 300.25 秒', exported.text)
                self.assertIn('SRT 时间从片段 0 秒起', exported.text)
                self.assertNotIn('OUTSIDE_', exported.text)
                self.assertEqual(json.dumps(payload, sort_keys=True), original)
                download.assert_not_called()
                remote_asr.assert_not_called()

    def test_same_handoff_cannot_change_provider_part_page_or_selected_range(self):
        if not self.worker:
            return self.isolated()
        for case in CASES:
            with self.subTest(platform=case['id']), patch('app.main.schedule_processing') as schedule:
                payload = self.payload(case)
                first = self.client.post('/api/tasks/from-current-page?defer=true', json=payload)
                self.assertEqual(first.status_code, 200, first.text)
                changed_url = {'bilibili': case['page_url'].replace('p=2', 'p=3'),
                               'youtube': case['page_url'].replace('abcdefghijk', 'zyxwvutsrqp'),
                               'html5': case['page_url'] + '-other'}[case['id']]
                for changes in ({'page_url': changed_url}, {'learning_range': {'start': 300.25, 'end': 420.5}}):
                    conflict = self.client.post('/api/tasks/from-current-page?defer=true', json={**payload, **changes})
                    self.assertEqual(conflict.status_code, 409, conflict.text)
                    self.assertEqual(conflict.json()['detail']['code'], 'handoff_id_conflict')
                schedule.assert_not_called()
                self.assertEqual(get_task(first.json()['task_id']).learning_range, case['custom_range'])
