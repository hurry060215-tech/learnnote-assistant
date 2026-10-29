"""Installed acceptance must finish before any new release is published."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstalledReleaseWorkflowTests(unittest.TestCase):
    def test_release_uses_shared_offline_and_javascript_gates_before_building(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            release = normalized.split('- name: Run release gate', 1)[1].split('- name: Preserve reliability evidence', 1)[0]
            order = [release.index(value) for value in (
                'python scripts/test-backend-offline.py',
                'throw "Backend release gate failed"',
                'python -m unittest discover scripts/tests -p "test_*.py"',
                'python -m unittest discover desktop/tests -p "test_*.py"',
                'npm test\n', 'throw "JavaScript release gate failed"',
                'npm run test:native\n', 'throw "Native dialog release gate failed"',
            )]
            self.assertEqual(order, sorted(order))
            self.assertEqual(normalized.count('python scripts/test-backend-offline.py'), 1)
            self.assertEqual(normalized.count('          npm test\n'), 1)
            self.assertEqual(normalized.count('          npm run test:native\n'), 1)
            self.assertNotIn('python -m unittest discover backend/tests', release)
            self.assertNotIn('Get-ChildItem extension/tests', release)
            self.assertNotIn('Get-ChildItem web/tests', release)
            self.assertNotIn('continue-on-error', release)

    def test_release_provisions_existing_pinned_media_tools_before_real_fixtures(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        helper = (ROOT / 'scripts/install-visual-media-tools.ps1').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            invocation = './scripts/install-visual-media-tools.ps1 -OutputDirectory build/release/visual-media-tools'
            self.assertEqual(normalized.count(invocation), 1)
            self.assertLess(normalized.index(invocation), normalized.index('- name: Run release gate'))
            step = normalized.split('- name: Provision pinned media tools for real fixture contracts', 1)[1].split('- name: Run release gate', 1)[0]
            self.assertIn('timeout-minutes: 5', step)
            self.assertIn("if: env.CANDIDATE_ARTIFACT_ID == ''", step)
            self.assertNotIn('continue-on-error', step)
            retention = normalized.split('- name: Preserve reliability evidence', 1)[1].split('- name: Build portable desktop client', 1)[0]
            self.assertIn('if: always()', retention)
            self.assertIn('build/release/visual-media-tools/media-tools.json', retention)
        self.assertIn('choco install ffmpeg --version=8.1.0', helper)
        self.assertIn("@('ffmpeg', 'ffprobe')", helper)
        self.assertIn('version verification failed', helper)
        self.assertIn('Pinned visual media tools installation failed', helper)

    def test_retained_feature_versions_reuse_pinned_media_without_expanding_older_diagnostics(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            name = '- name: Provision pinned media tools for real fixture contracts'
            step = normalized.split(name, 1)[1].split('- name: Run release gate', 1)[0]
            condition = next(line.strip() for line in step.splitlines() if line.strip().startswith('if:'))
            # Fresh builds and retained feature-capable versions need media;
            # retained pre-feature diagnostics retain their old scope.
            self.assertEqual(condition, "if: env.CANDIDATE_ARTIFACT_ID == '' || env.INSTALLED_FEATURES == 'true'")
            self.assertEqual(normalized.count(condition), 1)
            self.assertLess(normalized.index('Retained installers require acceptance-only manual diagnostics'), normalized.index(name))
            self.assertLess(normalized.index('Retained candidate identity verification failed'), normalized.index(name))
            self.assertLess(normalized.index(name), normalized.index('- name: Smoke-test installed release'))
            self.assertLess(normalized.index(name), normalized.index('python scripts/installed-upgrade-acceptance.py'))
            self.assertIn('run: ./scripts/install-visual-media-tools.ps1 -OutputDirectory build/release/visual-media-tools', step)
            self.assertNotIn('GH_TOKEN', step)
            self.assertNotIn('continue-on-error', step)

    def test_installed_gate_preserves_prior_smoke_and_blocks_publication(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            order = [normalized.index(value) for value in (
                'npm ci', 'Smoke-test installed release',
                'Previous installer digest mismatch', './scripts/test-upgrade-installer.ps1',
                'python scripts/installed-upgrade-acceptance.py', 'Package browser extension',
                'Publish GitHub Release')]
            self.assertEqual(order, sorted(order))
            self.assertEqual(normalized.count('python scripts/installed-upgrade-acceptance.py'), 1)
            self.assertIn('throw "Installed diagnostic and saved-subtitle acceptance failed"', normalized)
            self.assertIn('--expected-previous-version', normalized)
            self.assertIn('--expected-current-version', normalized)
            self.assertNotIn('continue-on-error', normalized)
            self.assertIn('throw "Previous stable release lookup failed"', normalized)
            self.assertIn('throw "Previous stable release is required for installed upgrade acceptance"', normalized)
            upgrade = normalized.split('- name: Smoke-test upgrade from previous release', 1)[1].split('- name: Retain installed upgrade acceptance evidence', 1)[0]
            self.assertNotIn('exit 0', upgrade)

    def test_reviewed_upgrade_baselines_do_not_drift_after_later_releases(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            upgrade = normalized.split('- name: Smoke-test upgrade from previous release', 1)[1].split('- name: Retain installed upgrade acceptance evidence', 1)[0]
            self.assertIn('$requiredPreviousTag = $env:INSTALLED_PREVIOUS_TAG', upgrade)
            pinned, fallback = upgrade.split('if ($requiredPreviousTag) {', 1)[1].split('} else {', 1)
            self.assertIn('$previous = [pscustomobject]@{ tagName = $requiredPreviousTag }', pinned)
            self.assertNotIn('gh release list', pinned)
            self.assertIn('gh release list', fallback)
            self.assertIn('--limit 20 --json tagName,isDraft,isPrerelease,publishedAt', fallback)
            self.assertIn('-not $_.isDraft -and -not $_.isPrerelease', fallback)
            self.assertIn("$_.tagName -match '^v[0-9]+\\.[0-9]+\\.[0-9]+$'", fallback)
            self.assertIn("[version]$_.tagName.TrimStart('v') -lt [version]$currentTag.TrimStart('v')", fallback)
            self.assertIn("Sort-Object { [version]$_.tagName.TrimStart('v') } -Descending", fallback)
            # Validate identity, stable publication, immutable pins and a unique
            # digest before downloading; downloaded bytes must then match it.
            for guard in (
                '$previousMetadata.tag_name -ne $previous.tagName',
                '$previousMetadata.draft -ne $false',
                '$previousMetadata.prerelease -ne $false',
                '$requiredPreviousTag -and $previousMetadata.immutable -ne $true',
                '$previousAssets.Count -ne 1',
                "$previousAssets[0].digest -notmatch '^sha256:[0-9a-f]{64}$'",
            ):
                self.assertLess(upgrade.index(guard), upgrade.index('gh release download'))
            self.assertIn('throw "Previous release is not the requested published stable baseline"', upgrade)
            self.assertIn('throw "Reviewed upgrade baseline must be an immutable release"', upgrade)
            self.assertIn('if ("sha256:$previousHash" -ne $previousAssets[0].digest) { throw "Previous installer digest mismatch" }', upgrade)
            self.assertLess(upgrade.index('Previous installer digest mismatch'), upgrade.index('./scripts/test-upgrade-installer.ps1'))
            self.assertIn("--expected-previous-version \"$($previous.tagName.TrimStart('v'))\"", upgrade)
            self.assertIn("--expected-current-version \"$($currentTag.TrimStart('v'))\"", upgrade)
            self.assertNotIn('ACCEPTANCE_ONLY', upgrade)
            # Retained mode may affect only the extra source-bound architecture phase.
            baseline = upgrade.split('$architectureArgs = @()', 1)[0]
            self.assertNotIn('CANDIDATE_ARTIFACT_ID', baseline)

    def test_fresh_feature_releases_require_architecture_while_retained_candidates_keep_prior_gates(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            upgrade = normalized.split('- name: Smoke-test upgrade from previous release', 1)[1].split('- name: Retain installed upgrade acceptance evidence', 1)[0]
            option = upgrade.split('$architectureArgs = @()', 1)[1].split('python scripts/installed-upgrade-acceptance.py', 1)[0]
            self.assertEqual([line.strip() for line in option.splitlines() if line.strip()], [
                "if ($env:INSTALLED_FEATURES -eq 'true' -and -not $env:CANDIDATE_ARTIFACT_ID) {",
                "$architectureArgs = @('--architecture')", '}',
            ])
            invocation = upgrade.split('python scripts/installed-upgrade-acceptance.py', 1)[1]
            self.assertIn('--output-dir build/release/installed-upgrade @architectureArgs', invocation)
            self.assertEqual(upgrade.count('CANDIDATE_ARTIFACT_ID'), 1)
            self.assertNotIn('ACCEPTANCE_ONLY', upgrade)
            self.assertLess(upgrade.index('Cover-upgrade smoke failed'), upgrade.index('$architectureArgs = @()'))
            self.assertLess(upgrade.index('@architectureArgs'), upgrade.index('Installed diagnostic and saved-subtitle acceptance failed'))
            self.assertNotIn('continue-on-error', upgrade)

    def test_candidate_retention_is_source_bound_and_before_mandatory_tests(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            order = [normalized.index(value) for value in (
                '- name: Sign Windows installer', '- name: Identify installer candidate',
                '- name: Retain installer candidate', '- name: Smoke-test installed release',
                '- name: Smoke-test upgrade from previous release', '- name: Publish GitHub Release')]
            self.assertEqual(order, sorted(order))
            identify = normalized.split('- name: Identify installer candidate', 1)[1].split('- name: Retain installer candidate', 1)[0]
            for field in ('source_commit = $env:BUILD_COMMIT', 'release_tag = $env:RELEASE_TAG',
                          'run_id = $env:GITHUB_RUN_ID', 'run_attempt = $env:GITHUB_RUN_ATTEMPT',
                          'acceptance_status = "pending"', 'installer_bytes = $installer.Length',
                          '-Algorithm SHA256'):
                self.assertIn(field, identify)
            step = normalized.split('- name: Retain installer candidate', 1)[1].split('- name: Smoke-test installed release', 1)[0]
            paths = step.split('path: |', 1)[1].split('if-no-files-found:', 1)[0].split()
            self.assertEqual(paths, ['LearnNote-Setup-x64.exe', 'build/release/installer-candidate.json',
                                     'build/release/freshness.json', 'build/release-tree-audit.json'])
            self.assertIn('if-no-files-found: error', step)
            self.assertIn('retention-days: 7', step)
            self.assertNotIn('continue-on-error', step)
            self.assertNotIn('gh release', step)

    def test_acceptance_only_keeps_gates_and_forbids_publication(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            option = normalized.split('      acceptance_only:', 1)[1].split('      release_tag:', 1)[0]
            self.assertIn('default: false', option)
            self.assertIn('type: boolean', option)
            self.assertIn("ACCEPTANCE_ONLY: ${{ inputs.acceptance_only && 'true' || 'false' }}", normalized)
            for name in ('Attest release build provenance', 'Publish GitHub Release'):
                self.assertIn(f"- name: {name}\n        if: env.RELEASE_TAG != '' && env.ACCEPTANCE_ONLY != 'true'", normalized)
            publish = normalized.split('- name: Publish GitHub Release', 1)[1]
            refusal = publish.index('Acceptance-only runs cannot create tags or publish releases')
            self.assertLess(refusal, publish.index('scripts/ensure-release-tag.py'))
            self.assertLess(refusal, publish.index('scripts/publish-release.ps1'))
            self.assertEqual(normalized.count('scripts/ensure-release-tag.py'), 1)
            self.assertEqual(normalized.count('scripts/publish-release.ps1'), 1)
            gates = normalized.split('- name: Run release gate', 1)[1].split('- name: Attest release build provenance', 1)[0]
            self.assertNotIn('ACCEPTANCE_ONLY', gates)
            self.assertIn('python scripts/installed-upgrade-acceptance.py', gates)
            self.assertIn('throw "Installed diagnostic and saved-subtitle acceptance failed"', gates)

    def test_retained_diagnostics_are_bounded_and_leave_installed_gates_mandatory(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        self.assertIn('candidate_artifact_id:', source)
        self.assertIn('retained mode pins candidate source; harness uses dispatched SHA', source)
        self.assertIn('inputs.candidate_artifact_id && github.sha || inputs.release_commit', source)
        self.assertIn('Retained installers require acceptance-only manual diagnostics', source)
        self.assertIn('Diagnostic harness must match the dispatched workflow source', source)
        self.assertIn('actions: read', source)
        for name in ('Install desktop dependencies',
                     'Run release gate', 'Build portable desktop client', 'Package Windows release',
                     'Identify installer candidate before installed tests',
                     'Retain installer candidate for failure diagnosis', 'Package browser extension'):
            self.assertIn(f"- name: {name}\n        if: env.CANDIDATE_ARTIFACT_ID == ''", source)
        for name in ('Sign Windows executable', 'Sign Windows installer'):
            self.assertIn(f"- name: {name}\n        if: env.CANDIDATE_ARTIFACT_ID == '' && env.SIGNING_CERT_BASE64 != ''", source)
        self.assertIn("if: env.CANDIDATE_ARTIFACT_ID == ''\n        with:\n          name: LearnNote-release-assets", source)
        fresh = source.split('- name: Smoke-test installed release', 1)[1].split('- name: Smoke-test upgrade', 1)[0]
        self.assertNotIn('if:', fresh)
        upgrade = source.split('- name: Smoke-test upgrade from previous release', 1)[1].split('- name: Retain installed', 1)[0]
        self.assertIn("if: env.RELEASE_TAG != ''", upgrade)
        self.assertNotIn('CANDIDATE_ARTIFACT_ID', upgrade.split('$architectureArgs = @()', 1)[0])
        self.assertLess(upgrade.index('$env:GH_TOKEN = ""'), upgrade.index('./scripts/test-upgrade-installer.ps1'))
        restore = source.split('- name: Verify and restore retained diagnostic candidate', 1)[1].split('- name: Install retained', 1)[0]
        self.assertIn('--source-commit "$env:RELEASE_COMMIT"', restore)
        self.assertNotIn('pip install', restore)
        dependencies = source.split('- name: Install retained diagnostic harness dependencies', 1)[1].split('- name: Provision', 1)[0]
        for pin in (ROOT / 'backend/requirements.windows-py312.lock.txt').read_text(encoding='utf-8').splitlines():
            if pin.split('==')[0] in ('requests', 'certifi', 'charset-normalizer', 'idna', 'urllib3'):
                self.assertIn(pin, dependencies)
        self.assertIn('npm ci', dependencies)
        self.assertNotIn('GH_TOKEN', dependencies)
        checks = source.split('- name: Check current retained diagnostic harness', 1)[1].split('- name: Provision', 1)[0]
        self.assertIn("if: env.CANDIDATE_ARTIFACT_ID != ''", checks)
        self.assertIn('scripts.tests.test_restore_installer_candidate scripts.tests.test_installed_release_workflow scripts.tests.test_installed_upgrade_acceptance.InstalledUpgradeTests', checks)
        self.assertIn('node web/tests/installed_diagnostic_acceptance.test.mjs', checks)
        self.assertNotIn('InstalledSourceRehearsalTests', checks)
        self.assertIn('python -m unittest discover scripts/tests -p "test_*.py"', source)
        installed_tests = (ROOT / 'scripts/tests/test_installed_upgrade_acceptance.py').read_text(encoding='utf-8')
        self.assertIn('class InstalledSourceRehearsalTests(unittest.TestCase):', installed_tests)
        self.assertIn('def test_real_api_saved_caption_retry_keeps_original_evidence(self):', installed_tests)
        self.assertIn('throw "Current native diagnostic helper contracts failed"', checks)
        self.assertLess(source.index('- name: Check current retained diagnostic harness'), source.index('- name: Smoke-test installed release'))
        self.assertIn('build/release/retained-candidate/*.json', source)
        self.assertNotIn('continue-on-error', source)

    def test_calibration_runs_once_and_retains_only_fixed_evidence_without_precreating_installed_output(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        test = (ROOT / 'web/tests/installed_diagnostic_acceptance.test.mjs').read_text(encoding='utf-8')
        installed = (ROOT / 'scripts/installed-upgrade-acceptance.py').read_text(encoding='utf-8')
        for text in (source, source.replace('\n', '\r\n')):
            normalized = text.replace('\r\n', '\n')
            checks = normalized.split('- name: Check current retained diagnostic harness', 1)[1].split('- name: Provision', 1)[0]
            release = normalized.split('- name: Run release gate', 1)[1].split('- name: Preserve reliability evidence', 1)[0]
            self.assertIn("if: env.CANDIDATE_ARTIFACT_ID != ''", checks)
            self.assertIn("if: env.CANDIDATE_ARTIFACT_ID == ''", release)
            self.assertEqual(checks.count('node web/tests/installed_diagnostic_acceptance.test.mjs'), 1)
            self.assertEqual(release.count('          npm run test:native\n'), 1)
            self.assertNotIn('node web/tests/installed_diagnostic_acceptance.test.mjs', release)
            retention = normalized.split('- name: Preserve reliability evidence', 1)[1].split('- name: Build portable desktop client', 1)[0]
            self.assertIn('if: always()', retention)
            self.assertEqual([line.strip() for line in retention.splitlines() if '/native-save-calibration/' in line], [
                'build/release/native-save-calibration/native-save-calibration-report.json',
                'build/release/native-save-calibration/native-save-calibration-md-dialog.png',
                'build/release/native-save-calibration/native-save-calibration-json-dialog.png',
            ])
            self.assertNotIn('continue-on-error', normalized)
        self.assertEqual(test.count("calibration.runCalibration(output)"), 1)
        self.assertIn("let output = path.resolve('build/release/native-save-calibration')", test)
        self.assertIn("fs.mkdtempSync(path.join(parent, 'native-save-calibration-rerun-'))", test)
        self.assertIn('args.output_dir.mkdir(parents=True, exist_ok=False)', installed)
        ci = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertEqual(ci.count('          npm test\n'), 1)
        self.assertEqual(ci.count('          npm run test:native\n'), 1)
        self.assertIn('throw "Native dialog checks failed"', ci)
        self.assertNotIn('node web/tests/installed_diagnostic_acceptance.test.mjs', ci)

    def test_retention_is_always_top_level_synthetic_evidence_only(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        step = source.split('- name: Retain installed upgrade acceptance evidence', 1)[1].split('- name: Package browser extension', 1)[0]
        self.assertIn('if: always()', step)
        paths = [line.strip() for line in step.splitlines() if 'build/release/installed-upgrade/' in line]
        self.assertEqual(paths, ['build/release/installed-upgrade/*.json',
                                 'build/release/installed-upgrade/*.log',
                                 'build/release/installed-upgrade/*.png'])
        self.assertNotIn('**', step)


if __name__ == '__main__':
    unittest.main()
