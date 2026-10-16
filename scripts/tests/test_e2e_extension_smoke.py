from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ExtensionSmokeIsolationTests(unittest.TestCase):
    def test_browser_profile_and_logs_follow_the_isolated_data_directory(self) -> None:
        source = (ROOT / "scripts" / "e2e-extension-smoke.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("LEARNNOTE_DATA_DIR", str(ROOT / "data"))', source)
        self.assertIn('data_root / "browser-profiles" / "e2e"', source)
        self.assertIn('data_root / "test-runs" / "e2e-logs"', source)

    def test_temporary_browser_profile_is_removed_after_the_browser_stops(self) -> None:
        source = (ROOT / "scripts" / "e2e-extension-smoke.py").read_text(encoding="utf-8")
        stop_browser = source.index("stop_process(browser_process)")
        remove_profile = source.index("shutil.rmtree(profile_dir, ignore_errors=True)")
        stop_samples = source.index("stop_process(samples_process)", stop_browser)

        self.assertGreater(remove_profile, stop_browser)
        self.assertLess(remove_profile, stop_samples)
        self.assertIn("if not args.keep_browser:", source[max(0, stop_browser - 120):stop_browser])

    def test_extension_smoke_reports_removed_chrome_cli_flags(self) -> None:
        source = (ROOT / "scripts" / "e2e-extension-smoke.py").read_text(encoding="utf-8")
        self.assertIn("--(?:load-extension|disable-extensions-except)", source)
        self.assertIn("Chrome for Testing", source)
        self.assertIn("extension-browser.log", source)

    def test_hosted_real_extension_gate_uses_fresh_synthetic_profile_and_no_secrets(self) -> None:
        workflow = (ROOT / ".github/workflows/ui-visual.yml").read_text(encoding="utf-8")
        job = workflow.split("  extension-runtime:", 1)[1].split("  public-site:", 1)[0]
        self.assertIn("runs-on: windows-latest", job)
        self.assertIn("--browser edge --backend-port 0 --samples-port 0 --debug-port 0", job)
        self.assertIn("LEARNNOTE_DATA_DIR:", job)
        self.assertIn("unpacked checkout", job)
        self.assertIn("excluded =", job)
        self.assertNotIn("secrets.", job)
        self.assertNotIn("--keep-browser", job)
        self.assertNotIn("--no-sandbox", job)
        self.assertNotIn("browser-profiles", job.split("path:", 1)[1])
        self.assertIn("contents: read", workflow)

    def test_extension_smoke_requires_backend_protocol_compatibility(self) -> None:
        source = (ROOT / "scripts" / "e2e-extension-smoke.py").read_text(encoding="utf-8")
        self.assertIn('heartbeat_health.get("extension_protocol_version") != heartbeat_health.get("protocol_version")', source)
        self.assertIn('heartbeat_health.get("extension_compatible") is False', source)


if __name__ == "__main__":
    unittest.main()
