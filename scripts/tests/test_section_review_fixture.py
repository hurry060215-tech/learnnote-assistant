"""The standalone fixture must resolve the same modules on Windows and Linux."""
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class SectionReviewFixtureTests(unittest.TestCase):
    def test_isolated_bootstrap_resolves_backend_and_desktop(self):
        # -I ignores inherited PYTHONPATH and the caller's working directory.
        # Importing the credential module only defines helpers; no vault read/write.
        code = """
import importlib.util, pathlib, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('review_fixture', root / 'scripts/section-review-fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
fixture.configure_import_paths(root)
import app, desktop.credentials
assert pathlib.Path(app.__file__).is_relative_to(root / 'backend')
assert pathlib.Path(desktop.credentials.__file__).is_relative_to(root / 'desktop')
"""
        with tempfile.TemporaryDirectory() as unrelated:
            result = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT)],
                                    cwd=unrelated, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
