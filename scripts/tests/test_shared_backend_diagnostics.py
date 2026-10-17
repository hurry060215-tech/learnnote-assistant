"""The shared visual backend preserves failure evidence without retrying it."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class SharedBackendDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((ROOT / '.github/workflows/ui-visual.yml').read_text(encoding='utf-8'))
        cls.job = cls.workflow['jobs']['accessibility-visual']
        cls.step = next(step for step in cls.job['steps'] if step.get('name') == 'Start isolated local backend')
        cls.code = cls.step['run']

    def test_one_owned_backend_redirected_before_helpers(self):
        self.assertEqual(self.code.count('Start-Process'), 1)
        self.assertIn('-RedirectStandardOutput "$diagnostics/stdout.log"', self.code)
        self.assertIn('-RedirectStandardError "$diagnostics/stderr.log"', self.code)
        self.assertLess(self.code.index('Start-Process'), self.code.index('node scripts/global-assistant'))
        self.assertIn('--port", "8765"', self.code)
        self.assertNotIn('continue-on-error', self.step)
        self.assertNotIn('continue-on-error', self.job)

    def test_primary_failure_and_precleanup_status_preserved(self):
        self.assertIn('$primaryFailure = $_\n  throw\n} finally {', self.code)
        self.assertLess(self.code.index('$server.Refresh()'), self.code.index('Stop-Process'))
        for field in ('capturedBeforeCleanup = $true', 'hasExited = $exited', 'exitCode =',
                      'workingSetBytes =', 'peakWorkingSetBytes =', 'helperFailed ='):
            self.assertIn(field, self.code)
        self.assertIn('if ($null -eq $primaryFailure) { throw }', self.code)
        self.assertIn('Stop-Process -Id $server.Id -Force -ErrorAction Stop', self.code)
        self.assertIn('throw "Default reader/studio accessibility matrix failed"', self.code)

    def test_failure_tails_bounded_and_only_explicit_logs_uploaded(self):
        self.assertIn('if ($null -ne $primaryFailure)', self.code)
        self.assertIn('-Tail 80', self.code)
        self.assertIn('$_.Substring(0, 2000)', self.code)
        upload = next(step for step in self.job['steps'] if 'build/ui-visual' in step.get('with', {}).get('path', ''))
        self.assertIn('always()', upload['if'])
        paths = upload['with']['path'].splitlines()
        self.assertEqual([p for p in paths if 'ui-backend-diagnostics' in p], [
            'build/ui-backend-diagnostics/stdout.log',
            'build/ui-backend-diagnostics/stderr.log',
            'build/ui-backend-diagnostics/process-status.json'])
        self.assertFalse(any('ui-visual-data' in p for p in paths))
        self.assertNotIn('Get-ChildItem', self.code)


if __name__ == '__main__':
    unittest.main()
