from pathlib import Path
import unittest
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]


class MacosFinalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / '.github/workflows/macos-release.yml').read_text(encoding='utf-8')
        self.steps = yaml.safe_load(self.text)['jobs']['build-macos']['steps']

    def step(self, name):
        return next(step for step in self.steps if step.get('name') == name)

    def test_media_tools_precede_real_fixture_tests(self):
        media = self.step('Provision media tools for actual fixture tests')
        tests = self.step('Run macOS contract and desktop tests')
        self.assertLess(self.steps.index(media), self.steps.index(tests))
        for command in ('brew install ffmpeg', 'command -v ffmpeg', 'command -v ffprobe'):
            self.assertIn(command, media['run'])
        self.assertNotIn('continue-on-error', media)

    def test_bundle_contains_every_shipped_sidepanel_script(self):
        html = (ROOT / 'extension/sidepanel.html').read_text(encoding='utf-8')
        build = self.step('Build unsigned macOS app bundle')['run']
        for script in re.findall(r'<script[^>]+src="([^"?]+)', html):
            self.assertIn('extension/' + script, build)
        package = (ROOT / 'scripts/package-extension.ps1').read_text(encoding='utf-8')
        files = package.split('$files = @(', 1)[1].split(')', 1)[0]
        for filename in re.findall(r'"([^"]+)"', files):
            self.assertIn('extension/' + filename, build)

    def test_final_archive_is_created_after_staple_and_extracted_validation_blocks_upload(self):
        sign = self.step('Sign and notarize macOS bundle when credentials are configured')
        script = sign['run']
        commands = [
            'codesign --force --deep --options runtime --timestamp --sign',
            'submission="$RUNNER_TEMP/LearnNote-notary-submission.zip"',
            'ditto -c -k --sequesterRsrc --keepParent dist/LearnNote.app "$submission"',
            'xcrun notarytool submit "$submission"',
            'xcrun stapler staple dist/LearnNote.app',
            'xcrun stapler validate dist/LearnNote.app',
            'codesign --verify --deep --strict --verbose=2 dist/LearnNote.app',
            'ditto -c -k --sequesterRsrc --keepParent dist/LearnNote.app LearnNote-macOS.zip',
            'ditto -x -k LearnNote-macOS.zip "$verification_dir"',
            'xcrun stapler validate "$verification_dir/LearnNote.app"',
            'codesign --verify --deep --strict --verbose=2 "$verification_dir/LearnNote.app"',
        ]
        positions = [script.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(script.count('dist/LearnNote.app LearnNote-macOS.zip'), 1)
        self.assertNotIn('continue-on-error', sign)
        publish = self.step('Publish signed macOS asset')
        self.assertNotIn('always()', publish['if'])
        self.assertNotIn('submission', publish['run'])
        self.assertIn('LearnNote-macOS.zip', publish['run'])
        self.assertLess(self.steps.index(sign), self.steps.index(publish))
        upload = next(step for step in self.steps if str(step.get('uses','')).startswith('actions/upload-artifact@'))
        self.assertNotIn('RUNNER_TEMP', upload['with']['path'])

    def test_unsigned_path_and_credential_guard_are_preserved(self):
        unsigned = self.step('Package unsigned macOS preview')
        self.assertEqual(unsigned['run'], 'ditto -c -k --sequesterRsrc --keepParent dist/LearnNote.app LearnNote-macOS-unsigned.zip')
        self.assertIn("env.APPLE_SIGNING_IDENTITY == ''", unsigned['if'])
        sign = self.step('Sign and notarize macOS bundle when credentials are configured')
        for key in ['APPLE_SIGNING_IDENTITY','APPLE_CERTIFICATE_BASE64','APPLE_NOTARY_APPLE_ID','APPLE_NOTARY_PASSWORD','APPLE_TEAM_ID']:
            self.assertIn(f"env.{key} != ''", sign['if'])
        self.assertNotIn('security', unsigned['run'])
