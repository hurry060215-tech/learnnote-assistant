import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).resolve().parents[1] / 'evidence-quality-benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkScoringTests(unittest.TestCase):
    def test_false_alarm_on_supported_note_fails_gate(self):
        with patch.object(benchmark, 'CASES', ({'id': 'supported', 'note': 'source', 'required': ()},)), patch.object(benchmark, 'note_grounding_issues', return_value=['unsupported_terms:wrong']):
            report = benchmark.run_benchmark()
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['passed_count'], 0)
        self.assertEqual(report['quality_metrics']['false_positive_cases'], 1)

    def test_missing_expected_issue_fails_gate(self):
        with patch.object(benchmark, 'CASES', ({'id': 'unsupported', 'note': 'source', 'required': ('unsupported_terms:',)},)), patch.object(benchmark, 'note_grounding_issues', return_value=[]):
            report = benchmark.run_benchmark()
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['quality_metrics']['false_negative_cases'], 1)
