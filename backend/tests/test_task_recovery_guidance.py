"""Frozen pre-extraction wire outputs from e4ab6f1, using synthetic inputs only."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.models import TaskRecord
from app.task_recovery_guidance import RecoveryEvidence, diagnostic_recovery_profile


class RecoveryGuidanceTests(unittest.TestCase):
    def test_frozen_recovery_profiles_are_unchanged_without_io(self):
        fixtures = json.loads((Path(__file__).parent / 'fixtures' /
                               'recovery-guidance-e4ab6f1.json').read_text(encoding='utf-8'))
        for fixture in fixtures:
            with self.subTest(case=fixture['case']):
                task = TaskRecord(**fixture['task'])
                evidence = RecoveryEvidence(**fixture['evidence'])
                before_task = task.model_dump(mode='json')
                before_evidence = copy.deepcopy(evidence)
                with patch('pathlib.Path.open', side_effect=AssertionError('pure projection accessed file')):
                    actual = diagnostic_recovery_profile(task, evidence)
                self.assertEqual(actual, fixture['expected'])
                self.assertEqual(task.model_dump(mode='json'), before_task)
                self.assertEqual(evidence, before_evidence)

    def test_api_adapter_preserves_compatibility(self):
        from app import main
        fixture = json.loads((Path(__file__).parent / 'fixtures' /
                              'recovery-guidance-e4ab6f1.json').read_text(encoding='utf-8'))[-1]
        task = TaskRecord(**fixture['task'])
        with patch.object(main, '_recovery_evidence', return_value=RecoveryEvidence(**fixture['evidence'])):
            self.assertEqual(main.diagnostic_recovery_profile(task), fixture['expected'])
