from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("validate_store_package", ROOT / "scripts" / "validate-store-package.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class StorePackageTests(unittest.TestCase):
    def test_valid_mv3_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extension.zip"
            with ZipFile(path, "w", ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps({"manifest_version": 3, "version": "0.1.54"}))
                for name in MODULE.REQUIRED - {"manifest.json"}:
                    archive.writestr(name, "safe local extension content")
            result = MODULE.validate(path, "0.1.54")
            self.assertEqual(result["status"], "pass")

    def test_secret_like_package_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extension.zip"
            with ZipFile(path, "w", ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps({"manifest_version": 3, "version": "0.1.54"}))
                for name in MODULE.REQUIRED - {"manifest.json"}:
                    archive.writestr(name, "api_key=sk-abcdefghijklmnopqrstuvwxyz")
            with self.assertRaisesRegex(ValueError, "secret-like"):
                MODULE.validate(path, "0.1.54")


if __name__ == "__main__":
    unittest.main()
