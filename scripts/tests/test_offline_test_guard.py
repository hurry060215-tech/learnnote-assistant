import importlib.util
from pathlib import Path
import socket
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("offline_test_guard", ROOT / "scripts/test-backend-offline.py")
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class OfflineTestGuardTests(unittest.TestCase):
    def test_external_dns_socket_http_and_downloader_fail_before_transport(self):
        import requests
        with GUARD.offline_network():
            with self.assertRaisesRegex(OSError, "external DNS"):
                socket.getaddrinfo("fixture.invalid", 443)
            for method in ("connect", "connect_ex"):
                with socket.socket() as client, self.assertRaisesRegex(OSError, "external network"):
                    getattr(client, method)(("192.0.2.1", 443))
            with self.assertRaisesRegex(requests.ConnectionError, "external HTTP"):
                requests.get("https://fixture.invalid", timeout=1)
            with self.assertRaisesRegex(OSError, "external yt-dlp"):
                subprocess.Popen(["yt-dlp", "https://fixture.invalid"])

    def test_loopback_resolution_is_kept_for_local_api_contracts(self):
        with GUARD.offline_network():
            self.assertTrue(socket.getaddrinfo("127.0.0.1", 8765))

    def test_core_ci_uses_offline_backend_runner(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("python scripts/test-backend-offline.py", workflow)
