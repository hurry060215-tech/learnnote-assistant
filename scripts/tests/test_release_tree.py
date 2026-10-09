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
        icons = extension / "icons"
        icons.mkdir()
        for name in MODULE.REQUIRED_EXTENSION_ICONS:
            (icons / name).write_bytes(b"png")

    def populate_legal_files(self, root: Path) -> None:
        for name in MODULE.REQUIRED_ROOT_FILES:
            (root / name).write_text(name, encoding="utf-8")

    def populate_bundled_files(self, root: Path) -> None:
        for relative in MODULE.REQUIRED_BUNDLED_FILES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")

    def test_clean_runtime_tree_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            self.populate_legal_files(root)
            self.populate_bundled_files(root)
            (root / "LearnNote.exe").write_bytes(b"exe")
            self.assertTrue(MODULE.audit_release_tree(root)["passed"])

    def test_test_and_cache_files_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            self.populate_legal_files(root)
            self.populate_bundled_files(root)
            tests = root / "_internal" / "backend" / "tests"
            tests.mkdir(parents=True)
            (tests / "test_api.py").write_text("", encoding="utf-8")
            result = MODULE.audit_release_tree(root)
            self.assertFalse(result["passed"])
            self.assertEqual(1, len(result["forbidden"]))

    def test_missing_release_notes_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            self.populate_legal_files(root)
            self.populate_bundled_files(root)
            (root / "_internal/web/release-notes.json").unlink()
            result = MODULE.audit_release_tree(root)
            self.assertFalse(result["passed"])
            self.assertEqual(["_internal/web/release-notes.json"], result["missing_bundled"])

    def test_missing_reader_encoding_module_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            self.populate_legal_files(root)
            self.populate_bundled_files(root)
            (root / "_internal/web/desk-material-encoding.js").unlink()
            result = MODULE.audit_release_tree(root)
            self.assertFalse(result["passed"])
            self.assertEqual(["_internal/web/desk-material-encoding.js"], result["missing_bundled"])

    def test_missing_study_quiz_module_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            self.populate_legal_files(root)
            self.populate_bundled_files(root)
            (root / "_internal/web/study-quiz.js").unlink()
            result = MODULE.audit_release_tree(root)
            self.assertFalse(result["passed"])
            self.assertEqual(["_internal/web/study-quiz.js"], result["missing_bundled"])


    def test_missing_batch_import_modules_fail(self):
        for filename in ("desk-material-batch.js", "material-batch.js"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                self.populate_extension(root)
                self.populate_legal_files(root)
                self.populate_bundled_files(root)
                relative = Path("_internal/web") / filename
                (root / relative).unlink()
                result = MODULE.audit_release_tree(root)
                self.assertFalse(result["passed"])
                self.assertEqual([relative.as_posix()], result["missing_bundled"])

    def test_missing_personal_anchor_module_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            self.populate_legal_files(root)
            self.populate_bundled_files(root)
            (root / "_internal/web/personal-anchors.js").unlink()
            result = MODULE.audit_release_tree(root)
            self.assertFalse(result["passed"])
            self.assertEqual(["_internal/web/personal-anchors.js"], result["missing_bundled"])

    def test_missing_material_ocr_module_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.populate_extension(root)
            self.populate_legal_files(root)
            self.populate_bundled_files(root)
            (root / "_internal/web/material-ocr.js").unlink()
            result = MODULE.audit_release_tree(root)
            self.assertFalse(result["passed"])
            self.assertEqual(["_internal/web/material-ocr.js"], result["missing_bundled"])


if __name__ == "__main__":
    unittest.main()
