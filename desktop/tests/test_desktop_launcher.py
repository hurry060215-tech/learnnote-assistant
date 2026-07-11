from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "desktop" / "main.py"


def load_module():
    spec = importlib.util.spec_from_file_location("learnnote_desktop", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


desktop = load_module()


class DesktopLauncherTests(unittest.TestCase):
    def test_available_port_returns_loopback_bindable_port(self):
        port = desktop.available_port(18765)
        self.assertGreaterEqual(port, 18765)
        self.assertLess(port, 18785)

    def test_configure_runtime_uses_application_data_and_local_origin(self):
        previous = {key: os.environ.get(key) for key in (
            "LEARNNOTE_DATA_DIR",
            "LEARNNOTE_BACKEND_ORIGIN",
            "LEARNNOTE_DEPLOYMENT_MODE",
        )}
        try:
            with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
                root = Path(temp_dir)
                data_dir = desktop.configure_runtime(root, 18766)
                self.assertEqual(root / "data", data_dir)
                self.assertEqual(str(data_dir), os.environ["LEARNNOTE_DATA_DIR"])
                self.assertEqual("http://127.0.0.1:18766", os.environ["LEARNNOTE_BACKEND_ORIGIN"])
                self.assertEqual("desktop", os.environ["LEARNNOTE_DEPLOYMENT_MODE"])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_release_build_analyzes_dynamic_backend_imports(self):
        workflow = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")
        self.assertIn('--paths "backend"', workflow)
        self.assertIn("--hidden-import app.main", workflow)
        self.assertIn("--collect-submodules fastapi", workflow)
        self.assertIn('--version-file "build/learnnote-version.txt"', workflow)
        self.assertIn("LearnNote-Setup-x64.exe", workflow)

    def test_installer_defaults_to_d_drive_and_rejects_c_drive(self):
        installer = (ROOT / "scripts" / "learnnote-installer.iss").read_text(encoding="utf-8")
        self.assertIn("DefaultDirName=D:\\LearnNote", installer)
        self.assertIn("CompareText(ExtractFileDrive(WizardDirValue), 'C:') = 0", installer)
        self.assertIn("Result := False", installer)


if __name__ == "__main__":
    unittest.main()
