"""Offline fixture lifecycle regressions; visual rendering remains an Edge gate."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CommunityQuestionFixtureTests(unittest.TestCase):
    def test_held_preview_cleanup_and_browser_boundaries(self):
        subprocess.run(["node", "--test", "scripts/tests/community-question-fixture.test.cjs"],
                       cwd=ROOT, check=True, timeout=30)
