from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from architecture_graph import dependency_cycles, python_import_edges

spec = importlib.util.spec_from_file_location("check_architecture", SCRIPTS / "check-architecture.py")
architecture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(architecture)


class ArchitectureGraphTests(unittest.TestCase):
    def package(self, contents):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "app"
        root.mkdir()
        (root / "__init__.py").write_text("")
        for name, content in contents.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return root

    def test_relative_absolute_alias_and_deferred_edges_are_detected(self):
        root = self.package({
            "alpha.py": "from . import beta as renamed\ndef later():\n    import app.gamma as g\n",
            "beta.py": "from backend.app.gamma import value\n",
            "gamma.py": "value = 1\n",
            "routers/__init__.py": "",
            "routers/tasks.py": "from ..alpha import later\n",
        })
        edges = python_import_edges(root)
        observed = {(edge.source, edge.target, edge.deferred) for edge in edges}
        self.assertIn(("app.alpha", "app.beta", False), observed)
        self.assertIn(("app.alpha", "app.gamma", True), observed)
        self.assertIn(("app.beta", "app.gamma", False), observed)
        self.assertIn(("app.routers.tasks", "app.alpha", False), observed)
        self.assertEqual(dependency_cycles(edges), [])

    def test_new_cycle_fails_even_when_one_import_is_deferred(self):
        root = self.package({"alpha.py": "from .beta import run\n", "beta.py": "def run():\n    from . import alpha\n"})
        self.assertEqual(dependency_cycles(python_import_edges(root)), [("app.alpha", "app.beta")])
        self.assertTrue(any("dependency cycle" in item for item in architecture.import_violations(root)))

    def test_cross_layer_alias_and_from_package_imports_fail(self):
        root = self.package({
            "main.py": "value = 1\n",
            "processor.py": "value = 1\n",
            "media_discovery.py": "from . import main as endpoint\n",
            "routers/__init__.py": "",
            "routers/tasks.py": "from app import processor as pipeline\n",
        })
        errors = architecture.import_violations(root)
        self.assertTrue(any("forbidden app.main" in error for error in errors))
        self.assertTrue(any("forbidden app.processor" in error for error in errors))
        self.assertTrue(any("pure-module boundary" in error for error in errors))

    def test_pure_parser_cannot_import_storage_even_without_cycle(self):
        root = self.package({"media_manifests.py": "from .storage import read\n", "storage.py": "def read(): pass\n"})
        self.assertTrue(any("pure-module boundary" in error for error in architecture.import_violations(root)))

    def test_only_exact_legacy_deferred_edge_is_exempt(self):
        root = self.package({"storage.py": "def cancel():\n    from .task_queue import stop\n", "task_queue.py": "from .storage import cancel\ndef stop(): pass\n"})
        self.assertEqual(architecture.import_violations(root), [])
        (root / "storage.py").write_text("from .task_queue import stop\ndef cancel(): pass\n")
        self.assertTrue(any("dependency cycle" in error for error in architecture.import_violations(root)))

    def test_aggregate_budget_counts_every_extracted_module(self):
        root = self.package({"one.py": "line\n" * 3, "two.py": "line\n" * 3})
        extension = root.parent / "extension"
        extension.mkdir()
        for name in ("background.js", "content.js", "page_hook.js"):
            (extension / name).write_text("abc")
        with patch.object(architecture, "APP", root), patch.object(architecture, "ROOT", root.parent), \
             patch.object(architecture, "EXTRACTED_BACKEND_MODULES", ("one", "two")), \
             patch.object(architecture, "EXTRACTED_BACKEND_BUDGET", 5), \
             patch.object(architecture, "EXTENSION_SCRIPT_BUDGET_BYTES", 8):
            errors = architecture.aggregate_size_violations()
        self.assertEqual(len(errors), 2)
        self.assertIn("6 lines", errors[0])
        self.assertIn("9 bytes", errors[1])

    def test_repository_has_no_new_cycles_or_boundary_regressions(self):
        self.assertEqual(architecture.import_violations(), [])
        self.assertEqual(architecture.aggregate_size_violations(), [])


if __name__ == "__main__":
    unittest.main()
