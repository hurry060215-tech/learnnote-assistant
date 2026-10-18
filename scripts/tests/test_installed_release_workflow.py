"""Installed acceptance must finish before any new release is published."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstalledReleaseWorkflowTests(unittest.TestCase):
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
            self.assertNotIn('if:', step)
            self.assertNotIn('continue-on-error', step)
            retention = normalized.split('- name: Preserve reliability evidence', 1)[1].split('- name: Build portable desktop client', 1)[0]
            self.assertIn('if: always()', retention)
            self.assertIn('build/release/visual-media-tools/media-tools.json', retention)
        self.assertIn('choco install ffmpeg --version=8.1.0', helper)
        self.assertIn("@('ffmpeg', 'ffprobe')", helper)
        self.assertIn('version verification failed', helper)
        self.assertIn('Pinned visual media tools installation failed', helper)

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
            self.assertIn("$previous.tagName -ne 'v0.2.15'", normalized)
            upgrade = normalized.split('- name: Smoke-test upgrade from previous release', 1)[1].split('- name: Retain installed upgrade acceptance evidence', 1)[0]
            self.assertNotIn('exit 0', upgrade)

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
