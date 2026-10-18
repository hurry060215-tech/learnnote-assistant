"""Offline, fail-closed identity and archive contracts for retained diagnostics."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('restore_candidate', ROOT / 'scripts/restore-installer-candidate.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
SOURCE, HARNESS = 'a' * 40, 'b' * 40
REPOSITORY = 'owner/project'


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = {'id': 22, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure',
                    'event': 'workflow_dispatch', 'head_branch': 'main', 'head_sha': SOURCE,
                    'repository': {'id': 33, 'full_name': REPOSITORY},
                    'head_repository': {'id': 33, 'full_name': REPOSITORY},
                    'path': helper.WORKFLOW, 'workflow_id': 44}
        self.artifact = {'id': 11, 'expired': False, 'name': 'installer-candidate-22-1',
                         'workflow_run': {'id': 22, 'repository_id': 33, 'head_repository_id': 33,
                                          'head_sha': SOURCE, 'head_branch': 'main'}}
        self.workflow = {'id': 44, 'path': helper.WORKFLOW}
        self.manifest = {'schema_version': 1, 'source_commit': SOURCE, 'release_tag': 'v0.2.16',
                         'run_id': '22', 'run_attempt': '1', 'acceptance_status': 'pending',
                         'installer_name': helper.INSTALLER, 'installer_bytes': 7,
                         'installer_sha256': hashlib.sha256(b'fixture').hexdigest()}
        self.freshness = {'schema_version': 1, 'status': 'pass', 'commit': SOURCE, 'expected_commit': SOURCE,
                          'clean_checkout': True, 'matches_expected_commit': True, 'require_current_ref': True}
        self.files = {helper.INSTALLER: b'fixture', helper.MANIFEST: self.manifest,
                      helper.FRESHNESS: self.freshness, helper.AUDIT: {'passed': True}}
        self.write_archive()

    def write_archive(self, extra=None, symlink=False):
        self.archive = self.root / 'candidate.zip'
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for name, value in self.files.items():
                info = zipfile.ZipInfo(name)
                if symlink and name == helper.INSTALLER:
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, value if isinstance(value, bytes) else json.dumps(value).encode())
            if extra:
                archive.writestr(extra, b'unexpected')
        self.artifact.update(size_in_bytes=self.archive.stat().st_size,
                             digest='sha256:' + helper.sha256(self.archive))

    def verify_origin(self, artifact=None, run=None, workflow=None):
        helper.verify_origin(artifact or self.artifact, run or self.run, workflow or self.workflow,
                             REPOSITORY, '11', SOURCE)

    def verify_archive(self):
        return helper.verify_archive(self.archive, self.artifact, self.run, SOURCE, 'v0.2.16', self.root / 'verified')

    def test_accepts_failed_original_gate_but_never_calls_it_accepted(self):
        self.verify_origin()
        self.assertEqual(self.verify_archive()['acceptance_status'], 'pending')
        self.assertEqual((self.root / 'verified' / helper.INSTALLER).read_bytes(), b'fixture')

    def test_rejects_origin_identity_changes(self):
        for object_name, changes in (
                ('artifact', {'id': 12, 'expired': True, 'digest': '', 'size_in_bytes': 0, 'name': 'installer-candidate-22-2'}),
                ('run', {'id': 23, 'run_attempt': 2, 'status': 'in_progress', 'conclusion': 'cancelled',
                         'event': 'pull_request', 'head_branch': 'feature', 'head_sha': HARNESS,
                         'path': '.github/workflows/other.yml', 'workflow_id': 45,
                         'repository': {'id': 33, 'full_name': 'other/repo'},
                         'head_repository': {'id': 34, 'full_name': REPOSITORY}}),
                ('workflow', {'id': 45, 'path': '.github/workflows/other.yml'})):
            for key, value in changes.items():
                with self.subTest(object=object_name, key=key):
                    changed = copy.deepcopy(getattr(self, object_name)); changed[key] = value
                    with self.assertRaises(ValueError):
                        self.verify_origin(**{object_name: changed})
        for key, value in {'id': 23, 'repository_id': 34, 'head_repository_id': 34,
                           'head_sha': HARNESS, 'head_branch': 'feature'}.items():
            changed = copy.deepcopy(self.artifact); changed['workflow_run'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify_origin(artifact=changed)

    def test_rejects_digest_before_extracting(self):
        self.artifact['digest'] = 'sha256:' + '0' * 64
        with self.assertRaisesRegex(ValueError, 'ZIP digest'):
            self.verify_archive()
        self.assertFalse((self.root / 'verified').exists())

    def test_rejects_extra_duplicate_traversal_and_links(self):
        for extra in ('extra.txt', helper.INSTALLER, '../escape.exe', '/absolute.exe', 'build\\evil.txt'):
            with self.subTest(extra=extra):
                self.write_archive(extra=extra)
                with self.assertRaisesRegex(ValueError, 'exactly'):
                    self.verify_archive()
        self.write_archive(symlink=True)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.verify_archive()
        self.assertFalse((self.root / 'verified').exists())

    def test_rejects_manifest_freshness_and_audit_mismatch(self):
        for member, changes in ((helper.MANIFEST, {'schema_version': 2, 'source_commit': HARNESS,
                'release_tag': 'v0.2.17', 'run_id': '23', 'run_attempt': '2', 'acceptance_status': 'accepted',
                'installer_name': 'other.exe', 'installer_bytes': 8, 'installer_sha256': 'invalid'}),
                (helper.FRESHNESS, {'status': 'fail', 'commit': HARNESS, 'expected_commit': HARNESS,
                 'clean_checkout': False, 'matches_expected_commit': False, 'require_current_ref': False}),
                (helper.AUDIT, {'passed': False})):
            original = copy.deepcopy(self.files[member])
            for key, value in changes.items():
                with self.subTest(member=member, key=key):
                    self.files[member] = {**original, key: value}; self.write_archive()
                    with self.assertRaises(ValueError):
                        self.verify_archive()
            self.files[member] = original
        self.manifest['installer_sha256'] = '0' * 64
        self.files[helper.MANIFEST] = self.manifest; self.write_archive()
        with self.assertRaisesRegex(ValueError, 'installer digest'):
            self.verify_archive()

    def test_malformed_metadata_fails_closed_before_installer_write(self):
        for field, value in [('digest', None), ('workflow_run', ['invalid']), ('size_in_bytes', '7')]:
            changed = {**self.artifact, field: value}
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError, AttributeError)):
                self.verify_origin(artifact=changed)
        self.artifact['digest'] = None
        with self.assertRaises((ValueError, TypeError)):
            self.verify_archive()
        self.write_archive()
        for member, value in [(helper.MANIFEST, None), (helper.MANIFEST, ['invalid']),
                              (helper.FRESHNESS, None), (helper.AUDIT, ['invalid'])]:
            original = self.files[member]
            self.files[member] = value; self.write_archive()
            with self.subTest(member=member), self.assertRaises((ValueError, TypeError, AttributeError)):
                self.verify_archive()
            self.files[member] = original
        self.assertFalse((self.root / 'verified').exists())

    def test_zero_and_oversized_members_fail_before_installer_write(self):
        for member in (helper.INSTALLER, helper.MANIFEST):
            original = self.files[member]
            self.files[member] = b''; self.write_archive()
            with self.subTest(member=member), self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.verify_archive()
            self.files[member] = original
        self.write_archive()
        with patch.object(helper, 'MAX_INSTALLER_BYTES', 6), self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.verify_archive()
        self.files[helper.MANIFEST] = b'0' * (1024**2 + 1); self.write_archive()
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.verify_archive()
        self.assertFalse((self.root / 'verified').exists())

    def test_restore_separates_candidate_and_harness_without_publishing(self):
        env = {'ACCEPTANCE_ONLY': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_REPOSITORY': REPOSITORY, 'GITHUB_SHA': HARNESS, 'BUILD_COMMIT': HARNESS, 'GITHUB_RUN_ID': '55'}
        args = SimpleNamespace(artifact_id='11', source_commit=SOURCE, release_tag='v0.2.16')
        endpoints = []
        def api(endpoint, output=None):
            endpoints.append(endpoint)
            if output:
                output.write(self.archive.read_bytes()); return
            return self.artifact if '/artifacts/' in endpoint else self.run if '/runs/' in endpoint else self.workflow
        with patch.object(helper, 'ROOT', self.root), patch.dict(os.environ, env, clear=True), \
                patch.object(helper, 'gh_api', side_effect=api), \
                patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(stdout=HARNESS + '\n')):
            helper.restore(args)
            report = json.loads((self.root / 'build/release/retained-candidate/diagnostic-identity.json').read_text())
            self.assertIs(report['current_source_acceptance'], False)
            self.assertEqual(report['candidate_source_commit'], SOURCE)
            self.assertEqual(report['harness_source_commit'], HARNESS)
            self.assertEqual(endpoints[-1], f'repos/{REPOSITORY}/actions/artifacts/11/zip')
            for key, bad in [('ACCEPTANCE_ONLY', 'false'), ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_SHA', SOURCE)]:
                with patch.dict(os.environ, {key: bad}), self.assertRaises(ValueError):
                    helper.restore(args)
            for bad in ['https://evil.test/archive', '11/zip', '0', '11\n']:
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    helper.restore(SimpleNamespace(**{**vars(args), 'artifact_id': bad}))
            self.assertEqual(len(endpoints), 4)


if __name__ == '__main__':
    unittest.main()
