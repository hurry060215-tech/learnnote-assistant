from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "audit-release-tree.py"
SPEC = importlib.util.spec_from_file_location("audit_release_tree", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReleaseTreeAuditTests(unittest.TestCase):
    def populate_extension(self, root: Path) -> None:
        extension = root / "extension"
        extension.mkdir()
        for name in MODULE.REQUIRED_EXTENSION_FILES:
            (extension / name).write_text(name, encoding="utf-8")

    def test_clean_runtime_tree_passes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            (root / "LearnNote.exe").write_bytes(b"exe")
            self.assertTrue(MODULE.audit_release_tree(root)["passed"])

    def test_test_and_cache_files_fail(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            tests = root / "_internal" / "backend" / "tests"
            tests.mkdir(parents=True)
            (tests / "test_api.py").write_text("", encoding="utf-8")
            result = MODULE.audit_release_tree(root)
            self.assertFalse(result["passed"])
            self.assertEqual(1, len(result["forbidden"]))


if __name__ == "__main__":
    unittest.main()
