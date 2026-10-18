"""Offline contracts for the actual installed acceptance runner."""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('installed_upgrade', ROOT / 'scripts/installed-upgrade-acceptance.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class InstalledUpgradeTests(unittest.TestCase):
    """Installed harness contracts requiring only requests and the standard library."""

    def test_child_environment_excludes_release_and_provider_credentials(self):
        private = {'GH_TOKEN': 'private', 'GITHUB_TOKEN': 'private', 'SIGNING_CERT_BASE64': 'private',
                   'SIGNING_CERT_PASSWORD': 'private', 'LLM_API_KEY': 'private', 'OPENAI_API_KEY': 'private', 'HTTPS_PROXY': 'private', 'ACTIONS_RUNTIME_TOKEN': 'private', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'private', 'HF_TOKEN': 'private'}
        with patch.dict(os.environ, private):
            env = runner.installed_environment(Path('/synthetic/data'), 8765)
        self.assertFalse(set(private) & set(env))
        self.assertNotIn('PYTHONPATH', env)
        self.assertEqual(env['HF_HUB_OFFLINE'], '1')

    def test_api_listener_requires_exact_pid_and_loopback(self):
        for rows, accepted in [([{'pid': 123, 'address': '127.0.0.1'}], True),
                               ([{'pid': 124, 'address': '127.0.0.1'}], False),
                               ([{'pid': 123, 'address': '0.0.0.0'}], False), ([], False)]:
            with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(rows))) as call:
                if accepted: runner.verify_api_owner(123, 8765)
                else:
                    with self.assertRaises(AssertionError): runner.verify_api_owner(123, 8765)
                self.assertTrue(call.call_args.kwargs['check'])
                self.assertEqual(call.call_args.kwargs['timeout'], 30)

    def test_health_rejects_wrong_data_root_before_seed(self):
        value = {'ok': True, 'app_version': '0.2.16', 'data_paths': {'root': '/owned'}}
        runner.verify_health(value, '0.2.16', Path('/owned'))
        with self.assertRaisesRegex(AssertionError, 'owned synthetic'):
            runner.verify_health(value, '0.2.16', Path('/other'))
        with self.assertRaises(AssertionError):
            runner.verify_health(value, '0.2.15', Path('/owned'))

    def test_constructor_failure_still_closes_owned_process_and_preserves_primary(self):
        primary = RuntimeError('constructor')
        process = Mock()
        with TemporaryDirectory() as tmp, patch.object(runner.subprocess, 'Popen', return_value=process), \
                patch.object(runner.native, 'Api', side_effect=primary), \
                patch.object(runner, 'cleanup_owned', return_value=[RuntimeError('secondary')]) as cleanup:
            with self.assertRaises(RuntimeError) as caught:
                with runner.running(Path(tmp), Path(tmp), Path(tmp), 'old', '0.2.15'):
                    self.fail('unreachable')
            self.assertIs(caught.exception, primary)
            cleanup.assert_called_once_with(process, None)

    def test_force_cleanup_is_failure_and_session_cleanup_is_independent(self):
        process = Mock(); process.poll.return_value = None
        primary = RuntimeError('normal close')
        process.terminate.side_effect = RuntimeError('terminate')
        api = SimpleNamespace(session=Mock())
        with patch.object(runner, 'close_owned', side_effect=primary):
            errors = runner.cleanup_owned(process, api)
        self.assertIs(errors[0], primary)
        self.assertEqual(len(errors), 2)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        api.session.close.assert_called_once()

    def test_force_reap_kills_after_terminate_and_wait_failures(self):
        process = Mock(); process.poll.return_value = None
        primary = RuntimeError('terminate')
        process.terminate.side_effect = primary
        process.wait.side_effect = [subprocess.TimeoutExpired('owned', 10), 0]
        errors = runner.reap_owned(process)
        self.assertIs(errors[0], primary)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_stopped_snapshot_recheck_detects_changed_original(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'original.txt').write_bytes(b'original')
            inventory = runner.seed.inventory(root)
            runner.verify_snapshot(root, inventory)
            (root / 'original.txt').write_bytes(b'changed')
            with self.assertRaisesRegex(AssertionError, 'snapshot changed'):
                runner.verify_snapshot(root, inventory)

    def test_actual_loopback_fixture_requires_reviewed_captions_and_no_images(self):
        import requests
        with runner.local_model() as (endpoint, calls):
            response = requests.post(endpoint + '/chat/completions', json={
                'messages': [{'role': 'user', 'content': '\n'.join(c['text'] for c in runner.seed.CUES)}]}, timeout=5)
            self.assertEqual(response.status_code, 200)
            self.assertIn(runner.seed.CUES[0]['text'], response.json()['choices'][0]['message']['content'])
            for payload in ({'messages': []}, {'messages': [{'content': 'image_url ' + ' '.join(c['text'] for c in runner.seed.CUES)}]}):
                self.assertEqual(requests.post(endpoint + '/chat/completions', json=payload, timeout=5).status_code, 400)
            self.assertEqual(len(calls), 1)
            self.assertEqual(set(calls[0]), {'bytes', 'sha256', 'saved_captions_present', 'images'})

    def test_retry_requires_skipped_media_and_unknown_historical_usage(self):
        stages = ['subtitle_probe', 'download', 'media', 'transcript', 'visual', 'frames']
        value = {'versions': {'task_run_app': None}, 'model': {'total_tokens': None},
                 'timings': {'attempts': [{'current': True, 'stages': [{'stage': name, 'status': 'skipped'} for name in stages]}]}}
        self.assertEqual(set(runner.verify_retry_diagnostic(value)), set(stages))
        value['timings']['attempts'][0]['stages'][0]['status'] = 'completed'
        with self.assertRaises(AssertionError):
            runner.verify_retry_diagnostic(value)

    def test_report_write_does_not_replace_install_failure(self):
        primary = RuntimeError('installer')
        with TemporaryDirectory() as tmp, patch.object(runner, 'install', side_effect=primary), \
                patch.object(runner, 'digest', return_value='hash'), \
                patch.object(runner, 'write_json', side_effect=RuntimeError('report')), \
                patch.object(runner, 'Path', side_effect=lambda value: Path(tmp) if value == 'D:/LearnNoteUpgradeSmoke' else Path(value)):
            args = SimpleNamespace(previous_installer=Path('old.exe'), current_installer=Path('new.exe'), expected_previous_version='0.2.15', expected_current_version='0.2.16')
            with self.assertRaises(RuntimeError) as caught:
                runner.exercise(args, Path(tmp))
            self.assertIs(caught.exception, primary)


class InstalledSourceRehearsalTests(unittest.TestCase):
    """Source-backend rehearsal; full release discovery retains this coverage."""

    def test_real_api_saved_caption_retry_keeps_original_evidence(self):
        # Source rehearsal only. Installed executable/UI evidence is a hosted gate.
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'; data.mkdir()
            (data / 'config').mkdir()
            runner.write_json(data / 'config/update-preferences.json', {'auto_check': False, 'auto_download': False})
            port = runner.native.free_port()
            env = runner.installed_environment(data, port)
            env['PYTHONPATH'] = str(ROOT / 'backend')
            bootstrap = """
import socket
_original_connect = socket.socket.connect
def local_connect(self, address):
    if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise AssertionError('Source rehearsal outbound connection forbidden')
    return _original_connect(self, address)
socket.socket.connect = local_connect
from app import processor
def forbidden(*args, **kwargs):
    raise AssertionError('Saved-caption retry must not download or transcribe')
processor.transcribe_with_task_progress = forbidden
processor.MediaDownloader = forbidden
import uvicorn, os
uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.environ['LEARNNOTE_BACKEND_ORIGIN'].rsplit(':', 1)[1]))
"""
            with (Path(tmp) / 'backend.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, '-c', bootstrap], env=env, cwd=ROOT, stdout=log, stderr=log)
                api = None
                failure = None
                try:
                    api = runner.native.Api(port)
                    deadline = time.monotonic() + 30
                    while True:
                        self.assertIsNone(process.poll(), 'Source backend exited')
                        try:
                            api.call('GET', '/health'); break
                        except runner.native.requests.RequestException:
                            if time.monotonic() >= deadline:
                                self.fail('Source backend startup deadline')
                            time.sleep(.05)
                    ids = runner.seed.seed(api)
                    before = runner.retained(api, ids)
                    task = api.call('GET', f'/api/tasks/{ids["task_id"]}').json()['task']
                    transcript = Path(task['transcript_path'])
                    original = (transcript.read_bytes(), transcript.stat().st_mtime_ns)
                    with runner.local_model() as (endpoint, calls):
                        api.call('POST', f'/api/tasks/{ids["task_id"]}/retry-summary', json={
                            'content_mode': 'text', 'visual_understanding': False, 'use_saved_connection': False,
                            'llm_base_url': endpoint, 'llm_model': 'synthetic-local'})
                        deadline = time.monotonic() + 30
                        while True:
                            task = api.call('GET', f'/api/tasks/{ids["task_id"]}').json()['task']
                            if task['status'] in ('success', 'failed', 'cancelled'): break
                            if time.monotonic() >= deadline: self.fail('Source retry deadline')
                            time.sleep(.05)
                        self.assertEqual(task['status'], 'success')
                        self.assertEqual(task['summary_source'], 'text-llm')
                        note = api.call('GET', f'/api/tasks/{ids["task_id"]}/exports/markdown').content
                        self.assertTrue(all(cue['text'].encode('utf-8') in note for cue in runner.seed.CUES))
                        self.assertEqual(len(calls), 1)
                    self.assertEqual(runner.retained(api, ids), before)
                    self.assertEqual((transcript.read_bytes(), transcript.stat().st_mtime_ns), original)
                    diagnostic = api.call('GET', f'/api/tasks/{ids["task_id"]}/exports/diagnostics?format=json').json()
                    runner.verify_retry_diagnostic(diagnostic)
                except BaseException as error:
                    failure = error
                    raise
                finally:
                    cleanup = runner.reap_owned(process)
                    if api is not None:
                        try: api.session.close()
                        except BaseException as error: cleanup.append(error)
                    if cleanup and failure is None: raise cleanup[0]


if __name__ == '__main__':
    unittest.main()
