"""Contract checks; the actual native keyboard/reflow result comes from Edge CI."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NativeTimelineZoomContract(unittest.TestCase):
    def test_setup_cleanup_and_reporting_failures_keep_original_error(self):
        subprocess.run(["node", str(ROOT / "scripts/tests/timeline-native-zoom-failures.cjs")], check=True, timeout=30)

    def test_keys_are_bound_to_owned_edge_process_and_window(self):
        source = (ROOT / "scripts/timeline-native-zoom.ps1").read_text(encoding="utf-8")
        for required in ("$OwnedBrowserPid", '$process.ProcessName -ne "msedge"', "OwnedWindows", "$windows.Count -ne 1", "GetWindowThreadProcessId", "GetForegroundWindow() -ne $window", 'Send-OwnedZoomKey "^0"', 'Send-OwnedZoomKey "^{ADD}"'):
            self.assertIn(required, source)
        for forbidden in ("SECURITY WARNING", "WM_CLOSE", "WM_COMMAND", "SetWindowPos", "--disable-extensions-except", "--load-extension"):
            self.assertNotIn(forbidden, source)

    def test_gate_measures_native_zoom_and_restores_owned_browser(self):
        source = (ROOT / "scripts/timeline-native-zoom-acceptance.cjs").read_text(encoding="utf-8")
        for required in ('channel: "msedge", headless: false', "server.process().pid", "viewport: null", 'nativeKey("200")', "devicePixelRatio / initial.dpr - 2", "innerWidth / initial.width - .5", "after.cssZoom", "after.documentZoom", "after.visualScale", "after.overflow", 'page.keyboard.press("Enter")', 'page.keyboard.press("End")', 'nativeKey("reset")', "server.close()"):
            self.assertIn(required, source)
        for forbidden in ("setDeviceMetricsOverride", "setPageScaleFactor", "deviceScaleFactor:", "style.zoom", "connectOverCDP", "launchPersistentContext", "--load-extension"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
