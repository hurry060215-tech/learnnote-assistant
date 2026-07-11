from __future__ import annotations

import importlib.util
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_configure_model_runtime_uses_secure_kimi_credential(self):
        keys = (
            "LEARNNOTE_LLM_API_KEY",
            "LEARNNOTE_LLM_BASE_URL",
            "LEARNNOTE_LLM_MODEL",
        )
        previous = {key: os.environ.get(key) for key in keys}
        try:
            with patch.object(desktop, "read_secret", return_value="test-kimi-key"):
                self.assertTrue(desktop.configure_model_runtime())
            self.assertEqual("test-kimi-key", os.environ["LEARNNOTE_LLM_API_KEY"])
            self.assertEqual("https://api.moonshot.cn/v1", os.environ["LEARNNOTE_LLM_BASE_URL"])
            self.assertEqual("kimi-k2.6", os.environ["LEARNNOTE_LLM_MODEL"])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_configure_model_runtime_leaves_defaults_without_credential(self):
        with patch.object(desktop, "read_secret", return_value=""):
            self.assertFalse(desktop.configure_model_runtime())

    def test_native_export_saves_backend_artifact_under_data_directory(self):
        class Response:
            headers = {"Content-Disposition": "attachment; filename*=UTF-8''course-note.md"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                return iter((b"# Course\n", b"notes\n"))

        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            api = desktop.DesktopApi(Path(temp_dir), "http://127.0.0.1:18766")
            with patch.object(desktop.requests, "get", return_value=Response()) as request:
                result = api.export_task("abcdef123456", "markdown")
            target = Path(result["path"])
            self.assertEqual(Path(temp_dir) / "exports", target.parent)
            self.assertEqual("course-note.md", target.name)
            self.assertEqual(b"# Course\nnotes\n", target.read_bytes())
            request.assert_called_once_with(
                "http://127.0.0.1:18766/api/tasks/abcdef123456/exports/markdown",
                stream=True,
                timeout=(5.0, 180.0),
            )

    def test_native_export_rejects_unknown_task_or_type(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            api = desktop.DesktopApi(Path(temp_dir), "http://127.0.0.1:18766")
            with self.assertRaises(ValueError):
                api.export_task("../secrets", "markdown")
            with self.assertRaises(ValueError):
                api.export_task("abcdef123456", "unknown")

    def test_update_check_returns_verified_windows_installer_metadata(self):
        checksum = "a" * 64
        installer_url = (
            "https://github.com/hurry060215-tech/learnnote-assistant/"
            "releases/download/v9.8.7/LearnNote-Setup-x64.exe"
        )

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "tag_name": "v9.8.7",
                    "html_url": "https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v9.8.7",
                    "assets": [{
                        "name": "LearnNote-Setup-x64.exe",
                        "browser_download_url": installer_url,
                        "digest": f"sha256:{checksum}",
                    }],
                }

        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            api = desktop.DesktopApi(Path(temp_dir))
            with patch.object(desktop.requests, "get", return_value=Response()):
                result = api.check_update()
        self.assertTrue(result["ok"])
        self.assertTrue(result["installable"])
        self.assertEqual(installer_url, result["installer_url"])
        self.assertEqual(checksum, result["installer_sha256"])

    def test_update_download_verifies_checksum_and_stays_under_data(self):
        content = b"signed release installer bytes"
        checksum = hashlib.sha256(content).hexdigest()
        installer_url = (
            "https://github.com/hurry060215-tech/learnnote-assistant/"
            "releases/download/v9.8.7/LearnNote-Setup-x64.exe"
        )

        class Response:
            headers = {"Content-Length": str(len(content))}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                return iter((content[:10], content[10:]))

        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            api = desktop.DesktopApi(Path(temp_dir))
            with patch.object(desktop.requests, "get", return_value=Response()):
                result = api.download_update("9.8.7", installer_url, checksum)
            target = Path(result["path"])
            self.assertEqual(Path(temp_dir) / "installers" / "v9.8.7", target.parent)
            self.assertEqual(content, target.read_bytes())

    def test_update_check_falls_back_to_release_page_and_checksum_asset(self):
        checksum = "b" * 64

        class ApiLimitedResponse:
            def raise_for_status(self):
                raise desktop.requests.HTTPError("rate limited")

        class LatestReleaseResponse:
            url = "https://github.com/hurry060215-tech/learnnote-assistant/releases/tag/v9.8.7"

            def raise_for_status(self):
                return None

        class ChecksumsResponse:
            text = f"{checksum}  LearnNote-Setup-x64.exe\n"

            def raise_for_status(self):
                return None

        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            api = desktop.DesktopApi(Path(temp_dir))
            with patch.object(
                desktop.requests,
                "get",
                side_effect=[ApiLimitedResponse(), LatestReleaseResponse(), ChecksumsResponse()],
            ):
                result = api.check_update()
        self.assertTrue(result["installable"])
        self.assertEqual("9.8.7", result["latest_version"])
        self.assertEqual(checksum, result["installer_sha256"])

    def test_update_rejects_untrusted_url_and_arbitrary_installer_path(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            api = desktop.DesktopApi(Path(temp_dir))
            with self.assertRaises(ValueError):
                api.download_update("9.8.7", "https://example.com/LearnNote-Setup-x64.exe", "a" * 64)
            unrelated = Path(temp_dir) / "LearnNote-Setup-x64.exe"
            unrelated.write_bytes(b"not an update")
            with self.assertRaises(ValueError):
                api.install_update("9.8.7", str(unrelated))

    def test_update_install_schedules_wait_install_and_restart_script(self):
        class Window:
            def destroy(self):
                return None

        with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            installer = data_dir / "installers" / "v9.8.7" / "LearnNote-Setup-x64.exe"
            installer.parent.mkdir(parents=True)
            installer.write_bytes(b"verified installer")
            (root / "LearnNote.exe").write_bytes(b"desktop app")
            api = desktop.DesktopApi(data_dir)
            api._bind_window(Window())
            with (
                patch.object(desktop, "application_root", return_value=root),
                patch.object(desktop.subprocess, "Popen") as popen,
                patch.object(desktop.threading, "Timer") as timer,
            ):
                result = api.install_update("9.8.7", str(installer))
            script = (installer.parent / "install-update.ps1").read_text(encoding="utf-8-sig")
        self.assertTrue(result["installing"])
        self.assertIn("Wait-Process", script)
        self.assertIn("/VERYSILENT", script)
        self.assertIn("Start-Process -FilePath $app", script)
        popen.assert_called_once()
        timer.assert_called_once()
        timer.return_value.start.assert_called_once()

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
