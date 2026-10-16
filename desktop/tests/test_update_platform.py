"""Offline updater capability contracts; no installers or native UI run."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from desktop import main as desktop


class UpdatePlatformTests(unittest.TestCase):
    def test_unsupported_actions_fail_before_network_files_threads_or_processes(self):
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                api = desktop.DesktopApi(root)
                before = dict(api._update_state)
                with patch.object(desktop.sys, "platform", platform), patch.object(desktop.requests, "get") as request, patch.object(desktop.threading, "Thread") as thread, patch.object(desktop.subprocess, "Popen") as process:
                    for method, args in (
                        (api.download_update, ("9.8.7", "ignored", "a" * 64)),
                        (api.start_update_download, ("9.8.7", "ignored", "a" * 64)),
                        (api.apply_update, ("9.8.7", "ignored", "a" * 64)),
                        (api.install_update, ("9.8.7", "ignored")),
                        (api._install_verified_update, ("9.8.7", "ignored")),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "macOS / Linux"):
                            method(*args)
                    request.assert_not_called()
                    thread.assert_not_called()
                    process.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])
                self.assertEqual(api._update_state, before)

    def test_release_information_keeps_manual_guidance_without_windows_asset(self):
        payload = {
            "tag_name": "v9.8.7", "html_url": desktop.GITHUB_RELEASE_BASE + "/tag/v9.8.7",
            "assets": [{"name": desktop.WINDOWS_INSTALLER_NAME, "digest": "sha256:" + "a" * 64,
                        "browser_download_url": desktop.GITHUB_RELEASE_BASE + "/download/v9.8.7/" + desktop.WINDOWS_INSTALLER_NAME}],
        }
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
        for platform in ("darwin", "linux", "win32"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory, patch.object(desktop.sys, "platform", platform), patch.object(desktop.requests, "get", return_value=response) as request:
                result = desktop.DesktopApi(Path(directory)).check_update()
                request.assert_called_once()
                self.assertEqual(result["latest_version"], "9.8.7")
                self.assertEqual(result["installable"], platform == "win32")
                self.assertEqual(result["capabilities"]["apply"], platform == "win32")
                if platform != "win32":
                    self.assertEqual(result["installer_url"], "")
                    self.assertEqual(result["installer_sha256"], "")
                    self.assertIn("保留原数据目录", result["capabilities"]["manual_update_message"])

    def test_non_windows_release_page_fallback_never_fetches_executable_checksums(self):
        response = SimpleNamespace(raise_for_status=lambda: None, url=desktop.GITHUB_RELEASE_BASE + "/tag/v9.8.7")
        with tempfile.TemporaryDirectory() as directory, patch.object(desktop.sys, "platform", "darwin"), patch.object(desktop.requests, "get", side_effect=[desktop.requests.ConnectionError("offline API"), response]) as request:
            result = desktop.DesktopApi(Path(directory)).check_update()
        self.assertTrue(result["ok"])
        self.assertEqual(request.call_count, 2)
        self.assertFalse(result["installable"])

    def test_status_restricts_old_backend_and_fallback_without_mutating_metadata(self):
        metadata = {"ok": True, "current": {}, "capabilities": {"download": True, "apply": True, "desktop_controller": True}, "latest": {"version": "9.8.7", "client": {"installable": True, "url": "windows.exe", "sha256": "a" * 64}, "extension": {"available": True, "url": "extension.zip"}}}
        original = copy.deepcopy(metadata)
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: copy.deepcopy(metadata))
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory, patch.object(desktop.sys, "platform", platform):
                api = desktop.DesktopApi(Path(directory))
                api._update_state = {"phase": "ready", "version": "9.8.7", "path": "copied-windows.exe"}
                with patch.object(desktop.requests, "get", return_value=response):
                    result = api.update_status()
                self.assertFalse(result["capabilities"]["download"])
                self.assertFalse(result["capabilities"]["apply"])
                self.assertFalse(result["latest"]["client"]["installable"])
                self.assertEqual(result["latest"]["extension"], metadata["latest"]["extension"])
                with patch.object(desktop.requests, "get", side_effect=desktop.requests.ConnectionError("offline")), patch.object(api, "check_update", return_value={"ok": True, "latest_version": "9.8.7", "installable": True, "installer_url": "windows.exe"}):
                    fallback = api.update_status(True)
                self.assertFalse(fallback["capabilities"]["apply"])
                self.assertFalse(fallback["latest"]["client"]["installable"])
        self.assertEqual(metadata, original)
