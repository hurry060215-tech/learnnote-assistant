"""Shipped storage disclosure contracts; actual UI acceptance remains hosted."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SettingsManagementFixtureTests(unittest.TestCase):
    def test_management_disclosure_selection_and_content(self):
        subprocess.run(["node", "--test", "scripts/tests/settings-management-fixture.test.cjs"],
                       cwd=ROOT, check=True, timeout=30)
