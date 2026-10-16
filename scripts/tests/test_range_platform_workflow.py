from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class RangePlatformWorkflowTests(unittest.TestCase):
    def test_independent_required_range_gate_and_retained_evidence(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/ui-visual.yml').read_text(encoding='utf-8'))
        events = workflow.get('on', workflow.get(True))
        for event in ('push', 'pull_request'):
            paths = events[event]['paths']
            for path in ('scripts/range-platform-browser-acceptance.cjs',
                         'scripts/fixtures/range-platform-cases.json',
                         'scripts/tests/*range*platform*',
                         'backend/tests/test_range_platform_fixtures.py',
                         'backend/tests/test_caption_range_context.py',
                         'backend/app/caption_extraction.py', 'backend/app/subtitle_notes.py'):
                self.assertIn(path, paths)
        job = workflow['jobs']['accessibility-visual']
        steps = job['steps']
        gate = next(step for step in steps if step.get('name') == 'Rendered platform range matrix with synthetic transport')
        self.assertEqual(gate['if'], "${{ !cancelled() && steps.visual_dependencies.outcome == 'success' }}")
        self.assertEqual(gate['shell'], 'pwsh')
        self.assertIn('node scripts/range-platform-browser-acceptance.cjs build/range-platform-ui', gate['run'])
        self.assertIn('if ($LASTEXITCODE -ne 0) { throw', gate['run'])
        self.assertNotIn('continue-on-error', gate)
        self.assertNotIn('continue-on-error', job)
        backend = next(step for step in steps if step.get('name') == 'Start isolated local backend')
        self.assertLess(steps.index(gate), steps.index(backend))
        upload = next(step for step in steps if 'build/range-platform-ui' in step.get('with', {}).get('path', ''))
        self.assertIn('always()', upload['if'])
