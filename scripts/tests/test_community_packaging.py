"""Every new runtime module ships and is explicitly budgeted, including panel UI."""
from pathlib import Path
import re
import runpy
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
architecture = runpy.run_path(str(ROOT / 'scripts/check-architecture.py'))


class CommunityPackagingTests(unittest.TestCase):
    def test_all_community_modules_ship_and_count_toward_explicit_budgets(self):
        expected = {'community-source.js', 'background-community.js', 'content-community.js', 'sidepanel-community.js'}
        source = (ROOT / 'scripts/package-extension.ps1').read_text(encoding='utf-8').split('$files = @(', 1)[1].split(')', 1)[0]
        packaged = set(re.findall(r'"([^"\n]+)"', source))
        budgeted = set(architecture['EXTENSION_CAPTURE_SCRIPTS']) | set(architecture['EXTENSION_COMMUNITY_UI_SCRIPTS'])
        self.assertTrue(expected <= packaged)
        self.assertTrue(expected <= budgeted)
        for name in expected:
            self.assertIn('extension/' + name, architecture['MODULE_SIZE_LIMITS'])
        self.assertEqual(architecture['aggregate_size_violations'](), [])

    def test_collector_load_is_action_only_and_does_not_expand_manifest(self):
        import json
        manifest = json.loads((ROOT / 'extension/manifest.json').read_text())
        self.assertNotIn('community', json.dumps(manifest))
        worker = (ROOT / 'extension/background.js').read_text()
        panel = (ROOT / 'extension/sidepanel.html').read_text()
        self.assertNotIn('content-community.js', worker.splitlines()[1])
        self.assertNotIn('content-community.js', panel)
        self.assertIn('sidepanel-community.js', panel)
        self.assertIn('background-community.js', worker.splitlines()[1])
