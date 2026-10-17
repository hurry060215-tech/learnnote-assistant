"""Local lifecycle/selector contracts; actual rendering belongs to hosted Edge."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CommunityCaptureFixtureTests(unittest.TestCase):
    def test_cleanup_races_and_shipped_selectors(self):
        subprocess.run(["node", "--test", "scripts/tests/community-capture-fixture.test.cjs"],
                       cwd=ROOT, check=True, timeout=30)
