"""Keep all hosted sidepanel asset paths synchronized with shipped imports."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SidepanelAssetTests(unittest.TestCase):
    def test_shipped_references_and_server_boundaries(self):
        subprocess.run(["node", "--test", "scripts/tests/sidepanel-assets.test.cjs"],
                       cwd=ROOT, check=True, timeout=30)
