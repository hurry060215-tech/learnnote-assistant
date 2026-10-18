"""Installed Windows two-version acceptance; synthetic data and loopback model only.

Snapshots stay local. Upload only the top-level report/log/PNG allowlist. The model
fixture verifies plumbing, never model quality. Force termination is cleanup, not
successful normal Close. No source backend is substituted for either executable.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rollback_seed', ROOT / 'scripts/native-version-rollback.py')
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)
native = seed.native


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def install(installer, destination):
    result = subprocess.run([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                             f'/DIR={destination}'], timeout=300, check=True, env=safe_environment(os.environ))
    return result.returncode


def installed_files(directory, expected, *, diagnostic_assets=False):
    notes = directory / '_internal/web/release-notes.json'
    release = json.loads(notes.read_text(encoding='utf-8-sig'))
    extension = directory / 'extension/manifest.json'
    manifest = json.loads(extension.read_text(encoding='utf-8-sig'))
    assert release['current'] == expected
    assert manifest['version'] == release.get('component_versions', {}).get('extension', expected)
    files = [directory / 'LearnNote.exe', notes, extension]
    for name in ['index.html', 'desk.js', 'task-diagnostic-export.js', 'task-diagnostic-export.css']:
        path = directory / '_internal/web' / name
        if diagnostic_assets or path.exists():
            files.append(path)
    return {str(p.relative_to(directory)).replace('\\', '/'): digest(p) for p in files}


def verify_api_owner(pid, port):
    assert type(pid) is int and 0 < pid <= 0xffffffff
    assert type(port) is int and 0 < port < 65536
    command = ("$ErrorActionPreference='Stop'; "
               f"$rows=@(Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction Stop); "
               "@($rows | ForEach-Object { @{pid=[int]$_.OwningProcess; address=[string]$_.LocalAddress} }) | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, check=True, timeout=30,
                            env=safe_environment(os.environ))
    records = json.loads(result.stdout)
    records = [records] if isinstance(records, dict) else records
    assert isinstance(records, list) and records and len(records) <= 4
    assert all(row['pid'] == pid and row['address'] in ('127.0.0.1', '::1') for row in records), 'API listener is not owned loopback'


def close_owned(process):
    """Normal WM_CLOSE to exactly one visible root owned by our live process."""
    if process.poll() is not None:
        raise AssertionError('Installed application exited before normal Close')
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    windows = []
    def collect(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid and user.IsWindowVisible(hwnd) and not user.GetWindow(hwnd, 4):
            windows.append(hwnd)
        return True
    user.EnumWindows(callback(collect), 0)
    assert len(windows) == 1, 'Normal Close requires exactly one owned visible root'
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(windows[0], ctypes.byref(pid))
    assert pid.value == process.pid and process.poll() is None
    if not user.PostMessageW(windows[0], 0x0010, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    assert process.wait(timeout=30) == 0, 'Normal installed Close failed'


def safe_environment(environment):
    env = dict(environment)
    for name in list(env):
        upper = name.upper()
        if upper.startswith(('GH_', 'GITHUB_', 'ACTIONS_', 'SIGNING_', 'CSC_', 'APPLE_', 'AZURE_', 'AWS_')) or upper.endswith('_TOKEN') or any(
                word in upper for word in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN', 'PASSWORD', 'SECRET', 'PROXY')):
            env.pop(name)
    return env


def installed_environment(data, port):
    env = safe_environment(native.isolated_environment(data, port))
    env.pop('PYTHONPATH', None)
    return env


def verify_health(health, version, data):
    assert health['ok'] and health['app_version'] == version
    assert Path(health['data_paths']['root']).resolve() == data.resolve(), 'API root is not owned synthetic data'


def reap_owned(process):
    """Best-effort force cleanup after failure; every operation is independent."""
    errors = []
    if process.poll() is not None:
        return errors
    try:
        process.terminate()
    except BaseException as error:
        errors.append(error)
    try:
        process.wait(timeout=10)
    except BaseException as error:
        errors.append(error)
    if process.poll() is None:
        try:
            process.kill()
        except BaseException as error:
            errors.append(error)
        try:
            process.wait(timeout=10)
        except BaseException as error:
            errors.append(error)
    return errors


def cleanup_owned(process, api):
    errors = []
    if process is not None:
        try:
            close_owned(process)
        except BaseException as error:
            errors.append(error)
            errors.extend(reap_owned(process))
    if api is not None:
        try:
            api.session.close()
        except BaseException as error:
            errors.append(error)
    return errors


@contextmanager
def running(directory, data, output, phase, version):
    port, debug_port = native.free_port(), native.free_port()
    env = installed_environment(data, port)
    process = api = None
    failure = None
    with (output / f'{phase}.log').open('w', encoding='utf-8') as log:
        try:
            process = subprocess.Popen([str(directory / 'LearnNote.exe'), '--port', str(port),
                                        '--webview-debug-port', str(debug_port)], cwd=directory,
                                       env=env, stdout=log, stderr=log)
            api = native.Api(port)
            deadline = time.monotonic() + 90
            while True:
                if process.poll() is not None:
                    raise AssertionError('Installed application exited during startup')
                try:
                    health = api.call('GET', '/health').json()
                    verify_health(health, version, data)
                    break
                except (ConnectionError, native.requests.RequestException):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Installed API did not become ready')
                    time.sleep(.2)
            verify_api_owner(process.pid, port)
            assert process.poll() is None
            yield api, debug_port, process.pid
        except BaseException as error:
            failure = error
            raise
        finally:
            errors = cleanup_owned(process, api)
            if errors:
                if failure is None:
                    raise errors[0]
                print('Secondary owned cleanup failed: ' + ', '.join(type(e).__name__ for e in errors), file=sys.stderr)


@contextmanager
def local_model():
    """No external model. Capture only synthetic payload counts/hash, never headers."""
    calls = []
    note = '# Synthetic rollback captions\n\n' + '\n\n'.join(c['text'] for c in seed.CUES)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.send_error(400); return
            if self.path != '/v1/chat/completions' or not 0 < size <= 256 * 1024:
                self.send_error(400); return
            raw = self.rfile.read(size)
            try:
                payload = json.loads(raw)
                text = json.dumps(payload['messages'], ensure_ascii=False)
            except (ValueError, KeyError, TypeError):
                self.send_error(400); return
            if not all(c['text'] in text for c in seed.CUES) or 'image_url' in text or len(calls) >= 4:
                self.send_error(400); return
            calls.append({'bytes': size, 'sha256': hashlib.sha256(raw).hexdigest(),
                          'saved_captions_present': True, 'images': False})
            body = json.dumps({'id': 'synthetic-completion', 'object': 'chat.completion',
                               'created': 0, 'model': 'synthetic-local', 'choices': [
                                   {'index': 0, 'message': {'role': 'assistant', 'content': note},
                                    'finish_reason': 'stop'}]}).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', calls
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


PRIVACY_SENTINEL = 'Authorization: Bearer SYNTHETIC_INSTALLED_PRIVATE_0216'


def verify_retry_diagnostic(value):
    assert PRIVACY_SENTINEL not in json.dumps(value)
    assert 'https://example.com/synthetic-rollback' not in json.dumps(value)
    assert 'Synthetic rollback captions' not in json.dumps(value)
    assert all(cue['text'] not in json.dumps(value) for cue in seed.CUES)
    current = [row for row in value['timings']['attempts'] if row['current'] is True]
    assert len(current) == 1
    stages = {row['stage']: row['status'] for row in current[0]['stages']}
    for name in ('subtitle_probe', 'download', 'media', 'transcript', 'visual', 'frames'):
        assert stages[name] == 'skipped', f'Unexpected processing stage: {name}'
    assert value['versions']['task_run_app'] is None
    assert value['model']['total_tokens'] is None
    return stages


def retained(api, ids):
    task = api.call('GET', f'/api/tasks/{ids["task_id"]}').json()['task']
    material = api.call('GET', f'/api/library/materials/{ids["material_id"]}/source').content
    annotations = api.call('GET', f'/api/personal/material/{ids["material_id"]}').json()['annotations']
    return {'transcript': api.call('GET', f'/api/tasks/{ids["task_id"]}/transcript').json(),
            'srt': hashlib.sha256(api.call('GET', f'/api/tasks/{ids["task_id"]}/exports/subtitles').content).hexdigest(),
            'material': hashlib.sha256(material).hexdigest(),
            'personal_text': sorted(x['text'] for x in annotations), 'title': task['title']}


def verify_snapshot(path, expected):
    assert seed.inventory(path) == expected, 'Original stopped snapshot changed'


def run_ui(output, debug, origin, task_id, pid, version, *, startup_only=False):
    subprocess.run(['node', str(ROOT / 'scripts/installed-diagnostic-acceptance.cjs'),
                    str(output), str(debug), origin, task_id, str(pid), '--expected-version', version,
                    *(['--startup-only'] if startup_only else [])], check=True, timeout=180, env=safe_environment(os.environ))


def exercise(args, output):
    run = Path('D:/LearnNoteUpgradeSmoke') / ('installed-' + uuid.uuid4().hex)
    directory, data = run / 'app', run / 'external-data'
    directory.mkdir(parents=True); data.mkdir()
    config = directory / 'learnnote-config.json'
    sentinel = data / 'user-data-must-survive.txt'
    sentinel.write_bytes(b'synthetic-installed-upgrade-sentinel\n')
    report = {'passed': False, 'scope': 'actual installed Windows apps; synthetic captions and deterministic loopback model',
              'snapshots_local_only': True, 'run_root': str(run), 'phases': [],
              'expected_versions': {'previous': args.expected_previous_version, 'current': args.expected_current_version}}
    installed = False
    failure = None
    try:
        report['installers'] = {name: digest(path) for name, path in [('previous', args.previous_installer), ('current', args.current_installer)]}
        report['previous_install_exit'] = install(args.previous_installer, directory)
        installed = True
        report['previous_files'] = installed_files(directory, args.expected_previous_version)
        write_json(config, {'data_dir': str(data), 'upgrade_sentinel': 'synthetic-installed-upgrade'})
        config_before = config.read_bytes()
        (run / 'pre-upgrade-config.json').write_bytes(config_before)
        (data / 'config').mkdir(exist_ok=True)
        write_json(data / 'config/update-preferences.json', {'auto_check': False, 'auto_download': False})
        with running(directory, data, output, 'previous', args.expected_previous_version) as (api, debug, pid):
            ids = seed.seed(api)
            api.call('POST', f'/api/personal/material/{ids["material_id"]}', json={'text': PRIVACY_SENTINEL})
            before = retained(api, ids)
            run_ui(output, debug, api.origin, ids['task_id'], pid, args.expected_previous_version, startup_only=True)
        report['phases'].append('previous_exact_version_started_and_closed_normally')
        report['config_sha256'] = hashlib.sha256(config_before).hexdigest()
        report['pre_upgrade_inventory'] = seed.snapshot(data, run / 'pre-upgrade-snapshot')
        report['current_install_exit'] = install(args.current_installer, directory)
        assert config.read_bytes() == config_before, 'Installer changed original config'
        assert seed.inventory(data) == report['pre_upgrade_inventory'], 'Installer changed old data bytes'
        report['current_files'] = installed_files(directory, args.expected_current_version, diagnostic_assets=True)
        with running(directory, data, output, 'current', args.expected_current_version) as (api, debug, pid):
            assert retained(api, ids) == before, 'Upgraded app changed original retained evidence'
            transcript_path = Path(api.call('GET', f'/api/tasks/{ids["task_id"]}').json()['task']['transcript_path'])
            transcript_before = (digest(transcript_path), transcript_path.stat().st_mtime_ns)
            # Native WebView2, actual installed UI/API, no API response mocks.
            run_ui(output, debug, api.origin, ids['task_id'], pid, args.expected_current_version)
            assert retained(api, ids) == before, 'Read-only preview altered saved source'
            with local_model() as (endpoint, calls):
                api.call('POST', f'/api/tasks/{ids["task_id"]}/retry-summary', json={
                    'content_mode': 'text', 'visual_understanding': False, 'use_saved_connection': False,
                    'llm_base_url': endpoint, 'llm_model': 'synthetic-local'})
                deadline = time.monotonic() + 90
                while True:
                    task = api.call('GET', f'/api/tasks/{ids["task_id"]}').json()['task']
                    if task['status'] in ('success', 'failed', 'cancelled'):
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Installed saved-caption retry did not finish')
                    time.sleep(.2)
                assert task['status'] == 'success', task.get('error_code')
                assert task['summary_source'] == 'text-llm'
                note = api.call('GET', f'/api/tasks/{ids["task_id"]}/exports/markdown').content
                assert all(cue['text'].encode('utf-8') in note for cue in seed.CUES)
                report['retry_note_sha256'] = hashlib.sha256(note).hexdigest()
                assert calls, 'Retry never reached deterministic loopback model'
                report['loopback_model_calls'] = calls
            assert retained(api, ids) == before
            assert (digest(transcript_path), transcript_path.stat().st_mtime_ns) == transcript_before
            report['retry_task'] = {'status': task['status'], 'phase': task['phase'], 'summary_source': task['summary_source']}
            report['transcript_bytes_and_mtime_preserved'] = True
            diagnostic = api.call('GET', f'/api/tasks/{ids["task_id"]}/exports/diagnostics?format=json').json()
            report['retry_stages'] = verify_retry_diagnostic(diagnostic)
            report['diagnostic'] = diagnostic
        report['phases'].append('current_exact_version_started_and_closed_normally')
        assert config.read_bytes() == config_before, 'Application changed preserved config'
        report['post_upgrade_inventory'] = seed.snapshot(data, run / 'post-upgrade-snapshot')
        report['uninstall_exit'] = subprocess.run([str(directory / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], check=True, timeout=180, env=safe_environment(os.environ)).returncode
        installed = False
        assert seed.inventory(data) == report['post_upgrade_inventory'], 'Uninstall modified external data'
        assert sentinel.read_bytes() == b'synthetic-installed-upgrade-sentinel\n'
        report['passed'] = True
    except BaseException as error:
        failure = error
        report['failure_type'] = type(error).__name__
        raise
    finally:
        # Preserve and recheck the stopped original snapshot even after a failed run.
        secondary = []
        if 'pre_upgrade_inventory' in report:
            try:
                verify_snapshot(run / 'pre-upgrade-snapshot', report['pre_upgrade_inventory'])
                assert digest(run / 'pre-upgrade-config.json') == report['config_sha256']
                report['pre_upgrade_snapshot_reverified'] = True
            except BaseException as error:
                report['pre_upgrade_snapshot_reverified'] = False
                report['passed'] = False
                secondary.append(error)
        try:
            write_json(output / 'installed-upgrade-report.json', report)
        except BaseException as error:
            secondary.append(error)
        if installed:
            print('Installation retained for failure inspection; owned app cleanup was attempted.', file=sys.stderr)
        if secondary:
            if failure is None:
                raise secondary[0]
            print('Secondary finalization failed: ' + ', '.join(type(e).__name__ for e in secondary), file=sys.stderr)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous-installer', type=Path, required=True)
    parser.add_argument('--current-installer', type=Path, required=True)
    parser.add_argument('--expected-previous-version', required=True)
    parser.add_argument('--expected-current-version', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Actual installed acceptance requires Windows')
    for name in ('previous_installer', 'current_installer'):
        value = getattr(args, name).resolve(strict=True)
        assert value.is_file() and value.suffix.lower() == '.exe'
        setattr(args, name, value)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    exercise(args, args.output_dir.resolve())


if __name__ == '__main__':
    main()
