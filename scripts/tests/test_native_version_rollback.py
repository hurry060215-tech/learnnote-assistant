from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('rollback', ROOT / 'scripts/native-version-rollback.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class NativeVersionRollbackTests(unittest.TestCase):
    def test_snapshot_preserves_hidden_unicode_bytes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'source'; source.mkdir()
            (source / '.owned').write_bytes(b'\x00\xff')
            (source / '批注').write_text('café', encoding='utf-8')
            before = M.snapshot(source, root / 'saved')
            self.assertEqual(before, M.inventory(source))
            self.assertEqual(before, M.inventory(root / 'saved'))
            with self.assertRaises(ValueError):
                M.snapshot(source, root / 'saved')

    def test_snapshot_rejects_symlinks_without_following(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'source'; source.mkdir()
            try:
                (source / 'link').symlink_to(root / 'outside')
            except OSError:
                self.skipTest('Host does not permit test symlink creation')
            with self.assertRaises(ValueError):
                M.snapshot(source, root / 'saved')
            self.assertFalse((root / 'saved').exists())

    def test_restore_uses_same_path_and_retains_new_version_edits(self):
        phases = []; active = None
        @contextmanager
        def launch(app, data, output, phase, version):
            nonlocal active
            if active is None:
                active = data; data.mkdir(); (data / 'record').write_text('old', encoding='utf-8')
            self.assertEqual(data, active)
            if version == '0.2.15':
                (data / 'record').write_text('new', encoding='utf-8')
            if phase == 'old-after-snapshot-restore':
                self.assertEqual((data / 'record').read_text(), 'old')
            phases.append((phase, version))
            yield Mock(), {'version': version}
        with tempfile.TemporaryDirectory() as temp, patch.object(M, 'seed', return_value={'material_id':'m','task_id':'t'}), patch.object(M, 'read_evidence', return_value={'exports': 'same'}):
            output = Path(temp)
            report = M.exercise(Path('old-app'), Path('new-app'), output, launch)
            self.assertEqual(report['status'], 'pass')
            self.assertEqual([x[1] for x in phases], ['0.2.14','0.2.15','0.2.14'])
            self.assertEqual((output/'pre-upgrade-snapshot/record').read_text(), 'old')
            self.assertEqual((output/'upgraded-snapshot/record').read_text(), 'new')
            self.assertEqual((output/'upgraded-active-data/record').read_text(), 'new')
            self.assertIn('old binary opening newer-schema data', report['not_tested'])

    def test_capture_binds_loaded_title_and_window_id_without_accessibility(self):
        result = Mock(stdout=json.dumps([{'id':123,'title':'LearnNote - Video Learning Notes','bounds':{}}]))
        with tempfile.TemporaryDirectory() as temp, patch.object(M.subprocess, 'run', return_value=result) as run:
            (Path(temp)/'phase.png').write_bytes(b'\x89PNG\r\n\x1a\n'+b'0'*32)
            proof = M.owned_capture(42, Path(temp), 'phase')
            self.assertEqual(proof['pid'], 42)
            self.assertEqual(run.call_args_list[0].args[0][-1], '42')
            self.assertEqual(run.call_args_list[1].args[0][:4], ['screencapture','-x','-l','123'])
            self.assertTrue(proof['visual_review_required'])
        swift = (ROOT/'scripts/native-version-window.swift').read_text(encoding='utf-8')
        self.assertIn('kCGWindowOwnerPID', swift)
        self.assertNotIn('System Events', swift)

    def test_main_keeps_primary_failure_if_report_write_fails(self):
        primary = RuntimeError('build mismatch')
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp)/'manifest.json';manifest.write_text('{}')
            args = ['gate','--old-app','old','--new-app','new','--build-manifest',str(manifest),'--output',temp]
            with patch.object(M.sys,'argv',args), patch.object(M.sys,'platform','darwin'), patch.object(M,'verify_builds',side_effect=primary), patch.object(M,'write_json',side_effect=OSError('report unavailable')):
                with self.assertRaises(RuntimeError) as caught: M.main()
                self.assertIs(caught.exception, primary)

    def test_cleanup_terminates_app_even_when_session_close_fails(self):
        primary = RuntimeError('phase failed')
        api = Mock()
        api.call.return_value.json.side_effect = [dict(ok=True,app_version='0.2.14',backend_version='0.2.14'),dict(focused=True)]
        api.session.close.side_effect = OSError('close failed')
        process = Mock(); process.poll.return_value = None
        with tempfile.TemporaryDirectory() as temp, patch.object(M.subprocess,'Popen',return_value=process), patch.object(M.native,'Api',return_value=api), patch.object(M,'owned_capture',return_value={}):
            with self.assertRaises(RuntimeError) as caught:
                with M.running(Path('app'),Path(temp)/'data',Path(temp),'old','0.2.14'):
                    raise primary
            self.assertIs(caught.exception,primary)
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=20)

    def test_constructor_and_capture_failures_always_stop_owned_process(self):
        for stage in ('api', 'capture'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                primary = RuntimeError(stage + ' failed')
                api = Mock()
                api.call.return_value.json.side_effect = [dict(ok=True,app_version='0.2.14',backend_version='0.2.14'),dict(focused=True)]
                process = Mock(); process.poll.return_value = None
                with patch.object(M.subprocess,'Popen',return_value=process), patch.object(M.native,'Api',side_effect=primary if stage=='api' else None,return_value=api), patch.object(M,'owned_capture',side_effect=primary if stage=='capture' else None):
                    with self.assertRaises(RuntimeError) as caught:
                        with M.running(Path('app'),Path(temp)/'data',Path(temp),'old','0.2.14'):
                            self.fail('Must not enter body after setup failure')
                    self.assertIs(caught.exception,primary)
                    process.terminate.assert_called_once()
                    process.wait.assert_called_once_with(timeout=20)
