"""Offline contracts for the actual installed acceptance runner."""
import importlib.util
import json
import os
import stat
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
            root = Path(tmp).resolve(); data = root / 'data'; data.mkdir()
            with self.assertRaises(RuntimeError) as caught:
                with runner.running(root, data, root, 'old', '0.2.15'):
                    self.fail('unreachable')
            self.assertIs(caught.exception, primary)
            cleanup.assert_called_once_with(process, None)

    def test_synthetic_desktop_exists_before_launch_without_changing_data(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); data = root / 'external-data'; data.mkdir()
            (data / 'sentinel').write_bytes(b'unchanged')
            before = runner.seed.inventory(data)
            env = runner.installed_environment(data, 8765)
            runner.prepare_installed_profile(data, env)
            home = root / 'external-data-home'; desktop = home / 'Desktop'
            self.assertTrue(desktop.is_dir())
            self.assertEqual(env['HOME'], str(home)); self.assertEqual(env['USERPROFILE'], str(home))
            (desktop / 'existing').write_bytes(b'preserved')
            runner.prepare_installed_profile(data, env)
            self.assertEqual((desktop / 'existing').read_bytes(), b'preserved')
            self.assertEqual(runner.seed.inventory(data), before)
            self.assertFalse((data / 'Desktop').exists())

    def test_profile_rejects_environment_escape_before_creating_folders(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); data = root / 'data'; data.mkdir()
            for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
                env = runner.installed_environment(data, 8765); env[key] = str(root / 'other')
                with self.assertRaisesRegex(AssertionError, 'environment escaped'):
                    runner.prepare_installed_profile(data, env)
                self.assertFalse((root / 'data-home').exists())

    def test_profile_rejects_existing_files(self):
        for target_name in ('home', 'desktop'):
            with self.subTest(target=target_name), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); data = root / 'data'; data.mkdir()
                home = root / 'data-home'; target = home
                if target_name == 'desktop': home.mkdir(); target = home / 'Desktop'
                target.write_bytes(b'keep')
                with self.assertRaisesRegex(AssertionError, 'real directory'):
                    runner.prepare_installed_profile(data, runner.installed_environment(data, 8765))
                self.assertEqual(target.read_bytes(), b'keep')

    def test_profile_rejects_real_symlink_paths(self):
        for target_name in ('home', 'desktop'):
            with self.subTest(target=target_name), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); data = root / 'data'; data.mkdir()
                home = root / 'data-home'; target = home
                if target_name == 'desktop': home.mkdir(); target = home / 'Desktop'
                outside = root / 'outside'; outside.mkdir()
                try: target.symlink_to(outside, target_is_directory=True)
                except OSError: self.skipTest('Host does not permit synthetic symlink creation')
                with self.assertRaisesRegex(AssertionError, 'real directory|reparse point|resolves elsewhere'):
                    runner.prepare_installed_profile(data, runner.installed_environment(data, 8765))
                self.assertEqual(list(outside.iterdir()), [])

    def test_profile_rejects_reparse_attribute_before_traversal(self):
        for target_name in ('home', 'desktop'):
            with self.subTest(target=target_name), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve(); data = root / 'data'; data.mkdir(); home = root / 'data-home'; home.mkdir()
                target = home
                if target_name == 'desktop': target = home / 'Desktop'; target.mkdir()
                original = Path.lstat
                def info(path, *args, **kwargs):
                    found = original(path, *args, **kwargs)
                    if path == target:
                        return SimpleNamespace(st_mode=found.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
                    return found
                with patch.object(Path, 'lstat', info), self.assertRaisesRegex(AssertionError, 'reparse point'):
                    runner.prepare_installed_profile(data, runner.installed_environment(data, 8765))
                if target_name == 'home': self.assertFalse((home / 'Desktop').exists())
                else: self.assertEqual(list(target.iterdir()), [])

    def test_profile_rejects_identity_change_during_desktop_creation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); data = root / 'data'; data.mkdir(); home = root / 'data-home'; home.mkdir()
            original = Path.mkdir
            def create(path, *args, **kwargs):
                if path == home / 'Desktop':
                    home.rename(root / 'prior-home'); original(home)
                return original(path, *args, **kwargs)
            with patch.object(Path, 'mkdir', create), self.assertRaisesRegex(AssertionError, 'directory changed'):
                runner.prepare_installed_profile(data, runner.installed_environment(data, 8765))

    def test_profile_failure_prevents_any_installed_process_launch(self):
        with TemporaryDirectory() as tmp, patch.object(runner.subprocess, 'Popen') as launch:
            root = Path(tmp).resolve(); data = root / 'data'; data.mkdir()
            (root / 'data-home').write_bytes(b'not a directory')
            with self.assertRaisesRegex(AssertionError, 'real directory'):
                with runner.running(root, data, root, 'current', '0.2.16'):
                    self.fail('unreachable')
            launch.assert_not_called()

    def test_profile_is_ready_before_both_old_and_new_process_launch(self):
        primary = RuntimeError('synthetic launch boundary')
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); data = root / 'data'; data.mkdir()
            def launch(*args, **kwargs):
                self.assertEqual(kwargs['env']['USERPROFILE'], str(root / 'data-home'))
                self.assertTrue((root / 'data-home/Desktop').is_dir())
                raise primary
            with patch.object(runner.subprocess, 'Popen', side_effect=launch) as child:
                for phase, version in [('previous', '0.2.15'), ('current', '0.2.16')]:
                    with self.assertRaises(RuntimeError) as caught:
                        with runner.running(root, data, root, phase, version): self.fail('unreachable')
                    self.assertIs(caught.exception, primary)
                self.assertEqual(child.call_count, 2)

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
