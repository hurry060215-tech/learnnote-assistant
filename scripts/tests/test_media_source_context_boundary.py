"""Prevent source interpretation from regrowing transport or storage coupling."""
from __future__ import annotations

import ast
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("source_context_architecture", SCRIPTS / "check-architecture.py")
architecture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(architecture)


class MediaSourceContextBoundaryTests(unittest.TestCase):
    def test_source_context_has_dependency_and_individual_and_aggregate_guards(self):
        self.assertIn("media_source_context", architecture.BOUNDARY_MODULES)
        self.assertEqual(architecture.PURE_MODULE_DEPENDENCIES["media_source_context"],
                         {"models", "media_kinds", "media_candidate_ranking", "media_url_parsing"})
        self.assertLessEqual(architecture.MODULE_SIZE_LIMITS["backend/app/downloader.py"], 2520)
        self.assertLessEqual(architecture.MODULE_SIZE_LIMITS["backend/app/media_source_context.py"], 300)
        self.assertIn("media_source_context", architecture.EXTRACTED_BACKEND_MODULES)
        self.assertLessEqual(architecture.EXTRACTED_BACKEND_BUDGET, 9250)

    def test_source_context_rejects_deferred_transport_and_storage_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "app"
            root.mkdir()
            (root / "__init__.py").write_text("")
            for target in ("downloader", "processor", "main", "storage", "media_transport", "runtime"):
                with self.subTest(target=target):
                    (root / f"{target}.py").write_text("def run(): pass\n")
                    (root / "media_source_context.py").write_text(f"def context():\n    from .{target} import run\n")
                    errors = architecture.import_violations(root)
                    self.assertTrue(any("pure-module boundary" in error and target in error for error in errors), errors)

    def test_source_context_external_imports_are_only_pure_standard_library(self):
        module = architecture.APP / "media_source_context.py"
        imports = set()
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                imports.add(node.module)
        self.assertEqual(imports, {"__future__", "re", "urllib.parse"})


if __name__ == "__main__":
    unittest.main()
