"""Keep the hosted browser fixture's safety/transport contracts in offline CI."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RangePlatformBrowserFixtureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_fixture_runtime_contracts_without_a_browser(self):
        result = subprocess.run(['node', str(ROOT / 'scripts/tests/range-platform-browser-fixtures.test.cjs')],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_edge_is_required_without_security_relaxations(self):
        source = (ROOT / 'scripts/range-platform-browser-acceptance.cjs').read_text(encoding='utf-8')
        self.assertIn('channel: "msedge"', source)
        self.assertIn('chromiumSandbox: true', source)
        self.assertIn('serviceWorkers: "block"', source)
        self.assertIn('native_extension_installation_or_permission_prompts_tested: false', source)
        for unsafe in ('--no-sandbox', '--disable-web-security', '--ignore-certificate-errors',
                       'grantPermissions', 'ignoreHTTPSErrors', 'executablePath:', 'channel: "chrome"'):
            self.assertNotIn(unsafe, source)


if __name__ == '__main__':
    unittest.main()
