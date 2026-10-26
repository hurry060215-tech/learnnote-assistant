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
            self.assertTrue(report['same_original_and_owned_subtitle_hashes'])
            self.assertTrue(report['same_intent_sequence_and_generation'])
            self.assertEqual(report['startup_order'], ['cleanup_completed', 'recovery_dispatched'])
            self.assertNotEqual(report['terminated_worker']['pid'], report['fresh_worker_pid'])
            self.assertNotEqual(report['terminated_worker']['exit_code'], 0)
            self.assertTrue(report['terminated_worker']['process_tree_reaped'])
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


class InterruptedNetworkGuardTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('interrupted_guard', ROOT / 'scripts/interrupted-task-reliability.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_self_pipe_requires_exact_code_socket_and_listener_endpoint(self):
        from types import SimpleNamespace
        sock, code = object(), object()
        local = {'csock': sock, 'lsock': SimpleNamespace(getsockname=lambda: ('127.0.0.1', 43210)),
                 'addr': '127.0.0.1', 'port': 43210}
        frame = SimpleNamespace(f_code=code, f_locals=local)
        check = self.module.is_socketpair_self_pipe
        self.assertTrue(check(sock, ('127.0.0.1', 43210), frame, code))
        self.assertFalse(check(sock, ('127.0.0.1', 43210), frame, object()))
        self.assertFalse(check(sock, ('127.0.0.1', 43210), frame, None))
        self.assertFalse(check(object(), ('127.0.0.1', 43210), frame, code))
        for target in [('127.0.0.1', 43211), ('localhost', 43210), ('203.0.113.1', 443)]:
            self.assertFalse(check(sock, target, frame, code))
        for host in ['203.0.113.1', 'localhost', '0.0.0.0']:
            local.update(addr=host, lsock=SimpleNamespace(getsockname=lambda: (host, 43210)))
            self.assertFalse(check(sock, (host, 43210), frame, code))

    def test_guard_denies_service_connections_in_main_and_concurrent_thread(self):
        import socket
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        original = (socket.create_connection, socket.socket.connect, socket.socket.connect_ex)
        with patch.object(socket, 'create_connection', original[0]), \
             patch.object(socket.socket, 'connect', original[1]), \
             patch.object(socket.socket, 'connect_ex', original[2]):
            self.module.install_network_guard()
            def assert_denied():
                for endpoint in [('203.0.113.1', 443), ('api.deepseek.com', 443), ('127.0.0.1', 80), ('::1', 80)]:
                    with self.assertRaisesRegex(AssertionError, 'Network is forbidden'):
                        socket.create_connection(endpoint)
                    with socket.socket() as sock:
                        with self.assertRaisesRegex(AssertionError, 'Network is forbidden'):
                            sock.connect(endpoint)
                        with self.assertRaisesRegex(AssertionError, 'Network is forbidden'):
                            sock.connect_ex(endpoint)
            assert_denied()
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(assert_denied).result()
            # On Windows exercise the exact stdlib fallback used by Proactor.
            if sys.platform == 'win32':
                left, right = socket._fallback_socketpair()
                try:
                    left.sendall(b'synthetic-self-pipe')
                    self.assertEqual(right.recv(64), b'synthetic-self-pipe')
                finally:
                    left.close()
                    right.close()
            assert_denied()
        self.assertEqual((socket.create_connection, socket.socket.connect, socket.socket.connect_ex), original)
