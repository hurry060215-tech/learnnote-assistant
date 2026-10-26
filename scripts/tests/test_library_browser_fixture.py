"""Keep synthetic browser catalogs and bounded paging in the core test gate."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LibraryBrowserFixtureTests(unittest.TestCase):
    def test_catalog_and_paging_boundaries(self):
        subprocess.run(["node", "--test", "scripts/tests/library-browser-fixture.test.cjs"],
                       cwd=ROOT, check=True, timeout=30)

    def test_shared_fixture_changes_trigger_both_visual_events(self):
        workflow = (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8")
        for name in ("scripts/library-browser-fixture.cjs", "scripts/tests/library-browser-fixture.test.cjs",
                     "scripts/tests/test_library_browser_fixture.py"):
            self.assertEqual(workflow.count('"' + name + '"'), 2, name)
