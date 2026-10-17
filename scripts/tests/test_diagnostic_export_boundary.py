"""Keep content-free report I/O separate from pure document diagnostic fields."""
import ast
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("diagnostic_architecture", SCRIPTS / "check-architecture.py")
architecture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(architecture)


class DiagnosticExportBoundaryTests(unittest.TestCase):
    def test_report_and_shared_fields_have_tight_caps(self):
        self.assertIn("diagnostic_report", architecture.BOUNDARY_MODULES)
        self.assertEqual(architecture.PURE_MODULE_DEPENDENCIES["diagnostic_fields"], set())
        self.assertEqual(architecture.MODULE_SIZE_LIMITS["backend/app/diagnostic_report.py"], 220)
        self.assertEqual(architecture.MODULE_SIZE_LIMITS["backend/app/diagnostic_fields.py"], 60)

    def test_shared_fields_have_no_imports(self):
        source = (architecture.APP / "diagnostic_fields.py").read_text(encoding="utf-8")
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(ast.parse(source))))

    def test_shared_fields_cannot_gain_deferred_artifact_io(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "app"
            root.mkdir()
            (root / "__init__.py").write_text("")
            (root / "task_artifacts.py").write_text("def read(): pass\n")
            (root / "diagnostic_fields.py").write_text("def fields():\n    from .task_artifacts import read\n")
            errors = architecture.import_violations(root)
            self.assertTrue(any("pure-module boundary" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
