"""One manual Windows cancellation diagnostic; existing gates stay unchanged."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = 'scripts/progressive-slo-cancel-diagnostic.py'
OUTPUT = 'build/reliability/cancel-diagnostic'


class CancelDiagnosticWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((ROOT / '.github/workflows/reliability.yml').read_text())
        cls.events = cls.workflow.get('on', cls.workflow.get(True))
        cls.job = cls.workflow['jobs']['offline-reliability']

    def test_manual_opt_in_separate_from_acceptance(self):
        option = self.events['workflow_dispatch']['inputs']['cancel_diagnostic']
        self.assertEqual(option['type'], 'boolean')
        self.assertIs(option['default'], False)
        self.assertIs(option['required'], False)
        self.assertIn('no browser acceptance', option['description'])
        steps = [step for step in self.job['steps'] if SCRIPT in step.get('run', '')]
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step['if'], "${{ success() && github.event_name == 'workflow_dispatch' && inputs.cancel_diagnostic }}")
        self.assertEqual(step['timeout-minutes'], 5)
        self.assertEqual(step['shell'], 'pwsh')
        self.assertNotIn('continue-on-error', step)
        self.assertEqual(step['run'].splitlines(), [f'python {SCRIPT} --output-dir {OUTPUT}',
            'if ($LASTEXITCODE -ne 0) { throw "Synthetic cancellation diagnostic failed" }'])
        self.assertEqual(self.job['runs-on'], 'windows-latest')
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertNotIn('cancel_diagnostic', str(self.workflow['jobs']['public-sample-audit']))

    def test_exact_report_only_upload_and_trigger_paths(self):
        for event in ('pull_request', 'push'):
            for path in (SCRIPT, 'scripts/progressive-slo-contention.py',
                         'scripts/tests/test_progressive_slo_cancel_diagnostic.py',
                         'scripts/tests/test_cancel_diagnostic_workflow.py'):
                self.assertEqual(self.events[event]['paths'].count(path), 1)
        upload = next(step for step in self.job['steps'] if step.get('name') == 'Upload offline reliability evidence')
        self.assertEqual(upload['if'], 'always()')
        paths = upload['with']['path'].splitlines()
        self.assertEqual([path for path in paths if 'cancel-diagnostic' in path], [OUTPUT + '/report.json'])
        self.assertFalse(any('/data' in path or '/seed' in path for path in paths))


if __name__ == '__main__':
    unittest.main()
